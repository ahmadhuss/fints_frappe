# FinTS Connector for Frappe/ERPNext

**FinTS Connector** is a Frappe/ERPNext app that integrates with German banks via the **FinTS (HBCI)** protocol. This app enables retrieval of bank transactions for reconciliation within ERPNext.

## Features
- Connection with German banks via FinTS  
- Bank transaction retrieval for reconciliation  
- Session persistence to reduce repeated TAN entry

## Requirement

[ERPNext](https://github.com/frappe/erpnext) should be installed as an application within the [Frappe framework](https://github.com/frappe/frappe).

## Installation
```sh
# Clone and install the app in Frappe Bench
cd ~/frappe-bench
bench get-app https://github.com/your-repo/fints_frappe.git
bench --site your-site install-app fints_frappe
bench restart
```

## Tested
Banks that support TAN mechanisms and have been successfully tested.

![Tested Banks](https://raw.githubusercontent.com/ahmadhuss/fints_frappe/master/fints_frappe/tests/tested.gif)

## License
MIT (see [license.txt](./license.txt)
)
