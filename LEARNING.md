# Expense Manager — Learning Guide

A comprehensive breakdown of every technology, service, and concept used in this project. Written for someone who wants to understand not just *what* was used, but *why* and *how* it works.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Backend — Python & Flask](#backend--python--flask)
3. [Data Store — Excel via openpyxl](#data-store--excel-via-openpyxl)
4. [Frontend — HTML, CSS, JavaScript](#frontend--html-css-javascript)
5. [Charts — Plotly.js](#charts--plotlyjs)
6. [Authentication & Security](#authentication--security)
7. [Theming System](#theming-system)
8. [Investment Tracking — Yahoo Finance](#investment-tracking--yahoo-finance)
9. [Email-to-Expense Pipeline](#email-to-expense-pipeline)
10. [LLM Integration — llama.cpp](#llm-integration--llamacpp)
11. [n8n — Workflow Automation](#n8n--workflow-automation)
12. [PWA — Progressive Web App](#pwa--progressive-web-app)
13. [Docker & Deployment](#docker--deployment)
14. [CI/CD — GitHub Actions](#cicd--github-actions)
15. [Reverse Proxy — nginx](#reverse-proxy--nginx)
16. [Logging](#logging)
17. [How Data Flows](#how-data-flows)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                    User's Browser                     │
│  (HTML + CSS + JavaScript + Plotly.js)               │
└─────────────────────┬───────────────────────────────┘
                      │ HTTP requests
                      ▼
┌─────────────────────────────────────────────────────┐
│              Flask (Python backend)                    │
│  app.py — routes, auth, API endpoints                │
│  spreadsheet.py — read/write Excel                   │
│  email_parser.py — parse bank emails                 │
└──────┬──────────────┬───────────────┬───────────────┘
       │              │               │
       ▼              ▼               ▼
┌──────────┐  ┌──────────────┐  ┌──────────────┐
│ data/    │  │ Yahoo Finance│  │ LLM (local)  │
│ .xlsx    │  │ (prices API) │  │ llama.cpp    │
│ .json    │  └──────────────┘  └──────────────┘
└──────────┘
```

There is no traditional database. All data is stored in files — an Excel spreadsheet for transactions and JSON files for configuration. This makes the app completely portable: copy the `data/` folder and you have a full backup.

---

## Backend — Python & Flask

### What is Flask?

Flask is a lightweight Python web framework. It handles:
- **Routing** — mapping URLs to Python functions (e.g., `/dashboard` calls the `dashboard()` function)
- **Templates** — rendering HTML with dynamic data using Jinja2
- **Request handling** — parsing form submissions, JSON payloads, cookies

### How it's used here

**`app.py`** is the main file. It defines:
- **Page routes** (return HTML): `/dashboard`, `/manage`, `/analytics`, `/accounts`, `/settings`
- **API routes** (return JSON): `/api/transactions`, `/api/accounts`, `/api/drafts/ingest`
- **Authentication**: login, session management, rate limiting
- **Helper functions**: Yahoo Finance price fetching, FD interest calculation

Example of a route:
```python
@app.route('/dashboard')
@login_required
def dashboard():
    summary = get_monthly_summary()
    return render_template('dashboard.html', summary=summary)
```

This says: when someone visits `/dashboard`, check they're logged in, fetch the spending summary, and render the dashboard HTML template with that data.

### Key libraries

| Library | Purpose |
|---------|---------|
| `flask` | Web framework |
| `flask-login` | Session-based authentication (who is logged in) |
| `flask-wtf` | CSRF protection (prevents cross-site request forgery) |
| `flask-limiter` | Rate limiting (prevents brute-force login attacks) |
| `bcrypt` | Password hashing (one-way encryption for stored passwords) |
| `gunicorn` | Production WSGI server (replaces Flask's built-in dev server) |

### WSGI and gunicorn

Flask's built-in server (`python app.py`) is for development only — it handles one request at a time and has no security features. In production (Docker), the app runs under **gunicorn**, a WSGI server that:
- Handles multiple requests concurrently
- Manages worker processes
- Provides proper logging
- Is designed for production workloads

The Dockerfile runs: `gunicorn -b 0.0.0.0:5000 -w 1 --timeout 120 app:app`

This means: start gunicorn, bind to all interfaces on port 5000, use 1 worker process, with a 120-second timeout, loading the Flask app from `app.py`.

---

## Data Store — Excel via openpyxl

### Why Excel instead of a database?

- **Portable** — one file you can open in LibreOffice/Excel and edit by hand
- **No setup** — no database server to install, configure, or maintain
- **Backupable** — copy one file and you're done
- **Human-readable** — you can inspect and fix your data without any tools

### How it works

**`spreadsheet.py`** handles all Excel operations using the `openpyxl` library.

**Sheet structure**: one sheet per month (e.g., "March 2026", "February 2026"). Each sheet has:
- Row 1: column headers (Date, Txn ID, Description, Category, Sub-Category, Account, Amount, Parent ID, Type, Track, Units)
- Row 2 onward: transaction data

**Transaction IDs** are global integers — unique across all sheets. When adding a new transaction, the app scans all sheets to find the highest ID and adds 1.

**Parent/child relationships**: a "parent" transaction has no Parent ID. A "sub-item" has a Parent ID pointing to its parent's Txn ID. Sub-items don't count toward balance calculations.

### Reading vs writing

```python
# Reading — use data_only=True to get computed values (not formulas)
wb = openpyxl.load_workbook('expenses.xlsx', data_only=True)

# Writing — normal mode
wb = openpyxl.load_workbook('expenses.xlsx')
```

### Thread safety

Multiple requests could try to write to the Excel file at the same time. The app uses Python's `threading.Lock` to ensure only one write happens at a time. This is why gunicorn runs with `-w 1` (one worker).

---

## Frontend — HTML, CSS, JavaScript

### No framework

The frontend uses plain HTML, CSS, and vanilla JavaScript — no React, Vue, or Angular. Each page is a standalone Jinja2 template that includes shared CSS and JS files.

### Jinja2 templates

Flask uses Jinja2 for server-side rendering. The Python code passes data to the template:

```python
return render_template('dashboard.html', summary=summary, accounts=accounts)
```

Inside the template, you can use this data:

```html
<div>Total: ₹{{ summary.total_spent }}</div>
{% for account in accounts %}
  <div>{{ account.name }}: ₹{{ account.balance }}</div>
{% endfor %}
```

The server renders the final HTML before sending it to the browser. The browser never sees Jinja2 syntax.

### CSS custom properties (variables)

The theming system uses CSS variables so colors can change at runtime:

```css
[data-theme="github-dark"] {
  --bg: #0d1117;
  --text: #c9d1d9;
  --accent: #58a6ff;
}
```

Every element uses `var(--bg)` instead of hardcoded colors. Switching themes just changes the `data-theme` attribute, and all colors update instantly.

### No build step

There's no webpack, no npm, no compilation. The CSS and JS files are served as-is. This keeps the project simple — edit a file and reload the page.

---

## Charts — Plotly.js

### What is Plotly?

Plotly.js is a charting library loaded from a CDN. It renders interactive charts (zoom, hover tooltips, click events) entirely in the browser.

### How charts are rendered

1. Flask computes the data on the server (e.g., daily spending totals)
2. The data is passed to the template as JSON: `const rawSummary = {{ summary|tojson }};`
3. JavaScript processes the data and calls Plotly:

```javascript
Plotly.react('chart-daily', [{
  x: dates,
  y: amounts,
  type: 'scatter',
  mode: 'lines+markers',
  fill: 'tozeroy'
}], layoutConfig);
```

### Charts in the app

| Chart | Page | Type |
|-------|------|------|
| Daily Spending | Dashboard | Line with fill |
| Cumulative Average | Dashboard | Smoothed line |
| By Category | Dashboard | Horizontal bar |
| By Account | Dashboard | Donut/pie |
| Month over Month | Dashboard | Bar |
| Category Trends | Analytics | Multi-line |
| Day of Week | Analytics | Bar |
| Top Merchants | Analytics | Horizontal bar |
| Spending Velocity | Analytics | Dual line (current vs previous month) |

### Client-side filtering

When you click "This Month" or "3 Months", the page doesn't reload. JavaScript filters `rawSummary.transactions` by date range and re-renders all charts with `Plotly.react()`. This is instant because the data is already in the browser.

---

## Authentication & Security

### Password storage

Passwords are never stored in plain text. When you create a password during setup:

```python
hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
```

This creates a one-way hash. When you log in, the app hashes your input and compares:

```python
bcrypt.checkpw(input_password, stored_hash)
```

Even if someone reads `auth.json`, they can't reverse the hash to get your password.

### Session management (Flask-Login)

After a successful login, Flask-Login creates a session cookie. On every subsequent request, the cookie proves you're authenticated. The `@login_required` decorator on routes checks this automatically.

### CSRF protection (Flask-WTF)

Every form includes a hidden CSRF token:

```html
<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
```

When the form is submitted, Flask-WTF checks that the token matches the session. This prevents attackers from tricking your browser into submitting forms to the app.

### Rate limiting (Flask-Limiter)

The login page is limited to 5 attempts per minute:

```python
@limiter.limit("5 per minute")
def login():
```

This prevents brute-force password guessing.

### Formula injection prevention

When writing to the Excel file, any cell value starting with `=`, `+`, `-`, or `@` is prefixed with a single quote to prevent formula injection:

```python
def sanitize_cell(value):
    if isinstance(value, str) and value and value[0] in ('=', '+', '-', '@'):
        return "'" + value
    return value
```

---

## Theming System

### How it works

The app supports 7 color palettes, each with a dark and light variant = 14 themes total.

**`static/themes.css`** defines all palettes using CSS custom properties:

```css
[data-theme="github-dark"] {
  --bg: #0d1117;
  --surface: #161b22;
  --accent: #58a6ff;
  /* ... 30+ variables */
}
```

**`static/theme.js`** manages the theme picker:
1. On page load, reads the saved theme from `localStorage`
2. Sets `document.documentElement.dataset.theme` to apply it
3. The picker dropdown lets users switch — saves to `localStorage`

### No flash on load

A common problem with JS-based themes: the page loads with default styles, then flashes when JS applies the theme. The fix: a tiny inline `<script>` in the `<head>` of every template reads `localStorage` and sets the theme *before* the browser paints:

```html
<script>
  const t = localStorage.getItem('theme') || 'github-dark';
  document.documentElement.dataset.theme = t;
</script>
```

This runs synchronously before any rendering, so there's no flash.

---

## Investment Tracking — Yahoo Finance

### Price fetching

The app fetches live ETF/stock prices from Yahoo Finance's unofficial API:

```python
url = f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=1d&interval=1d'
```

This returns JSON with the current market price. The app caches prices for 5 minutes to avoid hitting the API on every page load.

### How it connects to accounts

Each investment account has a `ticker` field (e.g., `NIFTYBEES.NS`) and `units` field. The dashboard:
1. Fetches the current price via the API
2. Calculates: `current_value = units × price`
3. Calculates: `P&L = current_value - invested_amount`

### Auto-unit updates

When you add an Income transaction on an investment account with a `units` field, the app automatically:
- Adds the units to the account's total units
- Adds the amount to the account's invested balance

This keeps the account in sync without manual editing.

### Fixed deposits (no API)

FD values are calculated locally using the compound interest formula:

```
A = P × (1 + r/n)^(n×t)
```

Where P = principal, r = annual rate, n = compounding frequency, t = time in years.

---

## Email-to-Expense Pipeline

### The problem

Every time you spend money, your bank sends an email alert. Manually typing each expense into the app is tedious.

### The solution

The app can parse bank transaction emails using a local LLM (language model). Three modes:

#### 1. Paste mode (simplest)

Copy-paste the email text into a text box on the Manage page. The app sends it to the LLM, which extracts amount, merchant, date, and account. A "draft" transaction appears for you to accept or edit.

#### 2. Webhook mode

The app exposes `POST /api/drafts/ingest`. Any external tool can POST email HTML to this endpoint with an API key. The app parses it and creates a draft.

#### 3. n8n automation (hands-free)

n8n polls your email inbox, detects bank emails, and automatically POSTs them to the app's webhook. You just review and accept drafts.

### Deduplication

Each draft gets a "fingerprint" (hash of amount + date + merchant). If the same email is processed twice, the duplicate is silently skipped.

---

## LLM Integration — llama.cpp

### What is an LLM?

A Large Language Model (like ChatGPT, Llama, Mistral) that can understand and generate text. In this project, it reads a bank email and extracts structured data (amount, merchant, date, account).

### What is llama.cpp?

An open-source tool that runs LLM models locally on your own hardware. It exposes an API compatible with OpenAI's format:

```
POST http://your-server:8080/v1/chat/completions
```

### How the app uses it

1. **Strip HTML** from the bank email to get plain text
2. **Build a prompt** that tells the LLM what to extract and what format to return
3. **Send to the LLM** via HTTP POST
4. **Parse the JSON** response into a draft transaction

Example prompt:
```
You are a bank transaction parser. Extract: amount, merchant, date, account.
"account 7621" = "HDFC Savings"
"Credit Card ending 0230" = "HDFC Regalia Credit Card"
Return JSON only.
```

The LLM returns:
```json
{"amount": 450.0, "merchant": "Swiggy Food", "date": "2026-03-24", "account": "HDFC Savings"}
```

### Why local LLM?

- **Privacy** — your financial data never leaves your network
- **Free** — no API costs, no usage limits
- **Fast enough** — a 7-8B parameter model parses a bank email in 5-15 seconds

---

## n8n — Workflow Automation

### What is n8n?

n8n is an open-source workflow automation tool (similar to Zapier, but self-hosted). It connects services together using visual node-based workflows.

### The workflow

The app includes a downloadable n8n workflow template with 3 nodes:

1. **Email Trigger (IMAP)** — polls your email inbox every minute for new emails
2. **Filter Bank Emails** — checks if the sender matches your bank (e.g., "hdfcbank")
3. **HTTP Request** — POSTs the email HTML to the app's `/api/drafts/ingest` endpoint

### How IMAP works

IMAP (Internet Message Access Protocol) is the standard for reading email. n8n connects to your email provider's IMAP server:

| Provider | IMAP Host | Port |
|----------|-----------|------|
| Gmail | imap.gmail.com | 993 |
| Outlook | outlook.office365.com | 993 |
| Protonmail | Via Protonmail Bridge | 1143 |

n8n checks for new (unread) emails matching the filter, processes them, and marks them as read.

---

## PWA — Progressive Web App

### What is a PWA?

A Progressive Web App lets a website behave like a native app on your phone. You can "install" it to your home screen, and it gets its own app icon and splash screen.

### Components

**`static/manifest.json`** — tells the browser this is a PWA:
```json
{
  "name": "Expense Manager",
  "short_name": "Expenses",
  "start_url": "/",
  "display": "standalone",
  "theme_color": "#0d1117",
  "icons": [...]
}
```

**`static/sw.js`** — a Service Worker that caches static files (CSS, JS, images):
- **Network-first** for data/API calls (always get fresh data)
- **Cache-first** for static assets (load instantly, update in background)

This means the app loads fast even on slow connections, and basic viewing works offline.

---

## Docker & Deployment

### What is Docker?

Docker packages the app and all its dependencies into a "container" — a lightweight, isolated environment that runs the same everywhere. No "works on my machine" problems.

### Dockerfile

```dockerfile
FROM python:3.10-slim          # Base image with Python 3.10
WORKDIR /app                    # Set working directory
COPY requirements.txt .         # Copy dependency list
RUN pip install -r requirements.txt  # Install dependencies
COPY app.py spreadsheet.py email_parser.py ./  # Copy app code
COPY templates/ templates/      # Copy HTML templates
COPY static/ static/            # Copy CSS/JS/images
COPY scripts/ scripts/          # Copy utility scripts
USER appuser                    # Run as non-root user
CMD ["gunicorn", ...]           # Start the app
```

### docker-compose.yml

```yaml
services:
  expense-manager:
    image: ghcr.io/lexical-yoda/expensetracker:latest
    ports:
      - "5000:5000"
    volumes:
      - ./data:/app/data    # Mount data folder (persists across restarts)
    restart: unless-stopped
```

The `volumes` mapping is critical — it mounts your local `data/` folder into the container. Without it, data would be lost when the container restarts.

---

## CI/CD — GitHub Actions

### What is CI/CD?

Continuous Integration / Continuous Deployment — automatically build and deploy your app when you push code.

### The workflow (`.github/workflows/docker.yml`)

Every push to `main`:
1. GitHub Actions spins up a virtual machine
2. Checks out your code
3. Logs into GitHub Container Registry (ghcr.io)
4. Builds the Docker image
5. Pushes it as `ghcr.io/lexical-yoda/expensetracker:latest`

To deploy the new version:
```bash
docker compose pull && docker compose up -d
```

This pulls the latest image and recreates the container. Your data is safe because it's on the mounted volume.

---

## Reverse Proxy — nginx

### What is a reverse proxy?

A reverse proxy sits between the internet and your app. It:
- Terminates SSL (HTTPS encryption)
- Forwards requests to the right backend service
- Hides your internal network from the internet

### How it's used

nginx runs on a VPS (public server). When someone visits `expenses.yourdomain.com`:

```
Internet → nginx (VPS, port 443, HTTPS)
         → proxy_pass to internal-server:5000 (HTTP, via VPN)
         → Flask app responds
         → nginx sends response back to browser
```

The Flask app itself only speaks HTTP. nginx handles HTTPS with Let's Encrypt SSL certificates.

---

## Logging

### How logging works

The app uses Flask's built-in logger (`app.logger`). In Docker, gunicorn captures these logs and writes them to stdout, which Docker captures:

```bash
docker logs expense-manager          # View logs
docker logs expense-manager -f       # Follow live
docker logs expense-manager --tail 50  # Last 50 lines
```

### What's logged

- **Auth events**: login success/failure with IP address
- **Transaction operations**: create, update, delete with details
- **Draft pipeline**: email received → LLM parsed → draft created/duplicate/failed
- **Errors**: LLM failures, Yahoo Finance timeouts, file permission issues
- **Security**: invalid API key attempts, rate limiting

### Log levels

| Level | Meaning | Example |
|-------|---------|---------|
| INFO | Normal operation | "Transaction created: id=235" |
| WARNING | Something unexpected but not broken | "Yahoo Finance fetch failed" |
| ERROR | Something broke | "LLM failed to parse email" |

---

## How Data Flows

### Adding a transaction manually

```
1. User fills form on /manage
2. JavaScript sends POST /api/transactions with JSON body
3. Flask validates the data
4. spreadsheet.py opens expenses.xlsx
5. Finds or creates the month's sheet
6. Appends a new row with the transaction data
7. Saves the file
8. Returns JSON success response
9. JavaScript shows a toast notification and reloads the list
```

### Email-to-expense (automated)

```
1. Bank sends email to user's inbox
2. n8n detects new email via IMAP
3. n8n POSTs email HTML to /api/drafts/ingest with API key
4. Flask validates the API key
5. email_parser.py strips HTML to get plain text
6. Checks if it's a transaction email (not promotional)
7. Sends text to LLM with parsing prompt
8. LLM returns JSON: {amount, merchant, date, account}
9. App checks for duplicates (fingerprint matching)
10. Creates a draft in data/drafts.json
11. User opens /manage → sees amber "pending drafts" banner
12. User clicks accept → draft becomes a real transaction in expenses.xlsx
```

### Dashboard rendering

```
1. User visits /dashboard
2. Flask calls get_all_transactions() → reads all sheets in expenses.xlsx
3. Flask calls compute_account_balances() → calculates running balances
4. Flask calls get_monthly_summary() → aggregates data for charts
5. Renders dashboard.html with all data as JSON
6. Browser loads Plotly.js from CDN
7. JavaScript processes the JSON and renders charts
8. Investment prices fetched via AJAX → /api/investments/prices → Yahoo Finance
9. Net worth calculated client-side from all account data
```

---

## Glossary

| Term | Meaning |
|------|---------|
| **API** | Application Programming Interface — how the frontend talks to the backend via HTTP |
| **CORS** | Cross-Origin Resource Sharing — browser security that prevents unauthorized API access |
| **CSRF** | Cross-Site Request Forgery — an attack where a malicious site tricks your browser into making requests |
| **Docker** | Tool that packages apps into portable containers |
| **Flask** | Python web framework used for the backend |
| **gunicorn** | Production Python web server |
| **IMAP** | Protocol for reading email from a server |
| **Jinja2** | Template engine used by Flask to generate HTML |
| **JSON** | JavaScript Object Notation — data format used for API communication |
| **LLM** | Large Language Model — AI that understands and generates text |
| **n8n** | Open-source workflow automation tool |
| **nginx** | Web server used as a reverse proxy |
| **openpyxl** | Python library for reading/writing Excel files |
| **Plotly** | JavaScript charting library |
| **PWA** | Progressive Web App — makes websites installable like native apps |
| **Service Worker** | JavaScript that runs in the background for caching and offline support |
| **SMTP** | Protocol for sending email |
| **SSL/TLS** | Encryption for HTTPS connections |
| **WSGI** | Web Server Gateway Interface — standard for Python web servers |
| **XLSX** | Excel file format |
