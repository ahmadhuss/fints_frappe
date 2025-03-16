import frappe
from frappe.utils import now_datetime

import json
import base64
import hashlib
import mt940


def transactions_manage_response(f=None, fints_doc=None, stmt_doc=None, transactions=None,
                                 start_date=None, end_date=None, is_tan_response=False):
    """
        Processes and manages the response for fetched transactions from a FinTS session.
        Args:
            f (FinTS3PinTanClient): The FinTS client handling the session.
            fints_doc (Document): The 'FinTS Statement Import' document instance.
            stmt_doc (Document): The ERPNext Statement document where transactions are stored.
            transactions (list): The list of fetched transaction records.
            start_date (date): The start date of the transaction period (datetime.date).
            end_date (date): The end date of the transaction period (datetime.date).
            is_tan_response (bool): Flag indicating if this response is part of a TAN request.
        Returns:
            dict: Response containing success status and TAN requirement.
    """
    print("\n\n Found", len(transactions), "transactions \n\n")
    print("\n\n Transactions raw format:", transactions, "\n\n")

    json_data = json.dumps(transactions, cls=mt940.JSONEncoder, indent=4)
    print(f"\n\n json_data:{json_data} \n\n")
    # Save the Dialog State for the future operations
    dialog_data = f.pause_dialog()
    from_data = f.deconstruct(including_private=True)
    # Convert to Base64 for easy storage
    from_data_encoded = base64.b64encode(from_data).decode("ascii")
    dialog_data_encoded = base64.b64encode(dialog_data).decode("ascii")
    # ==================================
    # Hash each JSON object
    # ==================================
    company_info = {
        "company": fints_doc.company,
        "bank_account": fints_doc.bank_account
    }
    transactions_unhashed = json.loads(json_data)
    if len(transactions_unhashed) > 0:
        for txn_dict in transactions_unhashed:
            txn_dict["hash"] = get_json_dictionary_hash(txn_dict)

        create_and_check_bank_transaction_entry(transactions_unhashed, company_info=company_info)
        json_data = json.dumps(transactions_unhashed, indent=4)
        print(f"\n\n transactions_unhashed:{json_data} \n\n")
    # ==================================
    # End - Hash each JSON object
    # ==================================

    # Save the state in the
    timestamp = now_datetime()
    stmt_doc.sync_count += 1
    stmt_doc.sync_timestamp = timestamp
    stmt_doc.append("sync_history", {
        "sync_timestamp": timestamp,
        "total": len(transactions),
        "start_date": start_date,
        "end_date": end_date,
        "sync_json": json_data
    })
    stmt_doc.from_data_state = from_data_encoded
    stmt_doc.pause_dialog_state = dialog_data_encoded
    if is_tan_response:
        stmt_doc.tan_data_response = ""
        stmt_doc.challenge = ""
    stmt_doc.save(ignore_permissions=True)

    return {
        "ok": True,
        "tan_required": False,
        "message": "The transactions have been fetched."
    }


def get_json_dictionary_hash(txn_dict):
    """
       Generate a SHA-256 hash for a given dictionary (JSON object).
       Args:
           txn_dict (dict): The transaction dictionary to be hashed.
       Returns:
           str: The SHA-256 hash as a hexadecimal string.
    """
    canonical_str = json.dumps(txn_dict, sort_keys=True)
    return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()


def create_and_check_bank_transaction_entry(transactions, company_info):
    """
         Creates bank transaction entries in ERPNext if they do not already exist.
         Args:
             transactions (list): A list of transaction dictionaries.
             company_info (dict): Contains company-related details like company name and bank account.
         Returns:
             None
     """
    if len(transactions) > 0:
        for txn_dict in transactions:
            if not frappe.db.exists("Bank Transaction", {"custom_hash": txn_dict.get("hash")}):
                print(f"\n\n Bank Transaction does not exists. \n\n")

                deposit = float(txn_dict.get("amount", {}).get("amount", 0)) if txn_dict.get("status") == "C" else 0
                withdrawal = abs(float(txn_dict.get("amount", {}).get("amount", 0))) if txn_dict.get(
                    "status") == "D" else 0
                transaction_type = ""
                if txn_dict.get("status") == "D":
                    transaction_type = "Debit"
                elif txn_dict.get("status") == "C":
                    transaction_type = "Credit"

                party = ""
                customer_id = frappe.db.get_value("Customer", txn_dict.get("applicant_name"), "name")
                if customer_id:
                    party = customer_id

                bank_transaction = frappe.get_doc({
                    "doctype": "Bank Transaction",
                    "company": company_info.get("company", ""),
                    "bank_account": company_info.get("bank_account", ""),
                    "date": txn_dict.get("date" ""),
                    "entry_date": txn_dict.get("entry_date", ""),
                    "guessed_entry_date": txn_dict.get("guessed_entry_date", ""),
                    "status": "Unreconciled",
                    "transaction_type": transaction_type,
                    "transaction_reference": txn_dict.get("transaction_reference", ""),
                    "transaction_code": txn_dict.get("transaction_code", ""),
                    "deposit": deposit,
                    "withdrawal": withdrawal,
                    "currency": txn_dict.get("amount", {}).get("currency"),
                    "description": txn_dict.get('purpose', ""),
                    "posting_text": txn_dict.get("posting_text", ""),
                    "reference_number": txn_dict.get("customer_reference", ""),
                    "bank_reference": txn_dict.get("bank_reference", ""),
                    "party_type": "Customer",
                    "party": party,
                    "bank_party_name": txn_dict.get("applicant_name", ""),
                    "bank_party_iban": txn_dict.get("applicant_iban", ""),
                    "bank_party_bin": txn_dict.get("applicant_bin", ""),
                    "funds_code": txn_dict.get("funds_code", ""),
                    "hash": txn_dict.get("hash", ""),
                    "id": txn_dict.get("id", ""),
                    "primary_note": txn_dict.get("prima_nota", ""),
                    "extra_details": txn_dict.get("extra_details", ""),
                    "return_debit_notes": txn_dict.get("return_debit_notes", ""),
                    "recipient_name": txn_dict.get("recipient_name", ""),
                    "additional_purpose": txn_dict.get("additional_purpose", ""),
                    "gvc_applicant_iban": txn_dict.get("gvc_applicant_iban", ""),
                    "gvc_applicant_bin": txn_dict.get("gvc_applicant_bin", ""),
                    "end_to_end_reference": txn_dict.get("end_to_end_reference", ""),
                    "additional_position_reference": txn_dict.get("additional_position_reference", ""),
                    "applicant_creditor_id": txn_dict.get("applicant_creditor_id", ""),
                    "purpose_code": txn_dict.get("purpose_code", ""),
                    "additional_position_date": txn_dict.get("additional_position_date", ""),
                    "deviate_applicant": txn_dict.get("deviate_applicant", ""),
                    "deviate_recipient": txn_dict.get("deviate_recipient", ""),
                    "first_one_off_recurring": txn_dict.get("FRST_ONE_OFF_RECC", ""),
                    "old_sepa_ci": txn_dict.get("old_SEPA_CI", ""),
                    "old_sepa_additional_position_reference": txn_dict.get(
                        "old_SEPA_additional_position_reference", ""),
                    "settlement_tag": txn_dict.get("settlement_tag", ""),
                    "debitor_identifier": txn_dict.get("debitor_identifier", ""),
                    "compensation_amount": txn_dict.get("compensation_amount", ""),
                    "original_amount": txn_dict.get("original_amount", ""),
                })
                bank_transaction.save(ignore_permissions=True)
                bank_transaction.submit()
