# FinTS Connector for Frappe/ERPNext

**FinTS Connector** is a Frappe/ERPNext app that integrates with German banks via the **FinTS (HBCI)** protocol. This app enables retrieval of bank transactions for reconciliation, payment processing, and financial automation within ERPNext.

## Features
- Connection with German banks via FinTS  
- Bank transaction retrieval for reconciliation  
- Session persistence to reduce repeated TAN entry

## Installation
```sh
# Clone and install the app in Frappe Bench
cd ~/frappe-bench
bench get-app https://github.com/your-repo/fints_frappe.git
bench --site your-site install-app fints_frappe
bench restart
```

## License
MIT (see [license.txt](./license.txt)
)
