// Copyright (c) 2025, Ahmad Hussnain and contributors
// For license information, please see license.txt

frappe.ui.form.on("FinTS Statement Import", {
    refresh: function (frm) {
        if (!frm.is_new()) {
            // Fetch Transactions
            frm.add_custom_button(__("Fetch Transactions"), function () {
                frappe.call({
                    method: "fints_frappe.fints_frappe.doctype.fints_statement_import.fints_statement_import.fetch_transactions",
                    args: {
                        docname: frm.doc.name
                    },
                    freeze: true,
                    freeze_message: __("Fetching transactions..."),
                    callback: function (r) {
                        if (r.message.tan_required) {
                            show_tan_prompt_for_statement(frm, r.message);
                        } else {
                            frappe.msgprint({
                                message: r.message.message,
                                indicator: "blue"
                            });
                            frm.reload_doc();
                        }
                    }
                });
            });
            // Reset Connection
            frm.add_custom_button(__("Reset"), function () {
                frappe.call({
                    method: "fints_frappe.fints_frappe.doctype.fints_statement_import.fints_statement_import.reset_connection",
                    args: {docname: frm.doc.name},
                    freeze: true,
                    freeze_message: __("Reset"),
                    callback: function (r) {
                        if (!r.exc && r.message) {
                            frappe.msgprint(r.message.message);
                            frm.reload_doc();
                        }
                    }
                });
            });
        }
    },

    transaction_mode: function (frm) {
        frm.set_value("mechanism_connected", false);
        frm.set_value("selected_mechanism_id", "");
        frm.set_value("account_get", false);
        frm.set_value("selected_account_iban", "");

        frm.set_value("pause_dialog_state", "");
        frm.set_value("from_data_state", "");
        frm.set_value("tan_data_response", "");
        frm.set_value("challenge", "");
    },
    // Step 1: Set Mechanism
    btn_set_mechanism: function (frm) {
        if (frm.doc.mechanism_connected || frm.doc.selected_mechanism_id) {
            return frappe.msgprint(__("The mechanism is already connected. Please reset the previous connection to make it work."),);
        }
        // Otherwise Get and Select TAN Mechanism
        console.log("BTN_TRIGGER_GET_SET_TAN");
        frappe.call({
            method: "fints_frappe.fints_frappe.doctype.fints_statement_import.fints_statement_import.fetch_tan_mechanisms",
            args: {docname: frm.doc.name},
            freeze: true,
            freeze_message: __("Fetching TAN Mechanisms..."),
            callback: function (r) {
                if (!r.exc && r.message) {
                    if (r.message.ok) {
                        show_mechanisms_dialog(frm, r.message.mechanisms);
                    } else {
                        return frappe.msgprint(r.message);
                    }
                }
            }
        });
    },
    // Step 2: Get Account
    btn_get_accounts: function (frm) {
        if (!frm.doc.mechanism_connected || !frm.doc.selected_mechanism_id) {
            return frappe.msgprint(__("Step 1 is missing. The \"Get Account\" function only works if Step 1 is completed. Please first retrieve the mechanisms and assign them."),);
        }

        if (frm.doc.account_get || frm.doc.selected_account_iban) {
            return frappe.msgprint(__("The account is already connected. Please reset the previous connection to make it work."),);
        }

        // Otherwise Get and Select TAN Mechanism
        console.log("BTN_TRIGGER_GET_SET_ACCOUNT");
        frappe.call({
            method: "fints_frappe.fints_frappe.doctype.fints_statement_import.fints_statement_import.get_set_account_iban",
            args: {docname: frm.doc.name},
            freeze: true,
            freeze_message: __("Fetching & Setting Account..."),
            callback: function (r) {
                if (!r.exc && r.message) {
                    if (r.message.tan_required) {
                        show_tan_prompt_for_statement(frm, r.message);
                    } else {
                        frappe.msgprint(r.message.message);
                        frm.reload_doc();
                    }
                }
            }
        });
    }
});

// Once we have a mechanism list, let the user pick
function show_mechanisms_dialog(frm, mechs) {
    if (!mechs || mechs.length === 0) {
        frappe.msgprint(__("No TAN mechanisms found."));
        return;
    }

    let options = mechs.map(mech => ({label: `${mech.name} - (${mech.id})`, value: mech.id}));
    let default_mechanism = options[0].value; // Select first one by default

    let d = new frappe.ui.Dialog({
        title: __("Available TAN Mechanisms"),
        fields: [
            {
                default: default_mechanism,
                fieldname: "mechanism_select",
                fieldtype: "Select",
                label: __("Choose Mechanism"),
                options: options,
                reqd: 1
            }
        ],
        primary_action_label: __("Set Mechanism"),
        primary_action(values) {
            d.hide();
            let mech_id = values.mechanism_select;
            frappe.call({
                method: "fints_frappe.fints_frappe.doctype.fints_statement_import.fints_statement_import.select_tan_mechanism",
                args: {
                    docname: frm.doc.name,
                    mechanism_id: mech_id
                },
                freeze: true,
                freeze_message: __("Setting mechanism..."),
                callback: function (r) {
                    if (!r.exc && r.message) {
                        if (r.message.ok) {
                            frappe.msgprint(r.message.message);
                            frm.reload_doc();
                        } else {
                            frappe.msgprint(r.message);
                        }
                    }
                }
            });
        }
    });
    d.show();
}

// TAN FLOW FOR STATEMENT (Fetching transactions)
function show_tan_prompt_for_statement(frm, server_message) {
    let d = new frappe.ui.Dialog({
        title: __("TAN Required"),
        fields: [
            {
                fieldname: "challenge",
                fieldtype: "HTML",
                options: `<div>${server_message.challenge || __("TAN required.")}</div>`
            },
            {
                fieldname: "user_tan",
                fieldtype: "Data",
                label: __("Enter TAN"),
                depends_on: `eval: !${server_message.decoupled}`,
                reqd: !server_message.decoupled // False Means Bank sent a code on the mobile app that we have to enter here in ERPNext.
            }
        ],
        primary_action_label: __("Submit"),
        primary_action(values) {
            d.hide();
            frappe.call({
                method: "fints_frappe.fints_frappe.doctype.fints_statement_import.fints_statement_import.submit_tan_for_statement",
                args: {
                    docname: frm.doc.name,
                    user_tan: values.user_tan
                },
                freeze: true,
                freeze_message: __("Sending TAN..."),
                callback: function (r) {
                    if (!r.exc && r.message) {
                        if (r.message.ok) {
                            frappe.msgprint(r.message.message);
                            frm.reload_doc();
                        }
                    }
                }
            });
        }
    });
    d.show();
}
