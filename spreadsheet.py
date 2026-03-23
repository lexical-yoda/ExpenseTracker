import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
import os
import json
from datetime import date, datetime
from collections import defaultdict

# ── Config ─────────────────────────────────────────────────────────────────────

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
XLSX_PATH = os.environ.get('EXPENSES_XLSX', os.path.join(DATA_DIR, 'expenses.xlsx'))
ACCOUNTS_FILE = os.path.join(DATA_DIR, 'accounts.json')

COLUMNS = {
    'date': 1,          # A
    'txn_id': 2,        # B
    'description': 3,   # C
    'category': 4,      # D
    'sub_category': 5,  # E
    'account': 6,       # F — stores full account name
    'amount': 7,        # G
    'parent_id': 8,     # H
    'txn_type': 9,      # I
    'track': 10,        # J — Yes/No, controls dashboard visibility
    'units': 11,        # K — units bought/sold for investment accounts
}

TABLE_START = 1  # Column headers row
DATA_START = 2   # First transaction row


# ── Workbook helpers ───────────────────────────────────────────────────────────

def load_workbook(data_only=False):
    if not os.path.exists(XLSX_PATH):
        wb = openpyxl.Workbook()
        wb.active.title = '_init'
        wb.save(XLSX_PATH)
    return openpyxl.load_workbook(XLSX_PATH, data_only=data_only)


def save_workbook(wb):
    wb.save(XLSX_PATH)


def month_sheet_name(year=None, month=None):
    if year is None or month is None:
        today = date.today()
        year, month = today.year, today.month
    return datetime(year, month, 1).strftime('%B %Y')


def ensure_month_sheet(year=None, month=None):
    """Create month sheet if it doesn't exist. Returns (wb, ws)."""
    wb = load_workbook()
    name = month_sheet_name(year, month)

    if name not in wb.sheetnames:
        ws = wb.create_sheet(name)
        _init_sheet(ws)
        if '_init' in wb.sheetnames:
            del wb['_init']
        save_workbook(wb)
        wb = load_workbook()

    return wb, wb[name]


def _init_sheet(ws):
    """Set up headers and formatting for a new month sheet."""
    thin = Side(style='thin')
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    headers = ['Date', 'Txn ID', 'Description', 'Category', 'Sub-Category',
               'Account', 'Amount (₹)', 'Parent ID', 'Type', 'Track', 'Units']
    widths = [12, 8, 28, 16, 16, 24, 14, 10, 10, 8, 10]

    for col, header in enumerate(headers, start=1):
        if not header:
            continue
        cell = ws.cell(row=TABLE_START, column=col, value=header)
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = PatternFill(fill_type='solid', fgColor='1a1a2e')
        cell.alignment = Alignment(horizontal='center')
        cell.border = border

    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


# ── Transaction ID management ─────────────────────────────────────────────────

def get_next_txn_id(wb):
    """Scan all sheets and return max txn_id + 1."""
    max_id = 0
    for name in wb.sheetnames:
        ws = wb[name]
        for row in ws.iter_rows(min_row=DATA_START, values_only=True):
            txn_id = row[COLUMNS['txn_id'] - 1]
            if isinstance(txn_id, int) and txn_id > max_id:
                max_id = txn_id
    return max_id + 1


def sanitize_cell(value):
    """Prevent formula injection in spreadsheet cells."""
    if isinstance(value, str) and value and value[0] in ('=', '+', '-', '@'):
        return "'" + value
    return value


# ── Read ───────────────────────────────────────────────────────────────────────

def parse_row(row, sheet_name):
    """Convert a raw openpyxl row tuple to a dict."""
    def val(col_name):
        idx = COLUMNS[col_name] - 1
        return row[idx] if idx < len(row) else None

    txn_id = val('txn_id')
    if not isinstance(txn_id, int):
        return None

    date_val = val('date')
    if isinstance(date_val, datetime):
        date_str = date_val.strftime('%Y-%m-%d')
    elif isinstance(date_val, date):
        date_str = date_val.strftime('%Y-%m-%d')
    else:
        date_str = str(date_val) if date_val else ''

    txn_type = val('txn_type')
    track_val = val('track')
    # Default to 'Yes' if column is empty or missing (backward compat)
    tracked = True if track_val is None or str(track_val).strip().lower() in ('yes', 'true', '1', '') else False

    units_val = val('units')
    units = float(units_val) if units_val is not None and units_val != '' else None

    return {
        'id': txn_id,
        'date': date_str,
        'description': val('description') or '',
        'category': val('category') or '',
        'sub_category': val('sub_category') or '',
        'account': val('account') or '',
        'amount': float(val('amount') or 0),
        'parent_id': val('parent_id'),
        'type': txn_type or 'Expense',
        'track': tracked,
        'units': units,
        'sheet': sheet_name,
    }


def get_all_transactions():
    """Return all transactions across all sheets, sorted by date desc."""
    wb = load_workbook(data_only=True)
    transactions = []
    for name in wb.sheetnames:
        ws = wb[name]
        for row in ws.iter_rows(min_row=DATA_START, values_only=True):
            parsed = parse_row(row, name)
            if parsed:
                transactions.append(parsed)
    transactions.sort(key=lambda t: (t['date'], t['id']), reverse=True)
    return transactions


def get_transaction_by_id(txn_id):
    wb = load_workbook(data_only=True)
    for name in wb.sheetnames:
        ws = wb[name]
        for row in ws.iter_rows(min_row=DATA_START, values_only=True):
            parsed = parse_row(row, name)
            if parsed and parsed['id'] == txn_id:
                return parsed
    return None


# ── Write ──────────────────────────────────────────────────────────────────────

def add_transaction(date_str, description, category, sub_category, account, amount, parent_id=None, txn_type='Expense', track=True, units=None):
    """Append a transaction to the correct month sheet. Returns txn_id."""
    d = datetime.strptime(date_str, '%Y-%m-%d').date()
    wb, ws = ensure_month_sheet(d.year, d.month)

    txn_id = get_next_txn_id(wb)
    sheet_name = month_sheet_name(d.year, d.month)
    ws_fresh = wb[sheet_name]

    # Find next empty row
    next_row = DATA_START
    while ws_fresh.cell(row=next_row, column=COLUMNS['txn_id']).value is not None:
        next_row += 1

    # Write row
    ws_fresh.cell(row=next_row, column=COLUMNS['date']).value = d
    ws_fresh.cell(row=next_row, column=COLUMNS['txn_id']).value = txn_id
    ws_fresh.cell(row=next_row, column=COLUMNS['description']).value = sanitize_cell(description)
    ws_fresh.cell(row=next_row, column=COLUMNS['category']).value = sanitize_cell(category)
    ws_fresh.cell(row=next_row, column=COLUMNS['sub_category']).value = sanitize_cell(sub_category or '')
    ws_fresh.cell(row=next_row, column=COLUMNS['account']).value = sanitize_cell(account)
    ws_fresh.cell(row=next_row, column=COLUMNS['amount']).value = amount
    ws_fresh.cell(row=next_row, column=COLUMNS['parent_id']).value = parent_id
    ws_fresh.cell(row=next_row, column=COLUMNS['txn_type']).value = txn_type
    ws_fresh.cell(row=next_row, column=COLUMNS['track']).value = 'Yes' if track else 'No'
    if units is not None:
        ws_fresh.cell(row=next_row, column=COLUMNS['units']).value = units
    ws_fresh.cell(row=next_row, column=COLUMNS['amount']).number_format = '₹#,##0.00'

    save_workbook(wb)

    # Auto-update investment account units & balance
    if units is not None and not parent_id:
        _update_investment_account(account, amount, units, txn_type)

    return txn_id


def _update_investment_account(account_name, amount, units, txn_type):
    """Auto-update investment account units and invested amount on transaction."""
    if not os.path.exists(ACCOUNTS_FILE):
        return
    with open(ACCOUNTS_FILE, 'r') as f:
        accounts = json.load(f)

    for acct in accounts:
        if acct['name'] == account_name and acct.get('type') == 'investment':
            if txn_type == 'Income':
                acct['units'] = acct.get('units', 0) + units
                acct['balance'] = acct.get('balance', 0) + amount
            elif txn_type == 'Expense':
                acct['units'] = max(0, acct.get('units', 0) - units)
                acct['balance'] = max(0, acct.get('balance', 0) - amount)
            with open(ACCOUNTS_FILE, 'w') as f:
                json.dump(accounts, f, indent=2)
            break


# ── Find / Edit / Delete ──────────────────────────────────────────────────────

def find_transaction_row(wb, txn_id):
    """Find the sheet name and row number for a given txn_id."""
    for name in wb.sheetnames:
        ws = wb[name]
        for row_num in range(DATA_START, ws.max_row + 1):
            if ws.cell(row=row_num, column=COLUMNS['txn_id']).value == txn_id:
                return (name, row_num)
    return None


def update_transaction(txn_id, data):
    """Update a transaction in place. Returns updated dict."""
    wb = load_workbook()
    result = find_transaction_row(wb, txn_id)
    if not result:
        raise ValueError(f'Transaction {txn_id} not found')

    sheet_name, row_num = result
    ws = wb[sheet_name]

    old_date = ws.cell(row=row_num, column=COLUMNS['date']).value
    new_date = datetime.strptime(data['date'], '%Y-%m-%d').date()
    if isinstance(old_date, datetime):
        old_date = old_date.date()

    if (old_date.year, old_date.month) != (new_date.year, new_date.month):
        raise ValueError('Cannot change date to a different month. Delete and re-add instead.')

    ws.cell(row=row_num, column=COLUMNS['date']).value = new_date
    ws.cell(row=row_num, column=COLUMNS['description']).value = sanitize_cell(data['description'])
    ws.cell(row=row_num, column=COLUMNS['category']).value = sanitize_cell(data['category'])
    ws.cell(row=row_num, column=COLUMNS['sub_category']).value = sanitize_cell(data.get('sub_category', ''))
    ws.cell(row=row_num, column=COLUMNS['account']).value = sanitize_cell(data['account'])
    ws.cell(row=row_num, column=COLUMNS['amount']).value = float(data['amount'])
    ws.cell(row=row_num, column=COLUMNS['amount']).number_format = '₹#,##0.00'
    ws.cell(row=row_num, column=COLUMNS['txn_type']).value = data.get('type', 'Expense')
    if 'track' in data:
        ws.cell(row=row_num, column=COLUMNS['track']).value = 'Yes' if data['track'] else 'No'
    if 'units' in data and data['units'] is not None:
        ws.cell(row=row_num, column=COLUMNS['units']).value = float(data['units'])

    save_workbook(wb)
    return get_transaction_by_id(txn_id)


def delete_transaction(txn_id):
    """Delete a transaction. If parent, also deletes all sub-items."""
    wb = load_workbook()
    result = find_transaction_row(wb, txn_id)
    if not result:
        raise ValueError(f'Transaction {txn_id} not found')

    sheet_name, row_num = result
    ws = wb[sheet_name]

    parent_id = ws.cell(row=row_num, column=COLUMNS['parent_id']).value
    rows_to_delete = [row_num]
    deleted_ids = [txn_id]

    if parent_id is None:
        for r in range(DATA_START, ws.max_row + 1):
            if r == row_num:
                continue
            pid = ws.cell(row=r, column=COLUMNS['parent_id']).value
            if pid == txn_id:
                rows_to_delete.append(r)
                deleted_ids.append(ws.cell(row=r, column=COLUMNS['txn_id']).value)

    for r in sorted(rows_to_delete, reverse=True):
        ws.delete_rows(r, 1)

    save_workbook(wb)
    return deleted_ids


# ── Account operations ────────────────────────────────────────────────────────

def rename_account_in_sheets(old_name, new_name):
    """Rename an account across all transaction sheets."""
    wb = load_workbook()
    changed = False
    for name in wb.sheetnames:
        ws = wb[name]
        for row_num in range(DATA_START, ws.max_row + 1):
            cell = ws.cell(row=row_num, column=COLUMNS['account'])
            if cell.value == old_name:
                cell.value = new_name
                changed = True
    if changed:
        save_workbook(wb)


def compute_account_balances():
    """Compute current balance for each account from accounts.json + transactions."""
    with open(ACCOUNTS_FILE, 'r') as f:
        accounts = json.load(f)

    transactions = get_all_transactions()
    parents = [t for t in transactions if not t['parent_id']]

    spend_by_account = defaultdict(float)
    income_by_account = defaultdict(float)
    for t in parents:
        if t['type'] == 'Income':
            income_by_account[t['account']] += t['amount']
        else:
            # Both Expense and Transfer reduce account balance
            spend_by_account[t['account']] += t['amount']

    result = []
    for acct in accounts:
        name = acct['name']
        spent = spend_by_account.get(name, 0)
        earned = income_by_account.get(name, 0)
        if acct['type'] == 'savings':
            current = acct['balance'] - spent + earned
            result.append({**acct, 'current_balance': round(current, 2)})
        elif acct['type'] == 'credit':
            accumulated = spent - earned
            remaining = acct['limit'] - accumulated
            result.append({**acct, 'accumulated': round(accumulated, 2), 'remaining': round(remaining, 2)})
        elif acct['type'] == 'investment':
            # Investment accounts: balance = cost basis / principal
            entry = {**acct, 'invested': acct.get('balance', 0)}
            entry['subtype'] = acct.get('subtype', 'market')
            result.append(entry)
    return result


# ── Summary for dashboard ──────────────────────────────────────────────────────

def get_monthly_summary():
    """Return structured data for Plotly dashboard."""
    transactions = get_all_transactions()
    parents = [t for t in transactions if not t['parent_id']]

    monthly = defaultdict(lambda: defaultdict(float))
    daily = defaultdict(float)
    by_category = defaultdict(float)
    by_account = defaultdict(float)

    for t in parents:
        if t['type'] == 'Transfer':
            continue  # Transfers excluded from summary charts
        if t['type'] == 'Income':
            continue  # Income excluded from spending charts
        if not t['track']:
            continue  # Untracked transactions excluded from charts
        month = t['date'][:7]
        monthly[month][t['category']] += t['amount']
        daily[t['date']] += t['amount']
        by_category[t['category']] += t['amount']
        by_account[t['account']] += t['amount']

    return {
        'monthly': {k: dict(v) for k, v in sorted(monthly.items())},
        'daily': dict(sorted(daily.items())),
        'by_category': dict(sorted(by_category.items(), key=lambda x: -x[1])),
        'by_account': dict(by_account),
        'transactions': parents,
    }
