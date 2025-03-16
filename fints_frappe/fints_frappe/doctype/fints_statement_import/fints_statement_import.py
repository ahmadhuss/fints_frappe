# Copyright (c) 2025, Ahmad Hussnain and contributors
# For license information, please see license.txt

import frappe
import base64
import traceback

from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, today

from datetime import datetime

# python-fints
import fints.segments.statement
from fints.client import FinTS3PinTanClient, NeedTANResponse, NeedRetryResponse
from fints.utils import mt940_to_array

from fints_frappe.fints_frappe.doctype.fints_statement_import.fints_helpers import transactions_manage_response


class FinTSStatementImport(Document):
    pass


@frappe.whitelist(methods=["POST"])
def fetch_tan_mechanisms(docname=None):
    """
      Fetches available TAN mechanisms for a given 'FinTS Statement Import' document.
      Args:
          docname (str): The name of the 'FinTS Statement Import' document.
      Returns:
          dict: Response containing available TAN mechanisms or an error message.
      """
    try:
        if not docname:
            frappe.throw(_("Missing docname for FinTS Statement Import."))

        stmt_doc = frappe.get_doc("FinTS Statement Import", docname)
        if not stmt_doc.fints_account:
            frappe.throw(_("Please set 'FinTS Account' first."))

        # Grab FinTS Settings
        fints_doc = frappe.get_doc("FinTS Settings", stmt_doc.fints_account)

        # Brand new FinTS Client
        client = FinTS3PinTanClient(
            bank_identifier=fints_doc.blz,
            user_id=fints_doc.username,
            pin=fints_doc.get_password("password"),
            server=fints_doc.endpoint_url,
            product_id=fints_doc.get_password("product_id")
        )

        if not client.get_current_tan_mechanism():
            client.fetch_tan_mechanisms()
            mechanisms = client.get_tan_mechanisms()  # OrderedDict
            if len(list(mechanisms.items())) > 1:
                # Convert mechs to a list/dict for JSON
                mechanism_list = []
                for key, val in mechanisms.items():
                    mechanism_list.append({
                        "id": key,
                        "name": val.name or f"Mechanism {key}"
                    })

                # Store updated session state of this client
                # including_private=True represents
                # When you restore the client later, it knows everything, including account details.
                # it will store the bank information in the state
                new_data = client.deconstruct(including_private=True)
                stmt_doc.from_data_state = base64.b64encode(new_data).decode("ascii")
                stmt_doc.save(ignore_permissions=True)

                return {
                    "ok": True,
                    "mechanisms": mechanism_list,
                    "message": _("Found {0} TAN mechanism(s).").format(len(mechanism_list))
                }
        if client.selected_tan_medium is None and client.is_tan_media_required():
            return {
                "ok": False,
                "mechanisms": [],
                "message": _(
                    "The following bank requires a TAN medium selection mechanism, which will be implemented at a later stage.")
            }
    except Exception as e:
        frappe.throw(str(e))


@frappe.whitelist(methods=["POST"])
def select_tan_mechanism(docname=None, mechanism_id=None):
    """
        Selects a TAN mechanism for a given 'FinTS Statement Import' document.
        Args:
            docname (str): The name of the 'FinTS Statement Import' document.
            mechanism_id (str): The ID of the TAN mechanism to be selected.
        Returns:
            dict: Response confirming the TAN mechanism selection.
    """
    try:
        if not docname or not mechanism_id:
            frappe.throw(_("Missing docname or mechanism_id."))

        # Load docs
        stmt_doc = frappe.get_doc("FinTS Statement Import", docname)
        if not stmt_doc.fints_account:
            frappe.throw(_("No FinTS Account set on doc."))

        fints_doc = frappe.get_doc("FinTS Settings", stmt_doc.fints_account)

        if not stmt_doc.from_data_state:
            frappe.throw(
                _("The mechanism will not be set because there is no saved connection state for the fetch mechanism. Please reset the connection and perform both Step 1 and Step 2 from the beginning."))

        # Possibly restore previous from_data
        from_data_bytes = base64.b64decode(stmt_doc.from_data_state)
        client = FinTS3PinTanClient(
            bank_identifier=fints_doc.blz,
            user_id=fints_doc.username,
            pin=fints_doc.get_password("password"),
            server=fints_doc.endpoint_url,
            product_id=fints_doc.get_password("product_id"),
            from_data=from_data_bytes
        )

        client.set_tan_mechanism(mechanism_id)

        new_data = client.deconstruct(including_private=True)
        stmt_doc.from_data = base64.b64encode(new_data).decode("ascii")

        stmt_doc.mechanism_connected = True
        stmt_doc.selected_mechanism_id = mechanism_id

        stmt_doc.save(ignore_permissions=True)

        return {
            "ok": True,
            "message": _("TAN mechanism {0} set successfully.").format(mechanism_id)
        }
    except Exception as e:
        # frappe.db.rollback()
        frappe.logger().error("select_tan_mechanism error: " + traceback.format_exc())
        frappe.throw(str(e))


@frappe.whitelist(methods=["POST"])
def get_set_account_iban(docname=None):
    """
        Fetches and sets the IBAN for a selected FinTS account.
        Args:
            docname (str): The name of the 'FinTS Statement Import' document.
        Returns:
            dict: Response indicating whether an account has been selected or if a TAN is required.
    """
    try:
        if not docname:
            frappe.throw(_("Missing docname for FinTS Statement Import."))

        stmt_doc = frappe.get_doc("FinTS Statement Import", docname)
        if not stmt_doc.fints_account:
            frappe.throw(_("Please set 'FinTS Account' first."))

        # Grab FinTS Settings
        fints_doc = frappe.get_doc("FinTS Settings", stmt_doc.fints_account)

        if not (stmt_doc.mechanism_connected or stmt_doc.selected_mechanism_id):
            frappe.throw(
                _("Step 1 is missing. The \"Get Account\" function only works if Step 1 is completed. Please first retrieve the mechanisms and assign them."));

        if not stmt_doc.from_data_state:
            frappe.throw(
                _("The account get will not work because there is no saved connection state for the fetch mechanism. Please reset the connection and perform both Step 1 and Step 2 from the beginning."))

        # Possibly restore previous from_data
        from_data_bytes = base64.b64decode(stmt_doc.from_data_state)
        f = FinTS3PinTanClient(
            bank_identifier=fints_doc.blz,
            user_id=fints_doc.username,
            pin=fints_doc.get_password("password"),
            server=fints_doc.endpoint_url,
            product_id=fints_doc.get_password("product_id"),
            from_data=from_data_bytes
        )

        # If there is not any dialog data Open a new session with with client
        if stmt_doc.from_data_state and not stmt_doc.pause_dialog_state:
            # Open a new session with the client.
            with f:
                # Since PSD2, a TAN might be needed for dialog initialization. Let's check if there is one required
                # If "f.init_tan_response" exists, it means the bank is waiting for the user to enter a TAN.
                if isinstance(f.init_tan_response, NeedTANResponse):
                    # Once you pause it, you cannot issue any more commands in that session until it's resumed.
                    # It freezes the current banking session (where you might be in the middle of entering a TAN)
                    # so you can stop temporarily and resume later without losing progress.
                    # including_private=True means:
                    # When you restore the client later, it knows everything, including account details.
                    # it will store the bank information in the state
                    dialog_data = f.pause_dialog()
                    from_data = f.deconstruct(including_private=True)
                    tan_response_data = f.init_tan_response.get_data()  # Return a compressed datablob representing this object.

                    # Convert to Base64 for easy storage
                    from_data_encoded = base64.b64encode(from_data).decode("ascii")
                    dialog_data_encoded = base64.b64encode(dialog_data).decode("ascii")
                    tan_data_encoded = base64.b64encode(tan_response_data).decode("ascii")

                    # Challenge & Decoupled
                    challenge = f.init_tan_response.challenge or "A TAN is Required"
                    decoupled = f.init_tan_response.decoupled

                    # Save the state in the
                    stmt_doc.from_data_state = from_data_encoded
                    stmt_doc.pause_dialog_state = dialog_data_encoded
                    stmt_doc.tan_data_response = tan_data_encoded
                    stmt_doc.challenge = challenge
                    stmt_doc.save(ignore_permissions=True)

                    # Decoupled means: the TAN is handled separately (outside your app).
                    # You don’t need to enter the TAN manually because it is confirmed in
                    # another place, like your bank’s mobile app.
                    if decoupled:
                        msg = "Decoupled:True Means Just confirmation will be done on your bank mobile app."
                    else:
                        msg = "Decoupled:False Means Bank sent a code on the mobile app that we have to enter here in ERPNext."

                    # Return the response
                    return {
                        "ok": False,  # required
                        "tan_required": True,  # required
                        "message": "A Tan is required",  # required
                        "challenge": challenge,
                        "decoupled": decoupled
                    }
                else:
                    accounts = f.get_sepa_accounts()

                    if isinstance(accounts, NeedTANResponse):
                        dialog_data = f.pause_dialog()
                        from_data = f.deconstruct(including_private=True)
                        tan_response_data = accounts.get_data()

                        # Convert to Base64 for easy storage
                        from_data_encoded = base64.b64encode(from_data).decode("ascii")
                        dialog_data_encoded = base64.b64encode(dialog_data).decode("ascii")
                        tan_data_encoded = base64.b64encode(tan_response_data).decode("ascii")

                        # Challenge & Decoupled
                        challenge = f.init_tan_response.challenge or "A TAN is Required"
                        decoupled = f.init_tan_response.decoupled

                        # Save the state in the
                        stmt_doc.from_data_state = from_data_encoded
                        stmt_doc.pause_dialog_state = dialog_data_encoded
                        stmt_doc.tan_data_response = tan_data_encoded
                        stmt_doc.challenge = challenge
                        stmt_doc.save(ignore_permissions=True)

                        # Decoupled means: the TAN is handled separately (outside your app).
                        # You don’t need to enter the TAN manually because it is confirmed in
                        # another place, like your bank’s mobile app.
                        if decoupled:
                            msg = "Decoupled:True Means Just confirmation will be done on your bank mobile app."
                        else:
                            msg = "Decoupled:False Means Bank sent a code on the mobile app that we have to enter here in ERPNext."

                        # Return the response
                        return {
                            "ok": False,  # required
                            "tan_required": True,  # required
                            "message": "A Tan is required",  # required
                            "challenge": challenge,
                            "decoupled": decoupled
                        }
                    else:
                        account = accounts[0]

                        dialog_data = f.pause_dialog()
                        from_data = f.deconstruct(including_private=True)
                        # Convert to Base64 for easy storage
                        from_data_encoded = base64.b64encode(from_data).decode("ascii")
                        dialog_data_encoded = base64.b64encode(dialog_data).decode("ascii")
                        # Save the state in the
                        stmt_doc.account_get = True
                        stmt_doc.selected_account_iban = account.iban
                        stmt_doc.from_data_state = from_data_encoded
                        stmt_doc.pause_dialog_state = dialog_data_encoded
                        stmt_doc.save(ignore_permissions=True)
                        return {
                            "ok": True,
                            "tan_required": False,
                            "message": "The account {0} has been selected.".format(account.iban)
                        }
        else:
            # Restore the previous pause session
            dialog_data_bytes = base64.b64decode(stmt_doc.pause_dialog_state)
            with f.resume_dialog(dialog_data_bytes):
                accounts = f.get_sepa_accounts()

                if isinstance(accounts, NeedTANResponse):
                    dialog_data = f.pause_dialog()
                    from_data = f.deconstruct(including_private=True)
                    tan_response_data = accounts.get_data()

                    # Convert to Base64 for easy storage
                    from_data_encoded = base64.b64encode(from_data).decode("ascii")
                    dialog_data_encoded = base64.b64encode(dialog_data).decode("ascii")
                    tan_data_encoded = base64.b64encode(tan_response_data).decode("ascii")

                    # Challenge & Decoupled
                    challenge = f.init_tan_response.challenge or "A TAN is Required"
                    decoupled = f.init_tan_response.decoupled

                    # Save the state in the
                    stmt_doc.from_data_state = from_data_encoded
                    stmt_doc.pause_dialog_state = dialog_data_encoded
                    stmt_doc.tan_data_response = tan_data_encoded
                    stmt_doc.challenge = challenge
                    stmt_doc.save(ignore_permissions=True)

                    # Decoupled means: the TAN is handled separately (outside your app).
                    # You don’t need to enter the TAN manually because it is confirmed in
                    # another place, like your bank’s mobile app.
                    if decoupled:
                        msg = "Decoupled:True Means Just confirmation will be done on your bank mobile app."
                    else:
                        msg = "Decoupled:False Means Bank sent a code on the mobile app that we have to enter here in ERPNext."

                    # Return the response
                    return {
                        "ok": False,  # required
                        "tan_required": True,  # required
                        "message": "A Tan is required",  # required
                        "challenge": challenge,
                        "decoupled": decoupled
                    }
                else:
                    account = accounts[0]

                    dialog_data = f.pause_dialog()
                    from_data = f.deconstruct(including_private=True)
                    # Convert to Base64 for easy storage
                    from_data_encoded = base64.b64encode(from_data).decode("ascii")
                    dialog_data_encoded = base64.b64encode(dialog_data).decode("ascii")
                    # Save the state in the
                    stmt_doc.account_get = True
                    stmt_doc.selected_account_iban = account.iban
                    stmt_doc.from_data_state = from_data_encoded
                    stmt_doc.pause_dialog_state = dialog_data_encoded
                    stmt_doc.save(ignore_permissions=True)
                    return {
                        "ok": True,
                        "tan_required": False,
                        "message": "The account {0} has been selected.".format(account.iban)
                    }
    except Exception as e:
        reset_connection(docname)
        frappe.throw(str(e))


@frappe.whitelist(methods=["POST"])
def fetch_transactions(docname=None):
    """
       Fetches bank transactions using FinTS for a given 'FinTS Statement Import' document.
       Args:
           docname (str): The name of the 'FinTS Statement Import' document.
       Returns:
           dict: A response indicating whether transactions were fetched or if a TAN is required.
       """
    try:
        if not docname:
            frappe.throw(_("Missing docname."))

        stmt_doc = frappe.get_doc("FinTS Statement Import", docname)
        if not stmt_doc.fints_account:
            frappe.throw(_("No FinTS Account set."))

        fints_doc = frappe.get_doc("FinTS Settings", stmt_doc.fints_account)

        if not (stmt_doc.mechanism_connected or stmt_doc.account_get
                or stmt_doc.selected_mechanism_id or stmt_doc.selected_account_iban):
            frappe.throw(
                _("To fetch transactions, both Step 1 and Step 2 are required. Please complete these steps before fetching transactions."))

        if not (stmt_doc.from_data_state or stmt_doc.pause_dialog_state):
            frappe.throw(
                _("To fetch transactions, ensure that the previous connection state and dialog state are saved. If not, first reset the connection and perform both Step 1 and Step 2 from the beginning."))

        # Transaction Mode:
        if stmt_doc.transaction_mode == "Fetch Last 30 Days":
            start_date = datetime.strptime(add_days(today(), -30), "%Y-%m-%d").date()
            end_date = datetime.strptime(today(), "%Y-%m-%d").date()
        elif stmt_doc.transaction_mode == "Fetch Last 120 Days":
            start_date = datetime.strptime(add_days(today(), -120), "%Y-%m-%d").date()
            end_date = datetime.strptime(today(), "%Y-%m-%d").date()
        elif stmt_doc.transaction_mode == "Custom":
            start_date = datetime.strptime(stmt_doc.start_date, "%Y-%m-%d").date()
            end_date = datetime.strptime(stmt_doc.end_date, "%Y-%m-%d").date()

        # Here it means both mechanism has been done and the FinTS state and Dialog pause state exists
        from_data_bytes = base64.b64decode(stmt_doc.from_data_state)
        dialog_data_bytes = base64.b64decode(stmt_doc.pause_dialog_state)
        f = FinTS3PinTanClient(
            bank_identifier=fints_doc.blz,
            user_id=fints_doc.username,
            pin=fints_doc.get_password("password"),
            server=fints_doc.endpoint_url,
            product_id=fints_doc.get_password("product_id"),
            from_data=from_data_bytes
        )

        with f.resume_dialog(dialog_data_bytes):
            accounts = f.get_sepa_accounts()

            if isinstance(accounts, NeedTANResponse):
                dialog_data = f.pause_dialog()
                from_data = f.deconstruct(including_private=True)
                tan_response_data = accounts.get_data()

                # Convert to Base64 for easy storage
                from_data_encoded = base64.b64encode(from_data).decode("ascii")
                dialog_data_encoded = base64.b64encode(dialog_data).decode("ascii")
                tan_data_encoded = base64.b64encode(tan_response_data).decode("ascii")

                # Challenge & Decoupled
                challenge = f.init_tan_response.challenge or "A TAN is Required"
                decoupled = f.init_tan_response.decoupled

                # Save the state in the
                stmt_doc.from_data_state = from_data_encoded
                stmt_doc.pause_dialog_state = dialog_data_encoded
                stmt_doc.tan_data_response = tan_data_encoded
                stmt_doc.challenge = challenge
                stmt_doc.save(ignore_permissions=True)

                # Decoupled means: the TAN is handled separately (outside your app).
                # You don’t need to enter the TAN manually because it is confirmed in
                # another place, like your bank’s mobile app.
                if decoupled:
                    msg = "Decoupled:True Means Just confirmation will be done on your bank mobile app."
                else:
                    msg = "Decoupled:False Means Bank sent a code on the mobile app that we have to enter here in ERPNext."

                # Return the response
                return {
                    "ok": False,  # required
                    "tan_required": True,  # required
                    "message": "A Tan is required",  # required
                    "challenge": challenge,
                    "decoupled": decoupled
                }
            else:
                account = accounts[0]

                # We will Fetch the transactions
                transactions = f.get_transactions(account, start_date, end_date)
                if isinstance(transactions, NeedTANResponse):
                    dialog_data = f.pause_dialog()
                    from_data = f.deconstruct(including_private=True)
                    tan_response_data = transactions.get_data()

                    # Convert to Base64 for easy storage
                    from_data_encoded = base64.b64encode(from_data).decode("ascii")
                    dialog_data_encoded = base64.b64encode(dialog_data).decode("ascii")
                    tan_data_encoded = base64.b64encode(tan_response_data).decode("ascii")

                    # Challenge & Decoupled
                    challenge = transactions.challenge or "A TAN is Required"
                    decoupled = transactions.decoupled

                    # Save the state in the
                    stmt_doc.from_data_state = from_data_encoded
                    stmt_doc.pause_dialog_state = dialog_data_encoded
                    stmt_doc.tan_data_response = tan_data_encoded
                    stmt_doc.challenge = challenge
                    stmt_doc.save(ignore_permissions=True)

                    # Decoupled means: the TAN is handled separately (outside your app).
                    # You don’t need to enter the TAN manually because it is confirmed in
                    # another place, like your bank’s mobile app.
                    if decoupled:
                        msg = "Decoupled:True Means Just confirmation will be done on your bank mobile app."
                    else:
                        msg = "Decoupled:False Means Bank sent a code on the mobile app that we have to enter here in ERPNext."

                    # Return the response
                    return {
                        "ok": False,  # required
                        "tan_required": True,  # required
                        "message": "A Tan is required",  # required
                        "challenge": challenge,
                        "decoupled": decoupled
                    }
                else:
                    return transactions_manage_response(f, fints_doc, stmt_doc, transactions, start_date, end_date)
    except Exception as e:
        reset_connection(docname)
        return {
            "ok": False,
            "message": "An error occurred while fetching transactions. The connection has been reset. Please try again."
        }


@frappe.whitelist(methods=["POST"])
def reset_connection(docname=None):
    """
        Resets the FinTS connection state for a given 'FinTS Statement Import' document.
        Args:
            docname (str): The name of the 'FinTS Statement Import' document.
        Returns:
            dict: Response confirming the reset operation.
    """
    if not docname:
        frappe.throw(_("Missing docname."))

    stmt_doc = frappe.get_doc("FinTS Statement Import", docname)
    if not stmt_doc.fints_account:
        frappe.throw(_("No FinTS Account set."))

    # Reset Connection:
    stmt_doc.mechanism_connected = False
    stmt_doc.selected_mechanism_id = ""

    stmt_doc.account_get = False
    stmt_doc.selected_account_iban = ""

    stmt_doc.pause_dialog_state = ""
    stmt_doc.from_data_state = ""
    stmt_doc.tan_data_response = ""
    stmt_doc.challenge = ""
    stmt_doc.save(ignore_permissions=True)
    frappe.db.commit()

    return {
        "ok": True,
        "message": _("The connection has been reset.")
    }


@frappe.whitelist(methods=["POST"])
def submit_tan_for_statement(docname=None, user_tan=None):
    """
        Handles the submission of the TAN (Transaction Authentication Number) for fetching bank statements via FinTS.
        Args:
            docname (str): Name of the 'FinTS Statement Import' document.
            user_tan (str): User-provided TAN for authentication.
        Returns:
            dict: Response containing transaction data or a success message.
    """
    try:
        if not docname:
            frappe.throw(_("The docname is required."))
        if not user_tan:
            frappe.throw(_("The User TAN is required."))

        if not frappe.db.exists("FinTS Statement Import", docname):
            frappe.throw(_("The docname has not been found."))

        stmt_doc = frappe.get_doc("FinTS Statement Import", docname)
        if not stmt_doc.fints_account or not frappe.db.exists("FinTS Settings", stmt_doc.fints_account):
            frappe.throw(_("No valid FinTS Account on the Statement Import doc."))

        fints_doc = frappe.get_doc("FinTS Settings", stmt_doc.fints_account)

        if not (stmt_doc.pause_dialog_state or stmt_doc.from_data_state or stmt_doc.tan_data_response):
            frappe.throw(
                _("The system has not found any TAN state, Pause Dialog state or FinTS State for the submission. Please reset the connection to establish a fresh connection."))

        from_data_bytes = base64.b64decode(stmt_doc.from_data_state)
        dialog_data_bytes = base64.b64decode(stmt_doc.pause_dialog_state)
        tan_data_bytes = base64.b64decode(stmt_doc.tan_data_response)

        f = FinTS3PinTanClient(
            bank_identifier=fints_doc.blz,
            user_id=fints_doc.username,
            pin=fints_doc.get_password("password"),
            server=fints_doc.endpoint_url,
            product_id=fints_doc.get_password("product_id"),
            from_data=from_data_bytes
        )

        # Recreate the NeedTANResponse object
        tan_request = NeedRetryResponse.from_data(tan_data_bytes)

        with f.resume_dialog(dialog_data_bytes):
            try:
                # Manually setting the missing attributes before calling send_tan()
                # HIKAZ => Kontoauszug Response - Account Statement Response
                # This is the response segment from the bank when requesting an account statement.
                f._touchdown_args = ['HIKAZ']
                f._touchdown_kwargs = {}
                f._touchdown_responses = []
                f._touchdown_counter = 1
                f._touchdown_dialog = f._get_dialog()
                f._touchdown_response_processor = lambda responses: mt940_to_array(
                    ''.join([seg.statement_booked.decode('iso-8859-1') for seg in responses]))

                # HKKAZ (Kontoauszug Request - Account Statement Request)
                # This is the request segment sent by the ERPNext to the bank.
                hkkaz = f._find_highest_supported_command(fints.segments.statement.HKKAZ5,
                                                          fints.segments.statement.HKKAZ6,
                                                          fints.segments.statement.HKKAZ7)
                f._touchdown_segment_factory = lambda touchdown: hkkaz(
                    account=tan_request.command_seg.account,
                    all_accounts=False,
                    date_start=tan_request.command_seg.date_start,
                    date_end=tan_request.command_seg.date_end,
                    touchdown_point=touchdown,
                )

                transactions = f.send_tan(tan_request, user_tan)
                return transactions_manage_response(f, fints_doc, stmt_doc, transactions,
                                                    start_date=tan_request.command_seg.date_start,
                                                    end_date=tan_request.command_seg.date_end, is_tan_response=True)
            except Exception as e:
                msg = "Oops! An error occurred while sending the TAN. The system has automatically reset the connection. Please start fresh from the beginning."
                frappe.throw(msg)
    except Exception as e:
        reset_connection(docname)
        frappe.throw(str(e))
