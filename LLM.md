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
| Testing | pytest — `plan.py` only (pure functions, no Flask app under test) |

### File Structure

```
├── app.py              # Flask routes, auth, API endpoints, CSRF, draft/email/settings/plan APIs
├── spreadsheet.py      # openpyxl read/write, balance computation, formula sanitization
├── email_parser.py     # HTML email stripping + LLM parsing (no Flask deps, testable standalone)
├── plan.py             # Plan-vs-actual target/actual calc (pure functions, no Flask deps, unit-tested)
├── requirements.txt    # Python dependencies
├── Dockerfile          # Python 3.10-slim, gunicorn server — must COPY every top-level .py module used by app.py
├── docker-compose.yml  # Single-service compose for deployment
├── .env                # Server config only (host, port, secret key — auto-generated)
├── .github/
│   └── workflows/
│       └── docker.yml  # GitHub Actions — auto-build and push image to ghcr.io on push to main
├── data/               # All user data (back up this folder to migrate)
│   ├── auth.json       # Login credentials (username + bcrypt hash + net worth goal)
│   ├── accounts.json   # Account definitions
│   ├── categories.json # Category/sub-category definitions
│   ├── expenses.xlsx   # Transaction data (one sheet per month)
│   ├── drafts.json     # Pending email-parsed draft transactions (auto-created)
│   ├── email_config.json  # LLM + webhook config (auto-created via Settings page)
│   ├── pipeline_log.json  # Email parsing attempt history (auto-created)
│   ├── plan.json           # Investment plan config (auto-created via Settings → Investment Plan)
│   └── networth_history.json  # Monthly net worth snapshots, keyed "YYYY-MM" (auto-created)
├── scripts/
│   ├── take_screenshots.py  # Selenium-based screenshot generator for README
│   └── reset_password.py   # CLI password reset (interactive or -p flag)
├── tests/
│   └── test_plan.py    # pytest — plan.py target/actual math, no Flask/app dependency
├── screenshots/             # Auto-generated screenshots (dark/light, desktop/mobile)
├── static/
│   ├── themes.css      # All theme definitions + theme picker + mobile nav styles
│   ├── theme.js        # Theme picker logic, palette/mode switching, localStorage
│   ├── interactions.js # Animated counters, toasts, pull-to-refresh, auto-refresh, relative timestamps, help-icon tooltips, PWA SW registration
│   ├── sw.js           # Service worker (network-first for data, cache-first for static)
│   ├── n8n-email-workflow.json  # Importable n8n workflow template for email automation
│   ├── favicon.svg     # App favicon (SVG)
│   ├── icon-192.png    # PWA icon (192x192)
│   └── icon-512.png    # PWA icon (512x512)
└── templates/
    ├── setup.html      # First-time setup wizard
    ├── login.html      # Login page
    ├── dashboard.html  # Plotly charts, stats, account balances, investments (home page)
    ├── analytics.html  # Spending trends, category trends, merchant analysis, velocity
    ├── manage.html     # Add form + transaction list + draft review banner + paste email modal
    ├── accounts.html   # Account management (CRUD)
    ├── plan.html       # Plan-vs-actual: progress bars, cumulative table, trajectory chart
    └── settings.html   # LLM config, n8n setup guide, webhook, account mapping, custom prompt, investment plan
```

---

## Data Model

### auth.json

Single object with login credentials. File permissions set to 600 on creation.

```json
{
  "username": "admin",
  "password_hash": "$2b$12$...",
  "nw_goal_increment": 500000
}
```

Read on every request via `load_auth()` — no in-memory caching. Changes take effect immediately without restart.

### accounts.json

Array of account objects. Three types: `savings`, `credit`, and `investment`.

```json
[
  {"id": 1, "name": "HDFC Savings", "type": "savings", "balance": 50000},
  {"id": 2, "name": "ICICI Credit Card", "type": "credit", "limit": 200000},
  {"id": 3, "name": "NIFTYBEES", "type": "investment", "subtype": "market", "balance": 62823, "ticker": "NIFTYBEES.NS", "units": 220},
  {"id": 4, "name": "HDFC FD", "type": "investment", "subtype": "fd", "balance": 100000, "interest_rate": 7.5, "start_date": "2025-09-15", "maturity_date": "2026-09-15", "compounding": "quarterly"}
]
```

- `id`: Auto-incrementing integer, unique per account
- `name`: Display name, must be unique. This exact string is stored in the spreadsheet's Account column
- `type`: `"savings"`, `"credit"`, or `"investment"`
- `balance` (savings): Opening balance — the starting amount before any transactions
- `balance` (investment): Total invested amount (cost basis / principal)
- `limit` (credit only): Credit limit
- `opening_balance` (credit only, optional): Amount already owed on the card before the first tracked transaction. Added to accumulated spend in `compute_account_balances()`. Defaults to 0 if absent. Use when tracking starts mid-cycle on a card that already carried a balance.
- `subtype` (investment only): `"market"` (ETF/stock with live pricing) or `"fd"` (fixed deposit)
- `ticker` (market only): Yahoo Finance symbol (e.g., `NIFTYBEES.NS`)
- `units` (market only): Number of units/shares held. Auto-updated when transactions with units are added.
- `interest_rate` (FD only): Annual interest rate percentage
- `start_date` / `maturity_date` (FD only): `YYYY-MM-DD` strings
- `compounding` (FD only): `"monthly"`, `"quarterly"`, `"half-yearly"`, or `"yearly"`
- `exclude_from_networth_goal` (any type, optional, default `false`): Excludes this account's balance from the net-worth **milestone bar** calculation specifically (`dashboard.html` `renderNetWorth()`) — the account still counts normally in the headline net worth figure, `/accounts`, CSV export, and everywhere else. Used e.g. for a dedicated "guilt-free spending" savings account that isn't part of a savings goal.

Balances are computed on the fly by `compute_account_balances()` in `spreadsheet.py` which sums all parent transactions per account against the opening balance/limit. Investment accounts return their cost basis; live values are fetched separately via `/api/investments/prices`.

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
| J | 10 | Track | `"Yes"` or `"No"`. Controls dashboard visibility. NULL treated as Yes |
| K | 11 | Units | Float. Number of units bought/sold for investment account transactions. NULL for non-investment |
| L | 12 | Plan Bucket | String. Plan-vs-actual bucket id (e.g. `"equity"`) — Income or Transfer transactions only, optional, NULL if untagged |
| M | 13 | Transfer To | String. Destination account name — Transfer transactions only, optional. When set, the destination account is credited directly (see "One-step transfers" below); when absent, behaves like the old two-transaction convention (source debited only) |

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
- Nav links: `Dashboard`, `Analytics`, `Manage`, `Accounts`, `Plan`, `Settings`, theme picker button, `Log Out`
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
4. Cross-month date edits are supported: if the new date falls in a different month, `update_transaction()` deletes the row from the old sheet and re-creates it (same Txn ID) in the correct month sheet, preserving `parent_id`.

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
   - **Savings**: `current_balance = opening_balance - (expenses + transfers) + income + transfer_credits_received`
   - **Credit**: `accumulated = opening_balance + (expenses + transfers) - income - transfer_credits_received`, `remaining = limit - accumulated` (`opening_balance` defaults to 0)
4. Returns enriched account dicts

**One-step transfers**: A `Transfer` transaction with `transfer_to_account` set credits that destination account directly — `transfer_credit_by_account` in `compute_account_balances()` sums these separately from `income_by_account`, so an internal transfer never inflates the dashboard's "Total Income" stat. The source account is still debited exactly as before (`spend_by_account`). This lets a CC bill payment or a savings→savings move happen in one transaction instead of two. **Backward compatible**: a `Transfer` with no `transfer_to_account` (every transfer logged before this feature existed) behaves exactly as it always did — source debited, nothing auto-credited, since the user was expected to log a matching `Income` on the destination separately. Transfers (with or without a destination) remain excluded from spending summary charts (`get_monthly_summary()`), same as before.

**Restrictions enforced client-side, not server-side**: the "To Account" dropdown (manage.html) only lists `savings`/`credit` accounts — investment accounts stay on the existing Income+units purchase flow, since a transfer isn't "buying units." The backend only rejects `transfer_to_account == account` (self-transfer); it doesn't enforce the savings/credit-only restriction, so a direct API call could bypass it. This wasn't tightened further since it just means whoever calls the API directly could pick an odd destination — no balance-math corruption results either way (the credit formula treats any account type the same generically).

**Track toggle**: Each transaction has a `track` field (Yes/No). Untracked transactions still affect account balances but are excluded from dashboard charts, stat cards, and spending summaries. Useful for investments, SIP payments, or other planned outflows the user doesn't want in their spending analytics. Toggle is available per-transaction in the Manage page via a dot button (◉). Defaults to tracked (Yes) for new transactions.

**Investment transactions**: When a transaction targets an investment account and includes units:
- `Income` on investment account: auto-adds units and invested amount to the account
- `Expense` on investment account: auto-subtracts units and invested amount
- The units field appears in the add/edit form only when an investment account is selected
- `_update_investment_account()` in spreadsheet.py handles the auto-update
- Editing a transaction also keeps the account consistent: `update_transaction()` reverses the old units/amount and reapplies the new ones (so changing amount/units/type on an investment txn no longer drifts `accounts.json`)

**Investment price fetching**: `fetch_yahoo_price(ticker)` in app.py calls Yahoo Finance's chart API. Returns the `regularMarketPrice` or `None` on failure. Called by `/api/investments/prices` which returns current value, P&L, and percentage for each market investment account.

**FD value calculation**: `calculate_fd_value()` in app.py uses compound interest formula: `A = P(1 + r/n)^(nt)`. Returns current value (based on elapsed time), maturity value, interest earned, days remaining, and matured status.

This is called on every dashboard load and accounts page load. Yahoo Finance prices are cached for 5 minutes; FD calculations are computed fresh each time (no external API call).

---

## API Endpoints

All return JSON. All require `@login_required` and CSRF token for mutations (except `/login`, `/setup`).

### Transactions

| Method | URL | Purpose |
|--------|-----|---------|
| POST | `/api/transactions` | Create transaction. Body: `{date, description, category, sub_category, account, amount, parent_id, type, units, plan_bucket, transfer_to_account}`. `transfer_to_account` only applies when `type: "Transfer"`; rejected with 400 if equal to `account` |
| GET | `/api/transactions` | List all transactions |
| GET | `/api/transactions/<id>` | Get single transaction |
| PUT | `/api/transactions/<id>` | Update transaction. Body: same as POST |
| DELETE | `/api/transactions/<id>` | Delete transaction (cascades for parents) |
| PATCH | `/api/transactions/<id>/track` | Toggle track status. Body: `{track: true/false}` |

### Export

| Method | URL | Purpose |
|--------|-----|---------|
| GET | `/api/export/csv` | Download transactions as CSV. Query params: `account`, `type`, `category`, `from`, `to`, `parents_only`. Columns: Date, ID, Description, Category, Sub-Category, Account, Transfer To, Amount, Type, Track, Units, Parent ID |

### Undo

| Method | URL | Purpose |
|--------|-----|---------|
| POST | `/api/undo/delete` | Save transaction to undo stack before deletion. Body: `{txn_id}` |
| POST | `/api/undo` | Undo last delete — re-creates the transaction and its sub-items |
| GET | `/api/undo/status` | Check how many undo actions are available |

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
| DELETE | `/api/accounts/<id>` | Delete account (blocked if transactions reference it) |
| GET | `/api/accounts/balances` | Get computed balances for all accounts |

### Investments

| Method | URL | Purpose |
|--------|-----|---------|
| GET | `/api/investments/prices` | Live prices for market investments + FD calculations. Returns current value, P&L, units, and FD maturity info |

### Plan (Plan vs. Actual)

| Method | URL | Purpose |
|--------|-----|---------|
| GET | `/api/settings/plan` | Get plan config (or the zeroed-out default if none saved yet) |
| PUT | `/api/settings/plan` | Save plan config. Body: `{plan_start_date, monthly_base, phase1_target_total, base_income, base_expense, income_growth_pct, expense_growth_pct, extra_routing, no_penalty_mode, buckets[], phase1_buckets}`. Each bucket's `ratio` is derived server-side as `amount / monthly_base` — don't send it. `phase1_buckets` is optional in the payload; if omitted, the existing on-disk value is preserved (not wiped) |
| GET | `/plan` | The Plan vs. Actual page itself (not a JSON API, but listed here since it's the feature's main entry point) |

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
- **`static/interactions.js`**: Shared UI utilities loaded on all authenticated pages — animated stat counters (`animateCounter`, `animateStat`), toast notifications (`showToast`), pull-to-refresh (mobile), auto-refresh (60s polling), relative timestamps (`timeAgo`), help-icon tooltips (self-initializing, see below), PWA service worker registration

### Templates

All templates are standalone HTML files (no base template / inheritance). Each includes:
- `<script src="/static/interactions.js">` in `<head>` for shared utilities
- `<link rel="stylesheet" href="/static/themes.css">` for theme definitions
- Inline theme initialization: `<script>document.documentElement.setAttribute('data-theme', ...)</script>` to prevent flash
- Page-specific CSS in a `<style>` block using CSS custom properties
- `<script src="/static/theme.js">` + `initThemePicker()` call before `</body>`
- CSRF meta tag: `<meta name="csrf-token" content="{{ csrf_token() }}">`

### Theming System

7 palettes, each with dark and light modes. The `data-theme` attribute on `<html>` uses the format `{palette}-{mode}`, e.g., `github-dark`, `nord-light`.

**Available palettes:** `github`, `indigo`, `nord`, `emerald`, `rose`, `amber`, `ocean`

**CSS variable contract** — every palette defines:
```
--bg, --surface, --surface2, --border, --accent, --accent-dim,
--text, --muted, --danger, --success, --savings, --cc,
--bucket-blue, --bucket-amber, --bucket-green, --bucket-pink, --bucket-gray, --bucket-teal, --bucket-violet
```

**Theme picker UI**: Dropdown appears from the sun/moon toggle button. Shows palette list with colored dots + dark/light mode toggle. On login/setup pages (no nav), the toggle uses `theme-toggle-fixed` class for fixed positioning.

**Adding a new theme**: Add two CSS blocks to `themes.css` (`[data-theme="name-dark"]` and `[data-theme="name-light"]`) and one entry to the `THEMES` array in `theme.js`. No template changes needed.

**Categorical color set (`--bucket-*`)**: Used for two things — Plan page bucket swatches (`plan.html`'s `bucketColor()`) and chart categorical series (Dashboard/Analytics `CAT_COLORS`, assigned by a stable name-hash — `stableColor(name, colors)` — never by sort rank, so a category/account/merchant keeps the same color across re-renders instead of repainting when the ranking shifts). All 6 hues (`blue/amber/green/pink/teal/violet`; `gray` is a separate neutral, not part of the categorical rotation) use the **same hex values in both light and dark mode** — validated against every theme's own surface color in both modes (OKLCH lightness band, chroma floor, CVD/colorblind separation, contrast). The dark blocks previously used brighter Tailwind-400-style tints (e.g. `#60a5fa`) that looked fine individually but failed the dark-mode lightness band as a set — don't "brighten for dark mode" if you touch these; the mid-tone values are already correct for both. `--success`/`--danger`/`--cc` are reserved status colors and must never be reused as generic categorical/series colors (a red spending category would misread as "over budget"; see `plan.html`'s trajectory chart below for a case where this was fixed).

### UI Patterns

- **Nav bar**: Sticky top, logo left (links to dashboard), links right: Dashboard, Analytics, Manage, Accounts, Plan, Settings, Log Out, theme picker. On mobile, wraps to two rows.
- **Forms**: Surface-colored cards, accent-colored focus rings, uppercase labels
- **Modals**: Bottom-sheet style (slides up from bottom), backdrop blur, close on overlay click
- **Toasts**: Fixed bottom-center, pill-shaped, auto-dismiss after 2.5s
- **Account indicators**: Colored dots — savings color for savings accounts, cc color for credit accounts
- **Amount display**: Expenses prefixed with `-`, income with `+` and success color
- **Help tooltips**: `<span class="help-icon" tabindex="0" role="button" aria-label="Help" data-help="...">?</span>` — self-initializing via a single delegated click listener in `interactions.js` (no per-page init call). Click toggles a `.help-popover` anchored above the icon; click elsewhere or Escape closes it. **Must call `e.preventDefault()` on the click** when the icon is inside a `<label for="...">` (common, since most usages sit right after a field label) — otherwise the browser's native label-click-forwarding fires a second synthetic click on the associated form control, which bubbles back to the same delegated listener and immediately closes the popover that was just opened. This is already handled in the shared handler; don't reimplement help icons with a per-element listener that skips it.
- **Getting-started banner** (`dashboard.html`): same dismiss-and-remember pattern as `email-setup-banner` — `localStorage` flag + conditional server-side render. Shown when `has_activity` is `False` (i.e. `get_all_transactions()` is empty), gone permanently once dismissed or once any transaction exists.
- **Icon action buttons** (`.action-btn` — edit/delete/track in `manage.html`, edit/delete in `accounts.html`): base look and size live in `themes.css`, not duplicated per template (was 28×28px in both files independently; now one shared rule at 32px, 38px on mobile via the existing `@media (max-width: 600px)` block). Always pair with an `aria-label` describing the specific target (e.g. `aria-label="Delete {{ txn.description }}"`), not just a bare `title` — icon-only buttons have nothing else for a screen reader to announce.
- **Focus-visible**: custom buttons/pills (`.action-btn`, `.filter-action-btn`, `.filter-pill`, `.filter-select`, `.theme-toggle`) get an explicit `outline: 2px solid var(--accent)` on `:focus-visible` in `themes.css`, since their `:hover`-only styling left keyboard users with either an inconsistent browser default or nothing. Hidden-radio toggles (`input[type=radio]` sized to `opacity:0; width:0` behind a `<label>` — the Type picker pattern in `manage.html`) get the same treatment via `input[type="radio"]:focus-visible + label` — without it, tabbing through them showed zero visual focus indicator at all.
- **Chart table fallback** (`renderChartTable(afterElId, tableId, headers, rows)` — defined locally in `dashboard.html`, `analytics.html`, `plan.html`): every Plotly chart gets a native `<details><summary>View as table</summary>...</details>` injected right after its `chart-wrap` div, built from the same data passed to `Plotly.react`. Plotly's SVG/canvas output has no screen-reader-usable content otherwise. The function is idempotent — call it again on every re-render (filter change, auto-refresh, theme switch) and it updates the existing table in place instead of stacking duplicates; call `removeChartTable(tableId)` (analytics.html only) when a chart's empty-state branch runs instead. All cell text goes through a local `escHTML`/`esc` helper, not raw interpolation.

### Dashboard (`/dashboard` — home page)

Two-column chart grid on desktop (> 900px), single column on mobile. Container max-width 1400px.

**Net worth hero** (`.net-worth-hero`, right after the date-range row, before the stat grid): net worth, next milestone, progress bar, and category breakdown. Deliberately styled heavier than a `.stat-card` (accent border, 2.2rem value vs. 1.2rem) and positioned first — it used to sit below account balances and the CC billing cycle section, styled almost identically to every other stat card, so it never read as the page's headline number.

**Stat cards** (6): Total Spent, Total Income, Net (green/red), Transactions count, Avg/Day, Spent Today

**Account balance cards**: One card per account showing name, type, current balance or remaining credit. Investment accounts use `--bucket-violet` for their dot/badge (not `--accent` — in the GitHub, Nord, and Ocean palettes `--savings` equals `--accent`, so Investment and Savings accounts used to render as the exact same color).

**Charts** (Plotly, all with zoom/pan disabled via `fixedrange: true` and `dragmode: false`; each has a "View as table" fallback below it — see Chart table fallback in UI Patterns):
1. **Daily Spending** (full width): Line chart with fill
2. **Cumulative Average Spending/Day** (full width): no table fallback — same underlying daily data as #1, deliberately not duplicated
3. **By Category**: Horizontal bar chart, colored by category name (stable hash, not sort rank)
4. **By Account**: Donut chart, colored per account name (not just account type — two accounts of the same type used to share one indistinguishable legend swatch)
5. **Month over Month**: Bar chart, current month highlighted

**Recent Transactions**: Last 8 transactions in the selected period

**Filters**: This Month, 3 Months, Year to Date, All Time, Custom (date range picker)

Chart colors are derived from CSS variables via `getThemeColors()` — works automatically with any palette. Theme is applied via `initTheme()` before the initial `renderAll()` call to avoid flash of unstyled charts.

**Clickable chart**: Clicking a point on the Daily Spending chart navigates to `/manage?date=YYYY-MM-DD`, which auto-filters the transaction list to that date.

### Analytics (`/analytics`)

Period filter pills: This Month, 3 Months (default), 6 Months, Year to Date, All Time, Custom (date range picker). "This Month" was added to match Dashboard's filter vocabulary — the two pages previously offered different option sets for what's conceptually the same control. All computation is client-side from `rawSummary` data.

**Period Summary cards** (4): This Week, This Month, Last Month, Daily Avg — each with percentage comparison to previous period (green = less spending, red = more).

**Charts** (Plotly, each with a "View as table" fallback — see UI Patterns):
1. **Category Trends** (full width, title says "always, ignores filter above"): Line chart, top 5 spending categories over the trailing 6 real calendar months — deliberately independent of the filter pills (built from `allTxns`, not the filter-scoped `txns`), so a narrow Custom range doesn't silently intersect with this window and show near-empty months
2. **Day of Week Spending**: Bar chart, average spending per weekday (Mon–Sun), highest day highlighted; shows a `.chart-empty` message when there's no spending in the selected period (previously just rendered 7 flat zero bars with no explanation)
3. **Top 10 Merchants**: Horizontal bar chart grouped by transaction description, colored by merchant name (stable hash)
4. **Spending Velocity** (full width): Cumulative spend this month vs last month — shows if spending is faster or slower

Period Summary and Spending Velocity always use absolute current/last month data regardless of filter selection. Day of Week and Merchant Analysis respond to the selected filter range; Category Trends does not (see above).

---

## Security Measures

- **Bcrypt** password hashing
- **CSRF protection** via flask-wtf CSRFProtect — forms use hidden tokens, fetch() sends X-CSRFToken header
- **Rate limiting** on login and setup (5/min each)
- **Open redirect prevention** — `next` param only allows relative paths starting with `/`, rejects `//`
- **XSS prevention** — user content escaped via `esc()` helper in JS templates, Jinja2 auto-escaping in server templates
- **Formula injection prevention** — `sanitize_cell()` prefixes `=`, `+`, `-`, `@`, `|`, `\t` with `'` before writing to xlsx
- **Thread-safe file access** — `_xlsx_lock` and `_accounts_lock` in spreadsheet.py protect concurrent read-modify-write operations
- **Generic error messages** — API endpoints return "Operation failed" instead of internal error details
- **Investment price caching** — Yahoo Finance responses cached for 5 minutes to prevent abuse
- **Transaction read caching** — `get_all_transactions()` caches parsed results, invalidated on xlsx write (file mtime check)
- **auth.json permissions** — `os.chmod(AUTH_FILE, 0o600)` after creation
- **Session cookies** — HttpOnly, SameSite=Lax, Secure configurable via env var
- **Setup lockout** — `/setup` permanently redirects to `/login` after initial configuration

---

## Key Implementation Details

### Spreadsheet column backward compatibility

The `COLUMNS` dict maps logical names to physical column indices. The spreadsheet has 13 columns (A–M) with no gaps. Type at column I (index 9), Track at column J (index 10), Units at column K (index 11), Plan Bucket at column L (index 12), Transfer To at column M (index 13). Each of these four optional columns follows the same precedent: append at the end of `COLUMNS` (never insert), so older sheets that predate the column still parse fine via `parse_row()`'s bounds check.

### `parse_row()` bounds checking

Uses `row[idx] if idx < len(row) else None` to handle rows that are shorter than expected (old sheets may have fewer columns).

### Jinja2 `{% set %}` doesn't survive a `{% for %}` — use `namespace()`

A value set with `{% set x = ... %}` **inside** a `{% for %}` loop body does not persist once that loop ends, even if the loop is nested inside another loop that needs the value afterward. This bit `accounts.html`'s account list for a long time: it did a per-account inner loop to find the matching entry in `balances`, `{% set bal = b %}` inside that inner loop — then referenced `bal` *after* the inner loop ended, where it was silently always `None`. Effect: the Accounts page showed each savings account's static opening `balance` field instead of its live `current_balance`, and every credit card showed a hardcoded "Remaining: ₹0.00" regardless of actual usage — for as long as that code existed, until a live browser check (not just an HTTP 200) caught it. Fixed with Jinja's `namespace()` object, which *does* support cross-scope mutation:
```jinja
{% set ns = namespace(bal=None) %}
{% for b in balances %}
  {% if b.id == acct.id %}{% set ns.bal = b %}{% endif %}
{% endfor %}
{% set bal = ns.bal %}
```
`manage.html` already did this correctly (`ns.cur_month`/`ns.cur_day` for tracking state across the transaction list loop) — that's the pattern to copy. Rule of thumb: if a `{% set %}` needs to be read outside the `{% for %}` (or outside a nested inner loop) that set it, it needs `namespace()`, not a bare `{% set %}`. A rendered-page check (screenshot or scraped text) is the only thing that actually catches this class of bug — the page returns 200 either way.

### `data_only=True` for reading

When reading the spreadsheet, `openpyxl` is loaded with `data_only=True` so that any Excel formulas return their cached computed values rather than formula strings. This matters because some users edit the spreadsheet manually in LibreOffice.

### Account rename propagation

When an account is renamed via the API (`PUT /api/accounts/<id>`), `rename_account_in_sheets()` scans every row in every sheet and updates column F to match the new name.

### Account deletion protection

Accounts cannot be deleted if any transaction references them. The API checks `get_all_transactions()` for matching account names before allowing deletion.

### First-time setup creates data/ files

The setup route creates `data/auth.json` (credentials), `data/accounts.json`, and `data/categories.json`. It also generates `.env` with a secret key if missing. Auth is read from `data/auth.json` on every request (no in-memory caching), so changes to the file take effect immediately.

### Cross-month date edits supported

`update_transaction()` handles a new date in a different month: it deletes the row from the original sheet and re-creates it (same Txn ID, preserving `parent_id`, `units`, and `track`) in the correct month sheet. The move is **atomic** — the delete and re-add happen in one workbook with a single save, so a failure can't lose the row. Same-month edits are updated in place. Omitted `units`/`track` fields are carried over from the existing row rather than cleared.

### Formula sanitization

`sanitize_cell()` in `spreadsheet.py` prefixes any string starting with `=`, `+`, `-`, or `@` with a single quote `'`. Applied to description, category, sub-category, and account fields on both add and update paths.

### Undo system

In-memory stack (`UNDO_STACK` in app.py, max 20 entries). Before deleting a transaction, the frontend calls `POST /api/undo/delete` which snapshots the transaction and its children. `POST /api/undo` pops the last entry and re-creates the transaction via `add_transaction()`. The undo stack resets on app restart (intentional — no persistent undo history).

### CSV export

`GET /api/export/csv` generates a CSV from `get_all_transactions()` with optional query param filters (account, type, category, from/to dates, parents_only). Returns a `text/csv` response with `Content-Disposition` header for download.

### PWA

- `manifest.json` served from Flask route (not a static file) — allows dynamic configuration
- Service worker (`/sw.js`) uses network-first strategy: tries live fetch, falls back to cache for static assets
- Service worker registered in `static/interactions.js` (loaded on every authenticated page)
- PWA icons at `static/icon-192.png` and `static/icon-512.png`

### Advanced filters (Manage page)

Client-side filtering using `data-` attributes on transaction cards (`data-account`, `data-type`, `data-cat`, `data-date`). The `applyFilters()` function reads all filter inputs and hides/shows cards and day/month labels accordingly. Filters also apply to CSV export via query params.

### Mobile input font-size / iOS Safari zoom

Every form's `input`/`select`/`textarea` is sized at 14–15px on desktop for visual density (set per-template — there's no shared form-field component). iOS Safari auto-zooms the whole page on focusing any text input rendered below 16px, which made every form in the app zoom in on tap on iPhone. Fixed once, globally, in `themes.css`'s existing `@media (max-width: 600px)` block: `input, select, textarea { font-size: 16px !important; }`. The `!important` is load-bearing — each template's own `<style>` block comes after `themes.css` in `<head>`, so without it the page's own 14–15px rule would win the cascade at equal specificity. Desktop sizing is untouched (media query only applies ≤600px).

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
gunicorn>=21.2.0
pytest>=8.0.0   # dev only — tests/test_plan.py
```

---

## Common Modification Patterns

### Adding a new page

1. Create route in `app.py` with `@login_required`
2. Create template in `templates/` — copy an existing one for structure
3. Include `<link rel="stylesheet" href="/static/themes.css">` in head
4. Include `<script src="/static/theme.js"></script>` and `<script>initThemePicker();</script>` before `</body>`
5. Add CSRF meta tag if the page makes fetch() calls
6. Add nav link in ALL templates' `.nav-links` div (dashboard.html, analytics.html, manage.html, accounts.html, plan.html, settings.html)
7. **Don't forget `Dockerfile`** — the `COPY app.py spreadsheet.py email_parser.py ...` line lists every top-level `.py` module explicitly; a new module (like `plan.py`) that's imported by `app.py` but missing from that line will crash the container with `ModuleNotFoundError` on boot even though it works fine locally (bit the plan-vs-actual feature on first deploy)

### Adding a new field to transactions

1. Add column to `COLUMNS` dict in `spreadsheet.py` (pick an unused column index, append at the end — never insert, so old sheets keep parsing via the bounds check in `parse_row()`/`val()`)
2. Update `parse_row()` to read it (with bounds checking)
3. Update `add_transaction()` to write it (with `sanitize_cell()` for strings) — only write the cell if the value is truthy/not-None, matching the `units`/`plan_bucket` precedent
4. Update `update_transaction()`/`_update_transaction_inner()` to write it — capture the **old** value before overwrite, resolve the **new** value with carry-over-if-omitted logic, and **always write the cell (not just when truthy)** so the field can actually be cleared via an edit — `plan_bucket` originally got this wrong (guarded the write with `if new_value:`, so clearing it silently failed to persist) before being fixed to unconditionally write `sanitize_cell(new_value) if new_value else None`
5. Update the add form and edit modal in `manage.html`
6. Update the JS form submission payloads
7. **Also update the transaction list rendering** (both the server-rendered `txn-card` in `manage.html` and the JS-inserted card built after a successful add) and `/api/export/csv`'s header row + row values — `transfer_to_account` shipped with steps 1-6 done but was invisible in both the list and the CSV export until a follow-up pass added it; easy to forget since neither one errors, they just silently omit the new field

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

## Email-to-Expense Pipeline

### Architecture

```
Bank email → User inbox → n8n (or paste) → App webhook/paste API
    → email_parser.strip_email_html() → extracts transaction text
    → email_parser.parse_with_llm() → sends to local LLM → gets JSON
    → apply_currency_conversion() → USD amounts converted to INR via Yahoo FX rate
    → Draft stored in data/drafts.json (status: pending)
    → User reviews on Manage page → accept/edit/reject
    → Accepted → add_transaction() → real transaction in xlsx
```

**Currency conversion**: `apply_currency_conversion()` in app.py converts non-INR (USD) parsed amounts to INR using a Yahoo Finance FX rate for the transaction date, storing `original_amount`/`original_currency`/`fx_rate` on the draft. If the rate fetch fails, the draft is **rejected** (logged as `failed`) rather than storing a raw foreign amount as INR.

### Key files

- **`email_parser.py`** — two pure functions, no Flask dependencies:
  - `strip_email_html(html)` → extracts "Dear Customer..." text, returns None for promotional emails
  - `parse_with_llm(text, llm_url, prompt)` → calls LLM's `/v1/chat/completions`, validates response, returns dict
  - `build_default_prompt(account_mapping)` → generates system prompt with dynamic account mapping and current year
  - `PROMPT_SETUP_GUIDE` — meta-prompt for users to create custom bank prompts using any LLM

- **Draft endpoints in `app.py`**:
  - `POST /api/drafts/ingest` — CSRF-exempt, API-key auth via `X-API-Key` header. Used by n8n/webhook.
  - `POST /api/drafts/paste` — login + CSRF auth. Used by paste modal on Manage page.
  - `GET /api/drafts` — list pending drafts
  - `POST /api/drafts/<id>/accept` — creates real transaction via `add_transaction()`. Validates the draft's `account` and `category` exist first (returns 400 otherwise) so drafts can't create transactions on phantom accounts. Passes through `units` for investment drafts.
  - `POST /api/drafts/<id>/reject` — marks draft as rejected
  - `PUT /api/drafts/<id>` — edit draft fields before accepting
  - `POST /api/drafts/accept-all` — bulk accept all pending

- **Settings endpoints in `app.py`**:
  - `GET/PUT /api/settings/email` — read/update email config
  - `POST /api/settings/email/regenerate-key` — regenerate API key
  - `POST /api/settings/email/test-llm` — test LLM connection (server-side, returns model names)
  - `POST /api/settings/email/test-webhook` — full pipeline test (HTML strip → LLM → draft creation)
  - `POST /api/settings/email/test-parse` — test LLM parsing with custom prompt
  - `PUT /api/settings/nw-goal` — update net worth goal increment

### Draft storage (`data/drafts.json`)

```json
[
  {
    "id": 1,
    "amount": 450.00,
    "merchant": "Swiggy",
    "date": "2026-03-25",
    "account": "HDFC Regalia Credit Card",
    "category": "Dining",
    "sub_category": "",
    "type": "Expense",
    "status": "pending",
    "raw_email_text": "Dear Customer, Rs.450...",
    "created_at": "2026-03-25T14:30:00",
    "fingerprint": "450.00|2026-03-25|hdfc regalia credit card|swiggy"
  }
]
```

- `fingerprint` = `amount|date|account_lowercase|merchant_lowercase` — used for deduplication. Amount is formatted to 2 decimals and the account is included so the same amount+date+merchant on two different cards is not wrongly deduped.
- `status`: `pending` / `accepted` / `rejected`
- Accepted/rejected drafts older than 30 days are auto-pruned on save
- Thread-safe via `_drafts_lock` in app.py

### Email config (`data/email_config.json`)

```json
{
  "enabled": true,
  "llm_url": "http://192.168.1.31:8080",
  "system_prompt": "",
  "account_mapping": {
    "account 7621": "HDFC Savings",
    "Credit Card ending 0230": "HDFC Regalia Credit Card"
  },
  "api_key": "auto-generated-token",
  "app_url": "http://localhost:5000"
}
```

- `system_prompt`: empty = use default prompt from `build_default_prompt()`
- `api_key`: validates `X-API-Key` header on the ingest endpoint
- Config is created/managed via the Settings page UI

### n8n integration

The app ships with an importable n8n workflow template at `static/n8n-email-workflow.json`. Three nodes:
1. **Email Trigger (IMAP)** — polls inbox for new emails
2. **Filter** — matches bank sender address
3. **HTTP Request** — POSTs email HTML to `/api/drafts/ingest` with API key

Users configure their email credentials in n8n, not in the app. The app only needs the LLM URL and API key.

### Pipeline history

Every email parsing attempt is logged in `data/pipeline_log.json`:

```json
{
  "id": 1,
  "timestamp": "2026-03-25T10:30:00",
  "status": "success",         // success, failed, skipped, duplicate
  "source": "webhook",         // webhook, paste, retry
  "email_preview": "Dear Customer, Rs.450...",
  "email_full": "Dear Customer, ... (untruncated, up to 5000 chars)",
  "parsed": {"amount": 450, "merchant": "Swiggy", "date": "2026-03-24", "account": "HDFC Savings"},
  "error": null,
  "draft_id": 5
}
```

`email_preview` is capped at 200 chars for display; `email_full` stores up to 5000 chars so retry re-parses the complete email, not a truncated preview.

**Endpoints:**
- `GET /api/pipeline/history?status=failed&limit=50` — filtered, newest first
- `POST /api/pipeline/retry/<log_id>` — retry a failed entry using the stored full email text (re-sends to LLM, creates draft on success)
- `POST /api/pipeline/clear` — clear all history

**UI:** Settings page has a "Pipeline History" section with filter buttons, status badges, retry buttons, and clear history. Uses `.section`/`.section-title`/`.btn-outline`/`.btn-danger` like every other Settings section — it used to be a bare `.card`/`<h2>`/`.btn-small`, none of which are defined anywhere in `settings.html`'s stylesheet, so it silently rendered unstyled (no background/border, browser-default buttons) next to the other 6 properly-styled sections. Status badges already carry the status text (`SUCCESS`/`FAILED`/etc.), not color alone.

**Settings page navigation:** `settings.html` stacks 7 config sections (LLM, n8n, Account Mapping, Webhook, Custom Prompt, Investment Plan, Pipeline History) in one scroll. A sticky `.section-nav` jump-bar sits above them (`<a href="#sec-llm">`, etc.) — each `.section` has a matching `id="sec-*"` and `scroll-margin-top` so a jump doesn't land the heading under the sticky bar. Adding an 8th section: add both the `<a href="#sec-x">` link and the target `id="sec-x"`.

**Limits:** capped at 500 entries (oldest pruned automatically).

### Security notes

- The ingest endpoint is CSRF-exempt (called by external tools) but requires a valid API key
- The API key is generated with `secrets.token_urlsafe(32)` and stored in `email_config.json`
- LLM calls happen server-side via `urllib.request` — the LLM URL can be a private/local address
- Email text is truncated to 500 chars before storing in drafts (prevents large payloads)
- Draft content is escaped in the frontend via `textContent` assignment (XSS-safe)

---

## Credit Card Billing Cycle

Credit card accounts can have a `billing_date` field (day of month, e.g., 14). When set, the dashboard shows:

- **Current Cycle Spend** — CC expenses from billing date to today
- **Cycle Period** — e.g., "14/3 — 13/4"
- **Days Remaining** — countdown to cycle end
- **Projected Bill** — daily average × total cycle days
- **Total CC Outstanding** — all-time accumulated CC balance
- **Previous Cycle Bill** — last cycle's total CC spend
- **Previous Period** — date range of prior cycle
- **Cycle-over-Cycle** — comparison showing spending up/down vs previous cycle (with % change)

All calculated client-side in `renderBillingCycle()` in `dashboard.html`. Only shown when at least one CC account has `billing_date` configured.

---

## Net Worth Goal

Users set a net worth milestone increment during setup (default ₹5,00,000). The dashboard shows:
- Current net worth (savings + investments - CC debt)
- Next milestone (auto-advances when crossed)
- Progress bar with percentage
- Remaining amount

Stored in `data/auth.json` as `nw_goal_increment`. Updated via `PUT /api/settings/nw-goal`. Milestone computed client-side in `computeMilestone()`.

---

## Plan vs. Actual Tracking

A read-only progress view for a manual, opt-in monthly allocation plan (e.g. "₹60k to equity, ₹15k to gold, ₹15k to FD top-up, ₹30k to a fun fund, ₹10k buffer"). Deliberately has **no** auto-debit, scheduling, or penalty mechanics — see `no_penalty_mode` below.

### Architecture

```
Settings → Investment Plan → PUT /api/settings/plan → data/plan.json
Manage → Income txn + Plan Bucket dropdown → plan_bucket column in expenses.xlsx
/plan route → plan.py (pure calc) + get_all_transactions() + networth_history.json → templates/plan.html
Dashboard load → snapshot_networth_if_needed() → networth_history.json (once per calendar month)
```

### `data/plan.json`

```json
{
  "plan_start_date": "2026-08-01",
  "phase1_target_total": 255000,
  "monthly_base": 130000,
  "base_income": 176736,
  "base_expense": 45000,
  "buckets": [
    {"id": "equity", "label": "Core equity", "amount": 60000, "ratio": 0.461538, "account_id": 3, "color": "blue"}
  ],
  "phase1_buckets": {"buffer": 0.117647, "fd_topup": 0.882353},
  "income_growth_pct": 18,
  "expense_growth_pct": 5,
  "extra_routing": "same_ratio",
  "no_penalty_mode": true
}
```

- `buckets[].account_id`: an `accounts.json` `id` (int), or `null` for buckets with no fixed account (e.g. `fd_topup`, matched by FD subtype instead — see `plan.html`/`manage.html` bucket pre-select logic)
- `buckets[].ratio`: derived server-side (`amount / monthly_base`) in `api_update_plan_config()` — never trust a client-submitted ratio
- `phase1_buckets`: optional `{bucket_id: ratio}` split used only during the Phase 1 (emergency-fund) window; falls back to an even split across whichever of `buffer`/`fd_topup` are present (`plan.default_phase1_buckets()`) if omitted
- `income_growth_pct` / `expense_growth_pct`: applied per completed **plan year** (12-month block from `plan_start_date`), not calendar year — `0` disables escalation entirely
- `no_penalty_mode`: currently informational only — there is no "behind schedule" red styling anywhere to suppress in the first place (by design), so this flag has no functional branch yet in `plan.html`

### `plan.py` — pure functions (no Flask import, unit-tested in `tests/test_plan.py`)

| Function | Purpose |
|---|---|
| `phase1_month_count(plan)` | `ceil(phase1_target_total / monthly_base)` |
| `monthly_target(plan, month_offset)` | Target per bucket for one 0-based month offset since `plan_start_date` — phase 1 split or phase 2 ratios + income/expense-growth-driven "extra" |
| `elapsed_month_offsets(plan, as_of_date)` | `[0..N]` inclusive — every month touched so far, **including** the current in-progress one |
| `completed_month_offsets(plan, as_of_date)` | `elapsed_month_offsets(...)[:-1]` — excludes the current in-progress month. **Use this, not `elapsed_month_offsets`, for anything that shouldn't assume a not-yet-finished month's target already happened** (cumulative target, trajectory, months-contributed denominator) |
| `cumulative_target(plan, as_of_date)` | Sum of monthly targets over `completed_month_offsets` |
| `cumulative_actual(transactions, plan, as_of_date, accounts)` | Sum of real tagged Income **or Transfer-with-destination** transactions since `plan_start_date` through `as_of_date`, plus matched FD account principals (see below) — **not** offset-based, so it reflects real contributions immediately even mid-month. A `Transfer` tagged with a bucket but no `transfer_to_account` is ignored — nothing was actually credited anywhere, so it shouldn't count (`_plan_transactions()`) |
| `this_month_target` / `this_month_actual` | Current calendar month only, for the "This Month" progress bars — intentionally *not* gated by completion, since that section is meant to show live in-progress status |
| `months_contributed(transactions, plan, as_of_date)` | `(N, M)` — completed months with ≥1 tagged contribution, out of total completed months |
| `trajectory(plan, as_of_date, baseline_networth)` | `[(month_key, projected_networth), ...]` over `completed_month_offsets` only |

**Why `completed_month_offsets` exists:** an earlier version summed over `elapsed_month_offsets` (including the current month) everywhere, so a brand-new plan — or a `plan_start_date` change to today — instantly showed a full month's target as "already due" and the trajectory chart showed projected net worth jumping ahead of actual by a full month's contribution, before any time had passed to act on it. Fixed by excluding the in-progress month from every target/projection calc; `cumulative_actual` and `this_month_*` were left untouched since they reflect real, live data rather than a target/goal.

### Net worth history (`data/networth_history.json`)

```json
{"2026-07": 235462.44, "2026-08": 344867.0}
```

- Written by `snapshot_networth_if_needed()` (app.py, called from the `/dashboard` route) — one entry per calendar month, computed via `compute_net_worth()` (savings + live investment/FD values − CC debt, same formula as the dashboard's client-side `renderNetWorth()`, but server-side so it's usable outside a browser session)
- Idempotent — does nothing if the current month's key already exists
- No backfill: history only starts accumulating from whenever a dashboard load first happens after this feature shipped. The trajectory chart's "actual" line is only as long as this file's history.

### `/plan` route pre-existing-plan handling

If `data/plan.json` doesn't exist or has no buckets, `plan_page()` renders `plan.html` with `plan_config=None`, which shows an empty-state pointing to Settings — no crash, no special-casing needed elsewhere.

### `plan.html` client-side rendering (all computed from server-passed `projected`/`actual_series`/etc. — no backend changes)

- **`renderHeadline()`** — the "₹X ahead/behind plan" stat card at the top of the page. Matches on the **latest month `actualSeries` actually has** (`actualSeries[actualSeries.length - 1]`), then looks up `projected`'s value for that *same* month key via `.find()` — not just `projected`'s last index — since `actualSeries` (from `networth_history.json`) can start later or have gaps relative to `projected` (which covers every completed month since plan start). Hidden (`display:none`) if either series is empty or no matching month exists.
- **Trajectory chart color**: "Actual" line uses `--bucket-gray` (neutral), not `--success`. `--success`/`--danger` are reserved for `renderHeadline()`'s verdict and the cumulative table's Δ column — coloring a plain historical fact green implied "you're winning" even when the line was below the projection.
- **`renderThisMonth()`** — adds a `met = target > 0 && actual >= target` check; renders "✓ Target met" (styled `--success`, bold) instead of the usual "X% of target reached" text once a bucket hits its goal.
- **`renderCumulative()`** — the table gained a 4th **Δ** column (`actual − target` per bucket, plus a grand total row), colored `--success`/`--danger` — this is the one other place on the page those tokens are used correctly, as an actual ahead/behind verdict rather than a series label.
- **`renderFunFundBalance()`** — the "Guilt-Free Balance" stat now renders through the shared `fmt()` (Indian-grouped, no decimals) instead of Jinja's `"%.2f"|format(...)`, matching every other number on this page (was the only amount on `/plan` rendering as `₹45231.00` instead of `₹45,231`).
- **`renderChartTable()`** on the trajectory chart — see Chart table fallback in the Frontend Architecture → UI Patterns section.

---

## Logging

The app uses Flask's `app.logger` for structured logging. In Docker, all logs appear in `docker logs expense-manager`.

**Logged events:**

| Event | Level | Details |
|-------|-------|---------|
| Login success/failure | INFO/WARNING | Username + IP address |
| Transaction CRUD | INFO/ERROR | ID, description, amount, account |
| Draft ingest | INFO | Source IP, email size, LLM parse result |
| Draft accept/reject | INFO | Draft ID, merchant, amount |
| LLM parse failure | ERROR | Email text preview |
| Invalid API key | WARNING | Source IP |
| Yahoo Finance failure | WARNING | Ticker + error |
| Settings changes | INFO | Enabled status, LLM URL |
| Bulk accept failures | WARNING | Draft ID + error |

---

## Known Limitations

- **Single user only** — no multi-user support, no user management
- **Thread-safe but not multi-process safe** — thread locks protect concurrent writes within a single process (gunicorn -w 1). Running multiple workers would require file-level locking
- **No pagination** — all transactions are loaded at once. Will slow down with thousands of entries
- **Dashboard recomputes on every load** — `compute_account_balances()` reads all transactions every time
- **No template inheritance** — each template is standalone, so nav/structure changes must be replicated across all 8 files (setup, login, dashboard, analytics, manage, accounts, plan, settings). Theme CSS/JS is shared via static files.
- **Yahoo Finance dependency** — investment prices rely on an unofficial API that could break. Failures are handled gracefully (shows "Price unavailable")
- **No investment transaction history** — unit updates are immediate; there's no log of past unit changes separate from the transaction list
- **FD interest is estimated** — calculated using standard compound interest formula; actual bank interest may differ slightly due to day-count conventions
- **Plan trajectory has no historical backfill** — `networth_history.json` only starts accumulating from whenever the plan-vs-actual feature is first used; there's no way to reconstruct past months' net worth retroactively
- **Plan tracking is calendar-month granular, not salary-cycle aware** — "this month" always means the 1st–end-of-calendar-month, regardless of what day salary actually lands; setting `plan_start_date` mid-month means that first partial month still counts as a full "plan month" toward the Phase 1 window
- **`plan_bucket` tagging applies to Income and one-step Transfer transactions, not Expense** — resolved the old limitation where only the `Income` leg of a manual two-transaction transfer could be tagged; a one-step `Transfer` with a `transfer_to_account` set can now be tagged directly (see "One-step transfers" above)
