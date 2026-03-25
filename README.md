# Expense Manager

![Expense Manager Banner](screenshots/banner.png)

A self-hosted personal finance tracker with multi-account support, investment tracking, analytics, and automated bank email parsing via local LLM. No database — all data lives in an Excel file.

Built with Flask, Plotly, and openpyxl.

---

## Screenshots

### Dark Mode

| Dashboard | Analytics |
|:---------:|:---------:|
| ![Dashboard Dark](screenshots/dashboard-desktop-github-dark.png) | ![Analytics Dark](screenshots/analytics-desktop-github-dark.png) |

| Manage | Accounts |
|:------:|:--------:|
| ![Manage Dark](screenshots/manage-desktop-github-dark.png) | ![Accounts Dark](screenshots/accounts-desktop-github-dark.png) |

### Light Mode

| Dashboard | Analytics |
|:---------:|:---------:|
| ![Dashboard Light](screenshots/dashboard-desktop-github-light.png) | ![Analytics Light](screenshots/analytics-desktop-github-light.png) |

### Mobile

| Dashboard | Manage |
|:---------:|:------:|
| ![Dashboard Mobile](screenshots/dashboard-mobile-github-dark.png) | ![Manage Mobile](screenshots/manage-mobile-github-dark.png) |

### Login

| Dark | Light |
|:----:|:-----:|
| ![Login Dark](screenshots/login-github-dark.png) | ![Login Light](screenshots/login-github-light.png) |

---

## What It Does

Expense Manager is a single-user, self-hosted web app for tracking personal finances. You add expenses and income, organize them by accounts and categories, and see where your money goes through interactive charts and analytics. It stores everything in an Excel file — no database setup, no cloud services, fully portable.

### Core Features

| Feature | Description |
|---------|-------------|
| **Multi-account tracking** | Savings, credit cards, and investment accounts — each with their own balance logic |
| **Income, expense & transfers** | Track money in, money out, and money moved between accounts |
| **Sub-expenses** | Break down a grocery order or restaurant bill into individual items |
| **Dashboard** | Stat cards, daily spending chart, cumulative average, category breakdown, account split, month-over-month comparison |
| **Analytics** | Spending trends over time, day-of-week patterns, top merchants, spending velocity vs previous months |
| **CC billing cycle** | Current cycle spend, projected bill, previous cycle bill, cycle-over-cycle comparison |
| **Investments** | ETF/stock tracking with live Yahoo Finance prices, P&L, and auto-unit updates on purchase |
| **Fixed deposits** | Compound interest calculation with maturity countdown |
| **Net worth** | Savings + investments - CC debt, with configurable milestone goals and progress bar |

### Quality of Life

| Feature | Description |
|---------|-------------|
| **7 color themes** | GitHub, Indigo, Nord, Emerald, Rose, Amber, Ocean — each with dark and light modes |
| **Email-to-expense** | Paste bank emails or automate via n8n + local LLM to auto-parse transactions |
| **CSV export** | Download filtered transactions for tax filing or sharing |
| **Undo delete** | Restore accidentally deleted transactions (up to 20 per session) |
| **Track/untrack toggle** | Exclude specific transactions from dashboard stats without deleting them |
| **Advanced filters** | Filter by account, type, category, date range, or search text |
| **Pipeline history** | Full log of every email parsing attempt with status, retry for failures, and clear history |
| **PWA** | Install on your phone's home screen, works offline for viewing |
| **Mobile-first** | Responsive layout, no theme flash, pull-to-refresh |

### Security

| Feature | Description |
|---------|-------------|
| **Password auth** | bcrypt-hashed password, rate-limited login (5 attempts/min) |
| **CSRF protection** | All forms protected with Flask-WTF tokens |
| **Formula injection prevention** | Spreadsheet cells are sanitized against injection |
| **Secure cookies** | HTTPOnly, SameSite=Lax, Secure flag in production |
| **Setup wizard** | First-time setup creates credentials — no default passwords |

---

## Pages

| URL | Purpose |
|-----|---------|
| `/` | Redirects to dashboard |
| `/setup` | First-time setup wizard — create login, add accounts |
| `/login` | Sign in |
| `/dashboard` | Home page — charts, stats, account balances, investments, net worth, billing cycle |
| `/analytics` | Spending trends, category trends, day-of-week patterns, merchant analysis, spending velocity |
| `/manage` | Add/edit/delete transactions, sub-expenses, draft review, paste email parsing |
| `/accounts` | Manage accounts — savings, credit cards, ETFs, fixed deposits |
| `/settings` | LLM config, email automation, webhook, account mapping, custom prompt |

---

## Quick Start

### Docker (recommended)

```bash
docker compose up -d
```

### Manual

```bash
pip install -r requirements.txt
python app.py
```

Open `http://localhost:5000` — the setup wizard guides you through creating your login and adding accounts.

---

## Data & Backup

All user data lives in the `data/` folder:

| File | Contents |
|------|----------|
| `auth.json` | Login credentials (username + bcrypt hash + net worth goal) |
| `accounts.json` | Account definitions (savings, credit, investment with tickers/FD details) |
| `categories.json` | Category and sub-category definitions |
| `expenses.xlsx` | All transaction data (one sheet per month) |
| `drafts.json` | Pending email-parsed drafts (auto-created) |
| `email_config.json` | LLM + webhook config (auto-created via Settings) |

**To migrate or back up**: copy the entire `data/` folder. The app handles an empty or missing `data/` folder — it shows the setup wizard to start fresh.

---

## Investment Tracking

### Market / ETF Accounts
- Add an investment account with a **Yahoo Finance ticker** (e.g., `NIFTYBEES.NS`, `GOLDBEES.NS`)
- Enter units held and total invested amount
- Dashboard fetches live prices and shows current value, P&L (amount + percentage)
- When buying new units: add an Income transaction on the investment account with the **units** field — the app auto-updates the account's units and invested amount

### Fixed Deposits
- Add an investment account with subtype **Fixed Deposit**
- Enter principal, interest rate, start date, maturity date, and compounding frequency
- Dashboard calculates current value with compound interest and shows days remaining to maturity

### Net Worth
The dashboard shows: sum of all savings balances + investment current values - credit card outstanding. A configurable milestone goal with progress bar auto-advances as you hit targets.

---

## Credit Card Billing Cycle

Set a `billing_date` on any credit card account (e.g., 14 for 14th of each month). The dashboard then shows:

- **Current cycle spend** — CC expenses since billing date
- **Projected bill** — extrapolated from daily average
- **Previous cycle bill** — last cycle's total
- **Cycle-over-cycle** — spending up or down vs previous cycle (with percentage)
- **Days remaining** — countdown to cycle end
- **Total CC outstanding** — all-time accumulated CC balance

---

## Email-to-Expense Pipeline

Parse bank transaction alert emails into expense entries using a local LLM. Supports manual paste and automated ingestion via n8n.

### How It Works

```
Bank sends email → Your inbox → n8n detects it → POSTs to app webhook
→ App strips HTML → sends to local LLM → LLM extracts amount/merchant/date
→ Draft transaction created → you review on Manage page → accept/edit/reject
```

Every step is logged in the **Pipeline History** (Settings page) — you can see which emails were processed, which failed, and retry failures with one click.

### Three Ways to Use

| Method | Setup | Best for |
|--------|-------|----------|
| **Paste mode** | None — paste email text on Manage page | Quick one-off entry |
| **n8n automation** | Install n8n, import workflow template, configure IMAP | Hands-free automation |
| **Webhook API** | `POST /api/drafts/ingest` with API key | Custom integrations |

### Setup

1. **Settings** → enable LLM, enter your LLM endpoint URL (e.g., Ollama, llama.cpp)
2. Add **account mappings** (e.g., `"account 7621"` → `"HDFC Savings"`)
3. (Optional) Customize the parsing prompt — the Settings page has an in-app guide for generating prompts for any bank
4. For automation: install [n8n](https://n8n.io), import the workflow template from Settings, configure your email credentials
5. After first login, a **setup banner** on the Dashboard guides you to configure this

### Pipeline History & Retry

- **Settings → Pipeline History** shows all parsing attempts
- Filter by status: success, failed, skipped, duplicate
- **Retry** failed entries with one click — useful if the LLM was temporarily down
- History is capped at 500 entries and auto-cleaned

### Handling Rapid Transactions

Multiple bank emails arriving in quick succession (e.g., during travel) are handled via:
- **n8n queues** emails and processes them sequentially
- **Deduplication** prevents the same transaction from being created twice (fingerprint matching on amount + date + merchant)
- **Rate limiting** on the webhook endpoint (30/min) prevents abuse
- All attempts are logged in Pipeline History regardless of outcome

### Requirements

- A local LLM with an OpenAI-compatible API (`/v1/chat/completions`) — e.g., llama.cpp, Ollama, LM Studio
- (For automation) n8n instance with access to your email inbox via IMAP

---

## Password Reset

```bash
# Interactive
python scripts/reset_password.py

# Non-interactive
python scripts/reset_password.py -p mynewpassword

# Docker
sudo docker exec -it expense-manager python scripts/reset_password.py
```

To start completely fresh, delete the `data/` folder and restart — the setup wizard will appear.

---

## Project Structure

```
├── app.py                # Flask routes, auth, API endpoints, investment prices
├── spreadsheet.py        # openpyxl read/write, balance computation
├── email_parser.py       # HTML email stripping + LLM parsing
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .github/workflows/
│   └── docker.yml        # Auto-build + push Docker image to ghcr.io
├── data/                 # All user data (not in git)
│   ├── auth.json
│   ├── accounts.json
│   ├── categories.json
│   ├── expenses.xlsx
│   ├── drafts.json       # Auto-created
│   └── email_config.json # Auto-created via Settings
├── scripts/
│   ├── reset_password.py
│   └── take_screenshots.py
├── static/
│   ├── themes.css        # 7 palettes × 2 modes
│   ├── theme.js          # Theme picker + localStorage
│   ├── interactions.js   # Counters, toasts, pull-to-refresh, auto-refresh
│   ├── sw.js             # Service worker for PWA
│   ├── n8n-email-workflow.json
│   ├── favicon.svg
│   ├── icon-192.png
│   └── icon-512.png
└── templates/
    ├── setup.html
    ├── login.html
    ├── dashboard.html
    ├── analytics.html
    ├── manage.html
    ├── accounts.html
    └── settings.html
```

---

## Notes

- Only parent transactions count toward balances — sub-items don't double-count
- "Untracked" transactions affect balances but are excluded from charts and stats
- Transaction IDs are global integers across all months
- The `.xlsx` is the single source of truth — editable in LibreOffice/Excel
- CC bill payments: record as a Transfer from savings + Income on the CC account
- Investment prices from Yahoo Finance are cached for 5 minutes (~15min market delay)
- Categories, accounts, and settings are updated live — no restart needed
- All operations are logged via `app.logger` — visible in `docker logs expense-manager`

---

## Built With LLM

This project was built using an LLM (Claude). To modify or extend it, feed [`LLM.md`](LLM.md) to your LLM — it contains a detailed implementation guide covering architecture, data models, API endpoints, theming, security, and common modification patterns.

For a comprehensive breakdown of every technology and service used, see [`LEARNING.md`](LEARNING.md).
