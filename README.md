# Expense Manager

A mobile-friendly personal expense tracker with a Flask backend, `.xlsx` data store, and multi-account support. Features 7 color themes, Plotly charts, CSRF protection, and full CRUD for transactions.

---

## Features

- Multiple named accounts (savings & credit cards) with live balance tracking
- Income and expense tracking
- Sub-expense support — break down a transaction into individual items
- Category & sub-category management from the frontend
- Dashboard with spending charts, stat cards, and account balances
- 7 color themes (GitHub, Indigo, Nord, Emerald, Rose, Amber, Ocean) with dark/light modes
- Login authentication with bcrypt, rate limiting, and CSRF protection
- First-time setup wizard — creates login, accounts, and categories
- Mobile-responsive layout
- Custom date range filtering on the dashboard

---

## Pages

| URL | Purpose |
|-----|---------|
| `/` | Redirects to dashboard |
| `/setup` | First-time setup (create login & accounts) |
| `/login` | Sign in |
| `/dashboard` | Charts, stats & spending summary (home page) |
| `/manage` | Add transactions + transaction list with edit/delete |
| `/accounts` | Manage accounts |

---

## Quick start

```bash
pip install -r requirements.txt
python app.py
```

On first launch, open `http://localhost:5000` — the setup wizard will guide you through creating your login and adding accounts.

---

## Data & Backup

All user data lives in the `data/` folder:

| File | Contents |
|------|----------|
| `data/auth.json` | Login credentials (username + bcrypt hash) |
| `data/accounts.json` | Account definitions (names, types, balances/limits) |
| `data/categories.json` | Category and sub-category definitions |
| `data/expenses.xlsx` | All transaction data |

To migrate or restore: copy the entire `data/` folder to the new install. The app handles an empty or missing `data/` folder gracefully — it will show the setup wizard to start fresh.

The `.env` file holds only server config (host, port, secret key) and is auto-generated during setup if missing.

---

## Resetting credentials

The setup page is only available on first run. To change your login after setup:

1. Generate a new password hash:
   ```bash
   python -c "import bcrypt; print(bcrypt.hashpw(b'newpassword', bcrypt.gensalt()).decode())"
   ```

2. Edit `data/auth.json`:
   ```json
   {
     "username": "newusername",
     "password_hash": "<paste hash here>"
   }
   ```

3. Restart the app.

To start completely fresh, delete the `data/` folder and restart — the setup wizard will appear.

---

## Project structure

```
├── app.py              # Flask routes, auth, API endpoints
├── spreadsheet.py      # openpyxl read/write, balance computation
├── requirements.txt
├── .env                # Server config (not in git, auto-generated)
├── data/               # All user data (not in git)
│   ├── auth.json       # Login credentials
│   ├── accounts.json   # Account definitions
│   ├── categories.json # Category definitions
│   └── expenses.xlsx   # Transaction data
├── static/
│   ├── themes.css      # 7 color palettes (dark + light each)
│   └── theme.js        # Theme picker logic + localStorage
└── templates/
    ├── setup.html      # First-time setup wizard
    ├── login.html      # Login page
    ├── dashboard.html  # Plotly charts & stats (home page)
    ├── manage.html     # Add transactions + transaction list
    └── accounts.html   # Account management
```

---

## Notes

- Only parent transactions count toward balance calculations — sub-items don't double-count
- Transaction IDs are global integers across all months
- The `.xlsx` is the single source of truth — you can edit it manually in a spreadsheet app
- `categories.json` and `accounts.json` are updated live from the frontend — no restart needed
- Themes persist across pages via localStorage

---

## Built with LLM

This project was built using an LLM (Claude). If you want to modify or extend it, feed [`LLM.md`](LLM.md) to your LLM — it contains a detailed implementation guide covering the architecture, data models, API endpoints, theming system, security measures, and common modification patterns.
