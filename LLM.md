# LLM Implementation Guide — Expense Manager

This document is for LLM models working on this codebase. It provides a complete understanding of the architecture, data models, conventions, and implementation details.

---

## Architecture Overview

A single-user personal expense tracker built with Flask, using an `.xlsx` file as the primary data store and JSON files for configuration. No database. All frontend is server-rendered Jinja2 templates with client-side JavaScript for interactivity and Plotly for charts.

### Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python / Flask |
| Auth | flask-login + bcrypt |
| CSRF | flask-wtf (CSRFProtect) |
| Rate limiting | flask-limiter |
| Spreadsheet I/O | openpyxl |
| Charts | Plotly.js (CDN, client-side) |
| Config | python-dotenv (.env) |
| Frontend | Vanilla HTML/CSS/JS, Jinja2 templates |
| Theming | CSS custom properties, 7 palettes × 2 modes |
| Fonts | Google Fonts — Syne (display) + DM Mono (body) |

### File Structure

```
├── app.py              # Flask routes, auth, API endpoints, CSRF
├── spreadsheet.py      # openpyxl read/write, balance computation, formula sanitization
├── requirements.txt    # Python dependencies
├── .env                # Server config only (host, port, secret key — auto-generated)
├── data/               # All user data (back up this folder to migrate)
│   ├── auth.json       # Login credentials (username + bcrypt hash, chmod 600)
│   ├── accounts.json   # Account definitions
│   ├── categories.json # Category/sub-category definitions
│   └── expenses.xlsx   # Transaction data (one sheet per month)
├── static/
│   ├── themes.css      # All theme definitions + theme picker + mobile nav styles
│   └── theme.js        # Theme picker logic, palette/mode switching, localStorage
└── templates/
    ├── setup.html      # First-time setup wizard
    ├── login.html      # Login page
    ├── dashboard.html  # Plotly charts, stats, account balances (home page)
    ├── manage.html     # Combined add form + transaction list with edit/delete
    └── accounts.html   # Account management (CRUD)
```

---

## Data Model

### auth.json

Single object with login credentials. File permissions set to 600 on creation.

```json
{
  "username": "admin",
  "password_hash": "$2b$12$..."
}
```

Read on every request via `load_auth()` — no in-memory caching. Changes take effect immediately without restart.

### accounts.json

Array of account objects. Each account is either `savings` or `credit` type.

```json
[
  {"id": 1, "name": "HDFC Savings", "type": "savings", "balance": 50000},
  {"id": 2, "name": "ICICI Credit Card", "type": "credit", "limit": 200000}
]
```

- `id`: Auto-incrementing integer, unique per account
- `name`: Display name, must be unique. This exact string is stored in the spreadsheet's Account column
- `type`: `"savings"` or `"credit"`
- `balance` (savings only): Opening balance — the starting amount before any transactions
- `limit` (credit only): Credit limit

Balances are **not** stored per-transaction. They are computed on the fly by `compute_account_balances()` in `spreadsheet.py` which sums all parent transactions per account against the opening balance/limit.

### categories.json

Simple dict mapping category names to arrays of sub-category strings.

```json
{
  "Groceries": ["Dairy", "Bakery", "Vegetables"],
  "Dining": ["Restaurant", "Cafe", "Delivery"],
  "Salary": [],
  "Refund": []
}
```

Categories are shared across income and expense types — there is no separation.

### expenses.xlsx — Spreadsheet Structure

One sheet tab per month, named `"March 2026"`, `"April 2026"`, etc. (full month name + year via `strftime('%B %Y')`).

**Row 1**: Column headers (`TABLE_START = 1`).
**Row 2+**: Transaction data (`DATA_START = 2`).

**Active columns:**

| Column | Index | Field | Description |
|--------|-------|-------|-------------|
| A | 1 | Date | Python `date` object |
| B | 2 | Txn ID | Unique integer across ALL sheets |
| C | 3 | Description | Free text (sanitized against formula injection) |
| D | 4 | Category | Must match a key in categories.json |
| E | 5 | Sub-Category | Must match a value under the category, or empty |
| F | 6 | Account | Full account name from accounts.json (e.g. "HDFC Savings") |
| G | 7 | Amount | Always positive float, regardless of income/expense |
| H | 8 | Parent ID | NULL for parent transactions. Set to another Txn ID for sub-items |
| I | 9 | Type | `"Expense"`, `"Income"`, or `"Transfer"`. NULL treated as Expense |

### Transaction hierarchy

- A **parent transaction** has `parent_id = NULL`. It affects account balances.
- A **sub-item** has `parent_id` pointing to another transaction's ID. It does NOT affect balances.
- Sub-items are for breaking down a purchase (e.g., a grocery run into individual items).
- Sub-item amounts do not need to sum to the parent amount.
- Deleting a parent cascades to all its sub-items.
- Transaction IDs are global across all month sheets — scanned via `get_next_txn_id()`.

---

## Application Flow

### First-time setup (`/setup`)

1. App checks `is_setup_complete()` — returns `True` if `data/auth.json` exists with valid username and password_hash
2. If not set, ALL routes redirect to `/setup`
3. User creates username + password, adds accounts (name, type, opening balance/limit)
4. On submit: writes `data/auth.json` (bcrypt hash, chmod 600), `data/accounts.json`, default `data/categories.json`, and `.env` (server config) if missing
5. Setup page is permanently locked after completion — accessing it redirects to `/login`
6. To start fresh: delete the `data/` folder and restart

### Authentication

- Flask-Login with session-based auth
- Single user only — credentials stored in `data/auth.json`
- Password hashed with bcrypt
- Login rate-limited to 5 attempts/minute via flask-limiter
- CSRF protection via flask-wtf (CSRFProtect) — HTML forms include hidden `csrf_token`, fetch() calls send `X-CSRFToken` header from meta tag
- Session cookies: HttpOnly, SameSite=Lax. `SESSION_COOKIE_SECURE` controlled by `SECURE_COOKIES` env var (default false, set true behind HTTPS)
- Open redirect prevention — `next` parameter only allows relative paths
- All routes except `/login` and `/setup` require `@login_required`

### Navigation

- Logo ("Expense Manager") links to `/` which redirects to dashboard (home page)
- Nav links: `Manage`, `Accounts`, theme picker button, `Log Out`
- On mobile (< 600px), nav wraps: logo on its own row, links centered below

### Managing transactions (`/manage`)

The Manage page combines the add form and transaction list on a single page.

**Adding:**
1. User fills the collapsible "New Transaction" form at the top — type (Expense/Income/Transfer), date, description, account (dropdown), amount, category, sub-category
2. JS POSTs to `/api/transactions` with JSON payload + CSRF token header
3. `add_transaction()` in spreadsheet.py sanitizes fields, writes to the correct month sheet
4. Success toast, form resets (page does not reload)

**Sub-expenses:** Accessed via `/manage?parent=<id>` — shows parent badge, auto-expands form

**Editing:**
1. Click pencil icon on any transaction or sub-item in the list
2. JS fetches `GET /api/transactions/<id>` to populate edit modal (bottom sheet)
3. JS sends `PUT /api/transactions/<id>` with CSRF token
4. **Limitation**: Cannot change date to a different month. Returns error; user must delete and re-add.

**Deleting:**
1. Click X icon → confirmation modal (warns about cascade for parents)
2. JS sends `DELETE /api/transactions/<id>` with CSRF token
3. `delete_transaction()` deletes from bottom to top to keep row indices valid

Legacy routes `/add`, `/add/sub/<id>`, and `/expenses` redirect to `/manage` for backward compatibility.

### Balance computation

`compute_account_balances()` in spreadsheet.py:
1. Loads accounts from `data/accounts.json`
2. Reads ALL parent transactions from the spreadsheet
3. For each account:
   - **Savings**: `current_balance = opening_balance - (expenses + transfers) + income`
   - **Credit**: `accumulated = (expenses + transfers) - income`, `remaining = limit - accumulated`
4. Returns enriched account dicts

**Transfer handling**: Transfers reduce account balances (money moved out) just like expenses, but are excluded from spending summary charts. This avoids double-counting in analytics while keeping balances accurate.

This is called on every dashboard load and accounts page load. No caching.

---

## API Endpoints

All return JSON. All require `@login_required` and CSRF token for mutations (except `/login`, `/setup`).

### Transactions

| Method | URL | Purpose |
|--------|-----|---------|
| POST | `/api/transactions` | Create transaction. Body: `{date, description, category, sub_category, account, amount, parent_id, type}` |
| GET | `/api/transactions` | List all transactions |
| GET | `/api/transactions/<id>` | Get single transaction |
| PUT | `/api/transactions/<id>` | Update transaction. Body: same as POST |
| DELETE | `/api/transactions/<id>` | Delete transaction (cascades for parents) |

### Categories

| Method | URL | Purpose |
|--------|-----|---------|
| GET | `/api/categories` | List all categories |
| POST | `/api/categories` | Add category/sub-category. Body: `{category, sub_category}` |

### Accounts

| Method | URL | Purpose |
|--------|-----|---------|
| GET | `/api/accounts` | List all accounts |
| POST | `/api/accounts` | Create account. Body: `{name, type, balance/limit}` |
| PUT | `/api/accounts/<id>` | Update account. Body: `{name, balance/limit}` |
| DELETE | `/api/accounts/<id>` | Delete account (blocked if transactions exist) |
| GET | `/api/accounts/balances` | Get computed balances for all accounts |

### Other

| Method | URL | Purpose |
|--------|-----|---------|
| GET | `/api/summary` | Dashboard summary data for Plotly |

---

## Frontend Architecture

### Shared static files

Theme definitions and logic are centralized — not duplicated per template:

- **`static/themes.css`**: All 7 palettes (dark + light = 14 `[data-theme]` blocks), theme picker dropdown styles, theme toggle button styles, mobile nav responsive rules
- **`static/theme.js`**: `initThemePicker(onChangeCallback)` — creates the dropdown, handles palette/mode switching, persists to localStorage (`em-palette`, `em-mode`)

### Templates

All templates are standalone HTML files (no base template / inheritance). Each includes:
- `<link rel="stylesheet" href="/static/themes.css">` for theme definitions
- Page-specific CSS in a `<style>` block using CSS custom properties
- `<script src="/static/theme.js">` + `initThemePicker()` call
- CSRF meta tag: `<meta name="csrf-token" content="{{ csrf_token() }}">`
- `<html lang="en">` (no data-theme attribute — set by JS on load)

### Theming System

7 palettes, each with dark and light modes. The `data-theme` attribute on `<html>` uses the format `{palette}-{mode}`, e.g., `github-dark`, `nord-light`.

**Available palettes:** `github`, `indigo`, `nord`, `emerald`, `rose`, `amber`, `ocean`

**CSS variable contract** — every palette defines:
```
--bg, --surface, --surface2, --border, --accent, --accent-dim,
--text, --muted, --danger, --success, --savings, --cc
```

**Theme picker UI**: Dropdown appears from the sun/moon toggle button. Shows palette list with colored dots + dark/light mode toggle. On login/setup pages (no nav), the toggle uses `theme-toggle-fixed` class for fixed positioning.

**Adding a new theme**: Add two CSS blocks to `themes.css` (`[data-theme="name-dark"]` and `[data-theme="name-light"]`) and one entry to the `THEMES` array in `theme.js`. No template changes needed.

### UI Patterns

- **Nav bar**: Sticky top, logo left (links to dashboard), links right: Dashboard, Manage, Accounts, Log Out, theme picker. On mobile, wraps to two rows.
- **Forms**: Surface-colored cards, accent-colored focus rings, uppercase labels
- **Modals**: Bottom-sheet style (slides up from bottom), backdrop blur, close on overlay click
- **Toasts**: Fixed bottom-center, pill-shaped, auto-dismiss after 2.5s
- **Account indicators**: Colored dots — savings color for savings accounts, cc color for credit accounts
- **Amount display**: Expenses prefixed with `-`, income with `+` and success color

### Dashboard (`/dashboard` — home page)

Two-column chart grid on desktop (> 900px), single column on mobile. Container max-width 1400px.

**Stat cards** (6): Total Spent, Total Income, Net (green/red), Transactions count, Avg/Day, Top Category

**Account balance cards**: One card per account showing name, type, current balance or remaining credit

**Charts** (Plotly, all with zoom/pan disabled via `fixedrange: true` and `dragmode: false`):
1. **Daily Spending** (full width): Line chart with fill
2. **By Category**: Horizontal bar chart
3. **By Account**: Donut chart, colors by account type
4. **Month over Month**: Bar chart, current month highlighted

**Recent Transactions**: Last 8 transactions in the selected period

**Filters**: This Month, 3 Months, Year to Date, All Time, Custom (date range picker)

Chart colors are derived from CSS variables via `getThemeColors()` — works automatically with any palette. Theme is applied via `initTheme()` before the initial `renderAll()` call to avoid flash of unstyled charts.

---

## Security Measures

- **Bcrypt** password hashing
- **CSRF protection** via flask-wtf CSRFProtect — forms use hidden tokens, fetch() sends X-CSRFToken header
- **Rate limiting** on login (5/min)
- **Open redirect prevention** — `next` param rejects absolute URLs
- **Formula injection prevention** — `sanitize_cell()` prefixes `=`, `+`, `-`, `@` with `'` before writing to xlsx
- **auth.json permissions** — `os.chmod(AUTH_FILE, 0o600)` after creation
- **Session cookies** — HttpOnly, SameSite=Lax, Secure configurable via env var
- **Setup lockout** — `/setup` permanently redirects to `/login` after initial configuration

---

## Key Implementation Details

### Spreadsheet column backward compatibility

The `COLUMNS` dict maps logical names to physical column indices. The spreadsheet has 9 columns (A–I) with no gaps. Type lives at column I (index 9). Earlier versions had dead balance columns at I/J/K with Type at L — these were cleaned up and the layout consolidated.

### `parse_row()` bounds checking

Uses `row[idx] if idx < len(row) else None` to handle rows that are shorter than expected (old sheets may have fewer columns).

### `data_only=True` for reading

When reading the spreadsheet, `openpyxl` is loaded with `data_only=True` so that any Excel formulas return their cached computed values rather than formula strings. This matters because some users edit the spreadsheet manually in LibreOffice.

### Account rename propagation

When an account is renamed via the API (`PUT /api/accounts/<id>`), `rename_account_in_sheets()` scans every row in every sheet and updates column F to match the new name.

### Account deletion protection

Accounts cannot be deleted if any transaction references them. The API checks `get_all_transactions()` for matching account names before allowing deletion.

### First-time setup creates data/ files

The setup route creates `data/auth.json` (credentials), `data/accounts.json`, and `data/categories.json`. It also generates `.env` with a secret key if missing. Auth is read from `data/auth.json` on every request (no in-memory caching), so changes to the file take effect immediately.

### Cross-month date edits blocked

`update_transaction()` raises `ValueError` if the new date falls in a different month than the original. This avoids the complexity of moving rows between sheets. Users should delete and re-add instead.

### Formula sanitization

`sanitize_cell()` in `spreadsheet.py` prefixes any string starting with `=`, `+`, `-`, or `@` with a single quote `'`. Applied to description, category, sub-category, and account fields on both add and update paths.

---

## Dependencies

```
flask>=3.0.0
openpyxl>=3.1.0
flask-login>=0.6.0
bcrypt>=4.0.0
python-dotenv>=1.0.0
flask-limiter>=3.0.0
flask-wtf>=1.2.0
```

---

## Common Modification Patterns

### Adding a new page

1. Create route in `app.py` with `@login_required`
2. Create template in `templates/` — copy an existing one for structure
3. Include `<link rel="stylesheet" href="/static/themes.css">` in head
4. Include `<script src="/static/theme.js"></script>` and `<script>initThemePicker();</script>` before `</body>`
5. Add CSRF meta tag if the page makes fetch() calls
6. Add nav link in ALL templates' `.nav-links` div (dashboard.html, manage.html, accounts.html)

### Adding a new field to transactions

1. Add column to `COLUMNS` dict in `spreadsheet.py` (pick an unused column index)
2. Update `parse_row()` to read it (with bounds checking)
3. Update `add_transaction()` to write it (with `sanitize_cell()` for strings)
4. Update `update_transaction()` to write it
5. Update the add form and edit modal in `manage.html`
6. Update the JS form submission payloads

### Adding a new API endpoint

1. Add route in `app.py` under the appropriate section
2. Add `@login_required` decorator
3. Return JSON with `jsonify()`
4. For mutations, validate input and return 400 on error
5. CSRF is enforced automatically by flask-wtf on POST/PUT/DELETE — frontend must send X-CSRFToken header

### Adding a new theme

1. Add `[data-theme="name-dark"]` and `[data-theme="name-light"]` blocks to `static/themes.css` defining all CSS variables
2. Add `{ id: 'name', label: 'Display Name' }` to the `THEMES` array in `static/theme.js`
3. Add a hardcoded dot color for the picker: `.theme-picker-item[data-palette="name"] .theme-picker-dot { background: #hexcolor; }` in `themes.css`
4. No template changes needed

### Modifying the color palette

All theme colors are in `static/themes.css`. Dashboard chart colors are derived from CSS variables via `getThemeColors()` — no hardcoded chart colors to update.

---

## Known Limitations

- **Single user only** — no multi-user support, no user management
- **No concurrent access safety** — the xlsx file has no locking. Simultaneous writes can corrupt data
- **No pagination** — all transactions are loaded at once. Will slow down with thousands of entries
- **Dashboard recomputes on every load** — `compute_account_balances()` reads all transactions every time
- **No template inheritance** — each template is standalone, so nav/structure changes must be replicated across all 6 files. Theme CSS/JS is shared via static files.
- **Cross-month date edits blocked** — must delete and re-add to move a transaction between months
