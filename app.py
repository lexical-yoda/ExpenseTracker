from flask import Flask, render_template, request, jsonify, redirect, url_for, session, Response
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_wtf.csrf import CSRFProtect
from dotenv import load_dotenv
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import bcrypt
import json
import os
import urllib.request
import urllib.error
from spreadsheet import (
    get_all_transactions, add_transaction, get_transaction_by_id,
    get_monthly_summary, update_transaction, delete_transaction,
    rename_account_in_sheets, compute_account_balances
)
from datetime import date, datetime

load_dotenv()

app = Flask(__name__)

# Persist secret key: check env, then .env file, then generate and save
def _get_or_create_secret_key():
    key = os.environ.get('SECRET_KEY')
    if key:
        return key
    env_file = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_file):
        with open(env_file, 'r') as f:
            for line in f:
                if line.strip().startswith('SECRET_KEY='):
                    return line.strip().split('=', 1)[1]
    # Generate and persist
    key = os.urandom(32).hex()
    os.makedirs(os.path.dirname(env_file) or '.', exist_ok=True)
    with open(env_file, 'a') as f:
        f.write(f"\nSECRET_KEY={key}\n")
    return key

app.secret_key = _get_or_create_secret_key()
# SECURE=True only when behind HTTPS (nginx/reverse proxy sets X-Forwarded-Proto)
# For local HTTP dev, this stays False so cookies actually work
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('SECURE_COOKIES', 'false').lower() == 'true'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['REMEMBER_COOKIE_DURATION'] = 2592000  # 30 days

limiter = Limiter(get_remote_address, app=app, default_limits=[])
csrf = CSRFProtect(app)


@app.template_filter('dayname')
def dayname_filter(date_str):
    """Convert 'YYYY-MM-DD' to day name like 'Monday'."""
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').strftime('%A')
    except (ValueError, TypeError):
        return ''

# ── Paths ─────────────────────────────────────────────────────────────────────

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
AUTH_FILE = os.path.join(DATA_DIR, 'auth.json')
ACCOUNTS_FILE = os.path.join(DATA_DIR, 'accounts.json')
CATEGORIES_FILE = os.path.join(DATA_DIR, 'categories.json')

# ── Auth helpers ──────────────────────────────────────────────────────────────

def load_auth():
    """Load auth credentials from data/auth.json. Returns dict or None."""
    if not os.path.exists(AUTH_FILE):
        return None
    try:
        with open(AUTH_FILE, 'r') as f:
            data = json.load(f)
        if data.get('username') and data.get('password_hash'):
            return data
    except (json.JSONDecodeError, KeyError):
        pass
    return None


def save_auth(username, password_hash):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(AUTH_FILE, 'w') as f:
        json.dump({'username': username, 'password_hash': password_hash}, f, indent=2)
    os.chmod(AUTH_FILE, 0o600)


def is_setup_complete():
    return load_auth() is not None


login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


class User(UserMixin):
    def __init__(self, username):
        self.id = username


@login_manager.user_loader
def load_user(user_id):
    auth = load_auth()
    if auth and user_id == auth['username']:
        return User(user_id)
    return None


@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def login():
    if not is_setup_complete():
        return redirect(url_for('setup'))

    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    error = None
    if request.method == 'POST':
        auth = load_auth()
        username = request.form.get('username', '')
        password = request.form.get('password', '')

        if (auth and username == auth['username'] and
                bcrypt.checkpw(password.encode('utf-8'), auth['password_hash'].encode('utf-8'))):
            login_user(User(username), remember=True)
            next_page = request.args.get('next', '')
            # Only allow relative paths to prevent open redirect attacks
            if not next_page or not next_page.startswith('/') or next_page.startswith('//'):
                next_page = url_for('dashboard')
            return redirect(next_page)
        else:
            error = 'Invalid username or password'

    return render_template('login.html', error=error)


@app.route('/setup', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def setup():
    if is_setup_complete():
        return redirect(url_for('login'))

    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')

        if not username:
            error = 'Username is required'
        elif len(password) < 6:
            error = 'Password must be at least 6 characters'
        elif password != confirm:
            error = 'Passwords do not match'
        else:
            pw_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

            os.makedirs(DATA_DIR, exist_ok=True)

            # Save auth
            save_auth(username, pw_hash)

            # Parse accounts from form
            accounts = []
            acct_idx = 0
            while True:
                name = request.form.get(f'acct_name_{acct_idx}', '').strip()
                if not name:
                    break
                acct_type = request.form.get(f'acct_type_{acct_idx}', 'savings')
                acct = {'id': acct_idx + 1, 'name': name, 'type': acct_type}
                if acct_type == 'savings':
                    acct['balance'] = float(request.form.get(f'acct_balance_{acct_idx}', 0) or 0)
                else:
                    acct['limit'] = float(request.form.get(f'acct_limit_{acct_idx}', 0) or 0)
                accounts.append(acct)
                acct_idx += 1

            if not accounts:
                accounts = [{'id': 1, 'name': 'Savings', 'type': 'savings', 'balance': 0}]

            save_accounts(accounts)

            # Create default categories if missing
            if not os.path.exists(CATEGORIES_FILE):
                default_cats = {
                    "Groceries": [], "Dining": [], "Transport": [], "Utilities": [],
                    "Shopping": [], "Health": [], "Entertainment": [], "Education": [],
                    "Rent & Housing": [], "Savings & Investment": [], "Subscriptions": [],
                    "Personal": [], "Fuel": [], "Miscellaneous": [],
                    "Salary": [], "Freelance": [], "Refund": [], "Interest & Dividends": []
                }
                save_categories(default_cats)

            # Write .env if it doesn't exist (server config only)
            env_file = os.path.join(os.path.dirname(__file__), '.env')
            if not os.path.exists(env_file):
                secret_key = os.urandom(32).hex()
                with open(env_file, 'w') as f:
                    f.write("# Expense Manager Configuration\n\n")
                    f.write("HOST=0.0.0.0\n")
                    f.write("PORT=5000\n\n")
                    f.write(f"SECRET_KEY={secret_key}\n")

            return redirect(url_for('login'))

    return render_template('setup.html', error=error)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


# ── Categories ────────────────────────────────────────────────────────────────

def load_categories():
    if not os.path.exists(CATEGORIES_FILE):
        return {}
    with open(CATEGORIES_FILE, 'r') as f:
        return json.load(f)

def save_categories(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CATEGORIES_FILE, 'w') as f:
        json.dump(data, f, indent=2)


# ── Accounts ──────────────────────────────────────────────────────────────────

def load_accounts():
    if not os.path.exists(ACCOUNTS_FILE):
        return []
    with open(ACCOUNTS_FILE, 'r') as f:
        return json.load(f)

def save_accounts(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(ACCOUNTS_FILE, 'w') as f:
        json.dump(data, f, indent=2)


# ── Pages ─────────────────────────────────────────────────────────────────────

@app.route('/')
@login_required
def index():
    return redirect(url_for('dashboard'))


@app.route('/manage')
@login_required
def manage():
    categories = load_categories()
    accounts = load_accounts()
    today = date.today().strftime('%Y-%m-%d')
    transactions = get_all_transactions()
    parents = [t for t in transactions if not t['parent_id']]
    children = {}
    for t in transactions:
        if t['parent_id']:
            children.setdefault(t['parent_id'], []).append(t)
    parent_id = request.args.get('parent')
    parent = None
    if parent_id:
        try:
            parent = get_transaction_by_id(int(parent_id))
        except (ValueError, TypeError):
            pass
    return render_template('manage.html', categories=categories, accounts=accounts, today=today, parent=parent, parents=parents, children=children)


@app.route('/add')
@login_required
def add_expense():
    return redirect(url_for('manage'))


@app.route('/add/sub/<int:parent_id>')
@login_required
def add_sub_expense(parent_id):
    return redirect(url_for('manage', parent=parent_id))


@app.route('/expenses')
@login_required
def expenses():
    return redirect(url_for('manage'))


@app.route('/dashboard')
@login_required
def dashboard():
    summary = get_monthly_summary()
    accounts = load_accounts()
    balances = compute_account_balances()
    return render_template('dashboard.html', summary=summary, accounts=accounts, balances=balances)


@app.route('/analytics')
@login_required
def analytics():
    summary = get_monthly_summary()
    return render_template('analytics.html', summary=summary)


@app.route('/accounts')
@login_required
def accounts_page():
    accounts = load_accounts()
    balances = compute_account_balances()
    return render_template('accounts.html', accounts=accounts, balances=balances)


# ── API: Transactions ────────────────────────────────────────────────────────

@app.route('/api/transactions', methods=['POST'])
@login_required
def api_add_transaction():
    data = request.get_json()
    txn_type = data.get('type', 'Expense')
    if txn_type not in ('Expense', 'Income', 'Transfer'):
        return jsonify({'success': False, 'error': 'Type must be Expense, Income, or Transfer'}), 400
    try:
        units = float(data['units']) if data.get('units') else None
        txn_id = add_transaction(
            date_str=data['date'],
            description=data['description'],
            category=data['category'],
            sub_category=data.get('sub_category', ''),
            account=data['account'],
            amount=float(data['amount']),
            parent_id=data.get('parent_id') or None,
            txn_type=txn_type,
            track=data.get('track', True),
            units=units
        )
        return jsonify({'success': True, 'id': txn_id})
    except Exception as e:
        return jsonify({'success': False, 'error': 'Operation failed'}), 400


@app.route('/api/transactions', methods=['GET'])
@login_required
def api_get_transactions():
    return jsonify(get_all_transactions())


@app.route('/api/transactions/<int:txn_id>', methods=['GET'])
@login_required
def api_get_transaction(txn_id):
    txn = get_transaction_by_id(txn_id)
    if not txn:
        return jsonify({'success': False, 'error': 'Not found'}), 404
    return jsonify(txn)


@app.route('/api/transactions/<int:txn_id>', methods=['PUT'])
@login_required
def api_update_transaction(txn_id):
    data = request.get_json()
    txn_type = data.get('type', 'Expense')
    if txn_type not in ('Expense', 'Income', 'Transfer'):
        return jsonify({'success': False, 'error': 'Type must be Expense, Income, or Transfer'}), 400
    try:
        updated = update_transaction(txn_id, data)
        return jsonify({'success': True, 'transaction': updated})
    except ValueError as e:
        return jsonify({'success': False, 'error': 'Operation failed'}), 400


@app.route('/api/transactions/<int:txn_id>', methods=['DELETE'])
@login_required
def api_delete_transaction(txn_id):
    try:
        deleted_ids = delete_transaction(txn_id)
        return jsonify({'success': True, 'deleted_ids': deleted_ids})
    except ValueError as e:
        return jsonify({'success': False, 'error': 'Operation failed'}), 404


@app.route('/api/transactions/<int:txn_id>/track', methods=['PATCH'])
@login_required
def api_toggle_track(txn_id):
    data = request.get_json()
    track = data.get('track', True)
    try:
        txn = get_transaction_by_id(txn_id)
        if not txn:
            return jsonify({'success': False, 'error': 'Transaction not found'}), 404
        updated = update_transaction(txn_id, {**txn, 'track': track})
        return jsonify({'success': True, 'transaction': updated})
    except (ValueError, TypeError):
        return jsonify({'success': False, 'error': 'Operation failed'}), 400


# ── API: Categories ──────────────────────────────────────────────────────────

@app.route('/api/categories', methods=['GET'])
@login_required
def api_get_categories():
    return jsonify(load_categories())


@app.route('/api/categories', methods=['POST'])
@login_required
def api_add_category():
    data = request.get_json()
    cats = load_categories()
    cat_name = data.get('category', '').strip()
    sub_name = data.get('sub_category', '').strip()

    if not cat_name:
        return jsonify({'success': False, 'error': 'Category name required'}), 400

    if cat_name not in cats:
        cats[cat_name] = []

    if sub_name and sub_name not in cats[cat_name]:
        cats[cat_name].append(sub_name)

    save_categories(cats)
    return jsonify({'success': True, 'categories': cats})


# ── API: Accounts ────────────────────────────────────────────────────────────

@app.route('/api/accounts', methods=['GET'])
@login_required
def api_get_accounts():
    return jsonify(load_accounts())


@app.route('/api/accounts', methods=['POST'])
@login_required
def api_add_account():
    data = request.get_json()
    accounts = load_accounts()

    name = data.get('name', '').strip()
    acct_type = data.get('type', '').strip()

    if not name:
        return jsonify({'success': False, 'error': 'Account name required'}), 400
    if acct_type not in ('savings', 'credit', 'investment'):
        return jsonify({'success': False, 'error': 'Type must be savings, credit, or investment'}), 400
    if any(a['name'] == name for a in accounts):
        return jsonify({'success': False, 'error': 'Account name already exists'}), 400

    new_id = max((a['id'] for a in accounts), default=0) + 1
    new_account = {'id': new_id, 'name': name, 'type': acct_type}

    if acct_type == 'savings':
        new_account['balance'] = float(data.get('balance', 0))
    elif acct_type == 'credit':
        new_account['limit'] = float(data.get('limit', 0))
    elif acct_type == 'investment':
        subtype = data.get('subtype', 'market').strip()
        new_account['subtype'] = subtype
        new_account['balance'] = float(data.get('balance', 0))
        if subtype == 'fd':
            new_account['interest_rate'] = float(data.get('interest_rate', 0))
            new_account['start_date'] = data.get('start_date', '')
            new_account['maturity_date'] = data.get('maturity_date', '')
            new_account['compounding'] = data.get('compounding', 'quarterly')
        else:
            new_account['ticker'] = data.get('ticker', '').strip()
            new_account['units'] = float(data.get('units', 0))

    accounts.append(new_account)
    save_accounts(accounts)
    return jsonify({'success': True, 'account': new_account})


@app.route('/api/accounts/<int:account_id>', methods=['PUT'])
@login_required
def api_update_account(account_id):
    data = request.get_json()
    accounts = load_accounts()

    acct = next((a for a in accounts if a['id'] == account_id), None)
    if not acct:
        return jsonify({'success': False, 'error': 'Account not found'}), 404

    new_name = data.get('name', '').strip()
    if not new_name:
        return jsonify({'success': False, 'error': 'Account name required'}), 400

    if any(a['name'] == new_name and a['id'] != account_id for a in accounts):
        return jsonify({'success': False, 'error': 'Account name already exists'}), 400

    old_name = acct['name']

    acct['name'] = new_name
    if acct['type'] == 'savings':
        acct['balance'] = float(data.get('balance', acct.get('balance', 0)))
    elif acct['type'] == 'credit':
        acct['limit'] = float(data.get('limit', acct.get('limit', 0)))
    elif acct['type'] == 'investment':
        acct['balance'] = float(data.get('balance', acct.get('balance', 0)))
        subtype = acct.get('subtype', 'market')
        if subtype == 'fd':
            acct['interest_rate'] = float(data.get('interest_rate', acct.get('interest_rate', 0)))
            acct['start_date'] = data.get('start_date', acct.get('start_date', ''))
            acct['maturity_date'] = data.get('maturity_date', acct.get('maturity_date', ''))
            acct['compounding'] = data.get('compounding', acct.get('compounding', 'quarterly'))
        else:
            acct['ticker'] = data.get('ticker', acct.get('ticker', '')).strip()
            acct['units'] = float(data.get('units', acct.get('units', 0)))

    save_accounts(accounts)

    if old_name != new_name:
        rename_account_in_sheets(old_name, new_name)

    return jsonify({'success': True, 'account': acct})


@app.route('/api/accounts/<int:account_id>', methods=['DELETE'])
@login_required
def api_delete_account(account_id):
    accounts = load_accounts()
    acct = next((a for a in accounts if a['id'] == account_id), None)
    if not acct:
        return jsonify({'success': False, 'error': 'Account not found'}), 404

    transactions = get_all_transactions()
    in_use = any(t['account'] == acct['name'] for t in transactions)
    if in_use:
        return jsonify({'success': False, 'error': 'Cannot delete — transactions use this account'}), 400

    accounts = [a for a in accounts if a['id'] != account_id]
    save_accounts(accounts)
    return jsonify({'success': True})


@app.route('/api/accounts/balances', methods=['GET'])
@login_required
def api_account_balances():
    return jsonify(compute_account_balances())


@app.route('/api/summary', methods=['GET'])
@login_required
def api_get_summary():
    return jsonify(get_monthly_summary())


# ── Investment price fetching ────────────────────────────────────────────────

_price_cache = {}  # {ticker: (price, timestamp)}
PRICE_CACHE_TTL = 300  # 5 minutes

def fetch_yahoo_price(ticker):
    """Fetch current price from Yahoo Finance with 5-min cache. Returns float or None."""
    import time
    now = time.time()
    if ticker in _price_cache:
        price, ts = _price_cache[ticker]
        if now - ts < PRICE_CACHE_TTL:
            return price
    try:
        url = f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=1d&interval=1d'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            price = data['chart']['result'][0]['meta']['regularMarketPrice']
            _price_cache[ticker] = (price, now)
            return price
    except Exception:
        return None


def calculate_fd_value(principal, annual_rate, start_date, maturity_date, compounding='quarterly'):
    """Calculate current and maturity value of a fixed deposit."""
    from math import pow as mpow
    today = date.today()

    try:
        start = datetime.strptime(start_date, '%Y-%m-%d').date()
        maturity = datetime.strptime(maturity_date, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None

    # Compounding frequency per year
    n_map = {'monthly': 12, 'quarterly': 4, 'half-yearly': 2, 'yearly': 1}
    n = n_map.get(compounding, 4)
    rate = annual_rate / 100

    # Total tenure in years
    total_years = (maturity - start).days / 365.25
    maturity_value = principal * mpow(1 + rate / n, n * total_years)

    # Elapsed time
    elapsed_days = (min(today, maturity) - start).days
    elapsed_years = max(0, elapsed_days / 365.25)
    current_value = principal * mpow(1 + rate / n, n * elapsed_years)

    days_remaining = max(0, (maturity - today).days)

    return {
        'current_value': round(current_value, 2),
        'maturity_value': round(maturity_value, 2),
        'interest_earned': round(current_value - principal, 2),
        'days_remaining': days_remaining,
        'matured': today >= maturity,
    }


@app.route('/api/investments/prices', methods=['GET'])
@login_required
def api_investment_prices():
    accounts = load_accounts()
    results = []
    for acct in accounts:
        if acct.get('type') != 'investment':
            continue

        subtype = acct.get('subtype', 'market')

        if subtype == 'fd':
            fd_data = calculate_fd_value(
                acct.get('balance', 0),
                acct.get('interest_rate', 0),
                acct.get('start_date', ''),
                acct.get('maturity_date', ''),
                acct.get('compounding', 'quarterly')
            )
            results.append({
                'id': acct['id'],
                'name': acct['name'],
                'subtype': 'fd',
                'principal': acct.get('balance', 0),
                'interest_rate': acct.get('interest_rate', 0),
                'start_date': acct.get('start_date', ''),
                'maturity_date': acct.get('maturity_date', ''),
                'compounding': acct.get('compounding', 'quarterly'),
                'current_value': fd_data['current_value'] if fd_data else None,
                'maturity_value': fd_data['maturity_value'] if fd_data else None,
                'interest_earned': fd_data['interest_earned'] if fd_data else None,
                'days_remaining': fd_data['days_remaining'] if fd_data else None,
                'matured': fd_data['matured'] if fd_data else False,
                'invested': acct.get('balance', 0),
                'pnl': fd_data['interest_earned'] if fd_data else None,
                'pnl_pct': round((fd_data['interest_earned'] / acct.get('balance', 1)) * 100, 2) if fd_data and fd_data['interest_earned'] else None,
            })
        else:
            ticker = acct.get('ticker')
            if not ticker:
                continue
            price = fetch_yahoo_price(ticker)
            units = acct.get('units', 0)
            invested = acct.get('balance', 0)
            current_value = round(units * price, 2) if price else None
            pnl = round(current_value - invested, 2) if current_value else None
            pnl_pct = round((pnl / invested) * 100, 2) if pnl is not None and invested > 0 else None
            results.append({
                'id': acct['id'],
                'name': acct['name'],
                'subtype': 'market',
                'ticker': ticker,
                'units': units,
                'invested': invested,
                'price': price,
                'current_value': current_value,
                'pnl': pnl,
                'pnl_pct': pnl_pct,
            })
    return jsonify(results)


# ── CSV Export ────────────────────────────────────────────────────────────────

@app.route('/api/export/csv', methods=['GET'])
@login_required
def api_export_csv():
    import csv
    import io
    transactions = get_all_transactions()
    parents_only = request.args.get('parents_only', 'false') == 'true'
    if parents_only:
        transactions = [t for t in transactions if not t['parent_id']]

    # Optional filters
    account = request.args.get('account', '')
    category = request.args.get('category', '')
    txn_type = request.args.get('type', '')
    date_from = request.args.get('from', '')
    date_to = request.args.get('to', '')

    if account:
        transactions = [t for t in transactions if t['account'] == account]
    if category:
        transactions = [t for t in transactions if t['category'] == category]
    if txn_type:
        transactions = [t for t in transactions if t['type'] == txn_type]
    if date_from:
        transactions = [t for t in transactions if t['date'] >= date_from]
    if date_to:
        transactions = [t for t in transactions if t['date'] <= date_to]

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date', 'ID', 'Description', 'Category', 'Sub-Category', 'Account', 'Amount', 'Type', 'Track', 'Units', 'Parent ID'])
    for t in transactions:
        writer.writerow([
            t['date'], t['id'], t['description'], t['category'],
            t.get('sub_category', ''), t['account'], t['amount'],
            t['type'], 'Yes' if t.get('track', True) else 'No',
            t.get('units', ''), t.get('parent_id', '')
        ])

    today_str = date.today().strftime('%Y-%m-%d')
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=expenses_{today_str}.csv'}
    )


# ── Undo (transaction history) ───────────────────────────────────────────────

UNDO_STACK = []  # In-memory stack of deleted/edited transactions for undo
MAX_UNDO = 20


@app.route('/api/undo/delete', methods=['POST'])
@login_required
def api_undo_delete():
    """Store transaction data before deletion for potential undo."""
    data = request.get_json()
    txn_id = data.get('txn_id')
    txn = get_transaction_by_id(txn_id)
    if not txn:
        return jsonify({'success': False, 'error': 'Transaction not found'}), 404

    # Get children too
    all_txns = get_all_transactions()
    children = [t for t in all_txns if t.get('parent_id') == txn_id]

    UNDO_STACK.append({
        'action': 'delete',
        'transaction': txn,
        'children': children,
        'timestamp': datetime.now().isoformat()
    })
    if len(UNDO_STACK) > MAX_UNDO:
        UNDO_STACK.pop(0)

    return jsonify({'success': True, 'undo_available': len(UNDO_STACK)})


@app.route('/api/undo', methods=['POST'])
@login_required
def api_undo():
    """Undo the last delete operation by re-adding the transaction."""
    if not UNDO_STACK:
        return jsonify({'success': False, 'error': 'Nothing to undo'}), 400

    entry = UNDO_STACK.pop()

    if entry['action'] == 'delete':
        txn = entry['transaction']
        try:
            new_id = add_transaction(
                date_str=txn['date'],
                description=txn['description'],
                category=txn['category'],
                sub_category=txn.get('sub_category', ''),
                account=txn['account'],
                amount=txn['amount'],
                parent_id=txn.get('parent_id'),
                txn_type=txn.get('type', 'Expense'),
                track=txn.get('track', True),
                units=txn.get('units')
            )
            # Re-add children
            for child in entry.get('children', []):
                add_transaction(
                    date_str=child['date'],
                    description=child['description'],
                    category=child['category'],
                    sub_category=child.get('sub_category', ''),
                    account=child['account'],
                    amount=child['amount'],
                    parent_id=new_id,
                    txn_type=child.get('type', 'Expense'),
                    track=child.get('track', True),
                    units=child.get('units')
                )
            return jsonify({'success': True, 'new_id': new_id, 'undo_remaining': len(UNDO_STACK)})
        except Exception as e:
            return jsonify({'success': False, 'error': 'Operation failed'}), 400

    return jsonify({'success': False, 'error': 'Unknown undo action'}), 400


@app.route('/api/undo/status', methods=['GET'])
@login_required
def api_undo_status():
    return jsonify({'available': len(UNDO_STACK), 'items': [{'action': e['action'], 'description': e['transaction']['description'], 'timestamp': e['timestamp']} for e in reversed(UNDO_STACK)]})


# ── PWA ──────────────────────────────────────────────────────────────────────

@app.route('/manifest.json')
def pwa_manifest():
    manifest = {
        'name': 'Expense Manager',
        'short_name': 'ExpenseManager',
        'description': 'Personal expense tracker with multi-account support',
        'start_url': '/',
        'display': 'standalone',
        'background_color': '#0d1117',
        'theme_color': '#0d1117',
        'orientation': 'portrait',
        'icons': [
            {'src': '/static/icon-192.png', 'sizes': '192x192', 'type': 'image/png', 'purpose': 'any maskable'},
            {'src': '/static/icon-512.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any maskable'}
        ]
    }
    return jsonify(manifest)


@app.route('/sw.js')
def service_worker():
    sw_path = os.path.join(app.static_folder, 'sw.js')
    with open(sw_path, 'r') as f:
        return Response(f.read(), mimetype='application/javascript',
                       headers={'Service-Worker-Allowed': '/', 'Cache-Control': 'no-cache'})


if __name__ == '__main__':
    host = os.environ.get('HOST', '0.0.0.0')
    port = int(os.environ.get('PORT', 5000))
    app.run(host=host, port=port, debug=False)
