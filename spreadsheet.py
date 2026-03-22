import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
import os
from datetime import date, datetime
from collections import defaultdict

# ── Config ─────────────────────────────────────────────────────────────────────

XLSX_PATH = os.environ.get('EXPENSES_XLSX', os.path.join(os.path.dirname(__file__), 'expenses.xlsx'))

COLUMNS = {
    'date': 1,          # A
    'txn_id': 2,        # B
    'description': 3,   # C
    'category': 4,      # D
    'sub_category': 5,  # E
    'account': 6,       # F
    'amount': 7,        # G
    'parent_id': 8,     # H
    'savings_bal': 9,   # I
    'cc_accum': 10,     # J
    'cc_remaining': 11, # K
}

HEADER_ROW = 1   # "Credit Card Limit" label
DATA_ROW = 2     # "Opening Savings Balance" label
TABLE_START = 4  # Column headers row
DATA_START = 5   # First transaction row

CC_LIMIT_COL = 2      # B1
OPENING_BAL_COL = 2   # B2


# ── Workbook helpers ───────────────────────────────────────────────────────────

def load_workbook():
    if not os.path.exists(XLSX_PATH):
        wb = openpyxl.Workbook()
        # Default sheet will be removed when first month sheet is created
        wb.active.title = '_init'
        wb.save(XLSX_PATH)
    return openpyxl.load_workbook(XLSX_PATH)


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
        # Remove placeholder sheet if it exists
        if '_init' in wb.sheetnames:
            del wb['_init']
        save_workbook(wb)
        wb = load_workbook()

    return wb, wb[name]


def _init_sheet(ws):
    """Set up headers and formatting for a new month sheet."""
    thin = Side(style='thin')
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    # Meta rows
    ws['A1'] = 'Credit Card Limit'
    ws['A2'] = 'Opening Savings Balance'
    ws['B1'] = 0
    ws['B2'] = 0

    for cell in [ws['A1'], ws['A2']]:
        cell.font = Font(bold=True)

    # Column headers row (row 4)
    headers = ['Date', 'Txn ID', 'Description', 'Category', 'Sub-Category',
               'Account', 'Amount (₹)', 'Parent ID', 'Savings Balance', 'CC Accumulated', 'CC Remaining']
    for col, header in enumerate(headers, start=1):
        cell = ws.cell(row=TABLE_START, column=col, value=header)
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = PatternFill(fill_type='solid', fgColor='1a1a2e')
        cell.alignment = Alignment(horizontal='center')
        cell.border = border

    # Column widths
    widths = [12, 8, 28, 16, 16, 14, 14, 10, 16, 16, 16]
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


# ── Read ───────────────────────────────────────────────────────────────────────

def parse_row(row, sheet_name):
    """Convert a raw openpyxl row tuple to a dict."""
    def val(col_name):
        v = row[COLUMNS[col_name] - 1]
        return v

    txn_id = val('txn_id')
    if not isinstance(txn_id, int):
        return None  # skip header/empty rows

    date_val = val('date')
    if isinstance(date_val, datetime):
        date_str = date_val.strftime('%Y-%m-%d')
    elif isinstance(date_val, date):
        date_str = date_val.strftime('%Y-%m-%d')
    else:
        date_str = str(date_val) if date_val else ''

    return {
        'id': txn_id,
        'date': date_str,
        'description': val('description') or '',
        'category': val('category') or '',
        'sub_category': val('sub_category') or '',
        'account': val('account') or '',
        'amount': float(val('amount') or 0),
        'parent_id': val('parent_id'),
        'savings_bal': val('savings_bal'),
        'cc_accum': val('cc_accum'),
        'cc_remaining': val('cc_remaining'),
        'sheet': sheet_name,
    }


def get_all_transactions():
    """Return all transactions across all sheets, sorted by date desc."""
    wb = load_workbook()
    transactions = []
    for name in wb.sheetnames:
        ws = wb[name]
        for row in ws.iter_rows(min_row=DATA_START, values_only=True):
            parsed = parse_row(row, name)
            if parsed:
                transactions.append(parsed)
    transactions.sort(key=lambda t: t['date'], reverse=True)
    return transactions


def get_transaction_by_id(txn_id):
    wb = load_workbook()
    for name in wb.sheetnames:
        ws = wb[name]
        for row in ws.iter_rows(min_row=DATA_START, values_only=True):
            parsed = parse_row(row, name)
            if parsed and parsed['id'] == txn_id:
                return parsed
    return None


def get_header_info(ws):
    cc_limit = ws.cell(row=HEADER_ROW, column=CC_LIMIT_COL).value or 0
    opening_bal = ws.cell(row=DATA_ROW, column=OPENING_BAL_COL).value or 0
    return float(cc_limit), float(opening_bal)


# ── Write ──────────────────────────────────────────────────────────────────────

def add_transaction(date_str, description, category, sub_category, account, amount, parent_id=None):
    """Append a transaction to the correct month sheet. Returns txn_id."""
    d = datetime.strptime(date_str, '%Y-%m-%d').date()
    wb, ws = ensure_month_sheet(d.year, d.month)
    cc_limit, opening_bal = get_header_info(ws)

    txn_id = get_next_txn_id(wb)
    ws_fresh = wb[month_sheet_name(d.year, d.month)]

    # Find next empty row
    next_row = DATA_START
    while ws_fresh.cell(row=next_row, column=COLUMNS['txn_id']).value is not None:
        next_row += 1

    # Calculate running balances
    savings_bal = None
    cc_accum = None
    cc_remaining = None

    # Collect existing parent rows for balance calculations
    parent_transactions = []
    for row in ws_fresh.iter_rows(min_row=DATA_START, max_row=next_row - 1, values_only=True):
        p = parse_row(row, '')
        if p and p['parent_id'] is None:
            parent_transactions.append(p)

    is_parent = (parent_id is None)

    if is_parent:
        # Savings balance calculation
        prev_savings = opening_bal
        for t in parent_transactions:
            if t['savings_bal'] is not None:
                prev_savings = float(t['savings_bal'])

        if account == 'Savings':
            savings_bal = prev_savings - amount
        else:
            savings_bal = prev_savings  # CC doesn't change savings

        # CC accumulated
        prev_cc = 0
        for t in parent_transactions:
            if t['cc_accum'] is not None:
                prev_cc = float(t['cc_accum'])

        if account == 'Credit Card':
            cc_accum = prev_cc + amount
        else:
            cc_accum = prev_cc

        cc_remaining = cc_limit - cc_accum if cc_limit else None

    # Write row
    ws_fresh.cell(row=next_row, column=COLUMNS['date']).value = d
    ws_fresh.cell(row=next_row, column=COLUMNS['txn_id']).value = txn_id
    ws_fresh.cell(row=next_row, column=COLUMNS['description']).value = description
    ws_fresh.cell(row=next_row, column=COLUMNS['category']).value = category
    ws_fresh.cell(row=next_row, column=COLUMNS['sub_category']).value = sub_category or ''
    ws_fresh.cell(row=next_row, column=COLUMNS['account']).value = account
    ws_fresh.cell(row=next_row, column=COLUMNS['amount']).value = amount
    ws_fresh.cell(row=next_row, column=COLUMNS['parent_id']).value = parent_id

    if savings_bal is not None:
        ws_fresh.cell(row=next_row, column=COLUMNS['savings_bal']).value = round(savings_bal, 2)
    if cc_accum is not None:
        ws_fresh.cell(row=next_row, column=COLUMNS['cc_accum']).value = round(cc_accum, 2)
    if cc_remaining is not None:
        ws_fresh.cell(row=next_row, column=COLUMNS['cc_remaining']).value = round(cc_remaining, 2)

    # Format amount cell
    ws_fresh.cell(row=next_row, column=COLUMNS['amount']).number_format = '₹#,##0.00'

    save_workbook(wb)
    return txn_id


# ── Summary for dashboard ──────────────────────────────────────────────────────

def get_monthly_summary():
    """Return structured data for Plotly dashboard."""
    transactions = get_all_transactions()
    # Only parent transactions for charts (avoid double-counting)
    parents = [t for t in transactions if not t['parent_id']]

    monthly = defaultdict(lambda: defaultdict(float))
    daily = defaultdict(float)
    by_category = defaultdict(float)
    by_account = defaultdict(float)

    for t in parents:
        month = t['date'][:7]  # YYYY-MM
        monthly[month][t['category']] += t['amount']
        daily[t['date']] += t['amount']
        by_category[t['category']] += t['amount']
        by_account[t['account']] += t['amount']

    return {
        'monthly': {k: dict(v) for k, v in sorted(monthly.items())},
        'daily': dict(sorted(daily.items())),
        'by_category': dict(sorted(by_category.items(), key=lambda x: -x[1])),
        'by_account': dict(by_account),
        'transactions': parents[:50],  # recent 50 for table
    }
