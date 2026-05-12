from flask import Flask, render_template, request, jsonify, redirect, url_for, session, Response
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_wtf.csrf import CSRFProtect
from dotenv import load_dotenv
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import bcrypt
import json
import os
import secrets
import hmac
import threading
import urllib.request
import urllib.error
from spreadsheet import (
    get_all_transactions, add_transaction, get_transaction_by_id,
    get_monthly_summary, update_transaction, delete_transaction,
    rename_account_in_sheets, compute_account_balances, compute_emi_schedule,
    _accounts_lock
)
from datetime import date, datetime, timedelta

load_dotenv()

app = Flask(__name__)

# Persist secret key: check env, then .env file, then generate and save
def _get_or_create_secret_key():
    # Check environment variable first
    key = os.environ.get('SECRET_KEY')
    if key:
        return key
    # Check .env file
    env_file = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_file):
        with open(env_file, 'r') as f:
            for line in f:
                if line.strip().startswith('SECRET_KEY='):
                    return line.strip().split('=', 1)[1]
    # Check data/ folder (writable in Docker)
    data_env = os.path.join(os.path.dirname(__file__), 'data', '.secret_key')
    if os.path.exists(data_env):
        with open(data_env, 'r') as f:
            return f.read().strip()
    # Generate and persist to the first writable location
    key = os.urandom(32).hex()
    for path in [env_file, data_env]:
        try:
            os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
            with open(path, 'a') as f:
                if path == env_file:
                    f.write(f"\nSECRET_KEY={key}\n")
                else:
                    f.write(key)
            return key
        except PermissionError:
            continue
    # Fallback: in-memory only (sessions reset on restart)
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
DRAFTS_FILE = os.path.join(DATA_DIR, 'drafts.json')
EMAIL_CONFIG_FILE = os.path.join(DATA_DIR, 'email_config.json')
PIPELINE_LOG_FILE = os.path.join(DATA_DIR, 'pipeline_log.json')

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


def save_auth(username, password_hash, extra=None):
    os.makedirs(DATA_DIR, exist_ok=True)
    data = {'username': username, 'password_hash': password_hash}
    # Preserve existing extra fields
    existing = load_auth()
    if existing:
        for k, v in existing.items():
            if k not in data:
                data[k] = v
    if extra:
        data.update(extra)
    _atomic_json_write(AUTH_FILE, data)
    os.chmod(AUTH_FILE, 0o600)


def get_nw_goal():
    """Get net worth goal increment. Returns (increment, increment). Milestone is computed client-side."""
    auth = load_auth()
    if not auth:
        return 500000, 500000
    increment = auth.get('nw_goal_increment', 500000)
    return increment, increment


def compute_nw_milestone(net_worth, increment):
    """Calculate the current milestone based on net worth and increment."""
    if increment <= 0:
        return 500000
    if net_worth <= 0:
        return increment
    import math
    milestone = math.ceil(net_worth / increment) * increment
    # If exactly at a milestone, target the next one
    if net_worth > 0 and net_worth == milestone:
        milestone += increment
    return milestone


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
            app.logger.info("Login success: %s from %s", username, request.remote_addr)
            next_page = request.args.get('next', '')
            # Only allow relative paths to prevent open redirect attacks
            if not next_page or not next_page.startswith('/') or next_page.startswith('//') or '\\' in next_page or ':' in next_page:
                next_page = url_for('dashboard')
            return redirect(next_page)
        else:
            app.logger.warning("Login failed: user=%s from %s", username, request.remote_addr)
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

            # Parse net worth goal increment
            try:
                nw_increment = float(request.form.get('nw_goal_increment', 500000) or 500000)
            except (ValueError, TypeError):
                nw_increment = 500000
            if nw_increment < 10000:
                nw_increment = 500000

            # Save auth with goal config
            save_auth(username, pw_hash, extra={'nw_goal_increment': nw_increment})

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
                try:
                    secret_key = os.urandom(32).hex()
                    with open(env_file, 'w') as f:
                        f.write("# Expense Manager Configuration\n\n")
                        f.write("HOST=0.0.0.0\n")
                        f.write("PORT=5000\n\n")
                        f.write(f"SECRET_KEY={secret_key}\n")
                except PermissionError:
                    pass  # In Docker, .env is read-only; secret key handled by _get_or_create_secret_key()

            return redirect(url_for('login'))

    return render_template('setup.html', error=error)


@app.route('/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


# ── Categories ────────────────────────────────────────────────────────────────

def load_categories():
    if not os.path.exists(CATEGORIES_FILE):
        return {}
    try:
        with open(CATEGORIES_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        app.logger.error("Corrupt categories.json — returning empty")
        return {}

def save_categories(data):
    _atomic_json_write(CATEGORIES_FILE, data)


# ── Accounts ──────────────────────────────────────────────────────────────────

def load_accounts():
    if not os.path.exists(ACCOUNTS_FILE):
        return []
    try:
        with open(ACCOUNTS_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        app.logger.error("Corrupt accounts.json — returning empty")
        return []

def save_accounts(data):
    _atomic_json_write(ACCOUNTS_FILE, data)


# ── Draft helpers ────────────────────────────────────────────────────────────

_drafts_lock = threading.Lock()

def load_drafts():
    if not os.path.exists(DRAFTS_FILE):
        return []
    try:
        with open(DRAFTS_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        app.logger.error("Corrupt drafts.json — returning empty")
        return []

def _atomic_json_write(filepath, data):
    """Write JSON atomically: write to temp file, then rename."""
    import tempfile
    os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(filepath), suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, filepath)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

def save_drafts(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    # Prune accepted/rejected drafts older than 30 days
    cutoff = (datetime.now() - timedelta(days=30)).isoformat()
    data = [d for d in data if d.get('status') == 'pending' or d.get('created_at', '') > cutoff]
    _atomic_json_write(DRAFTS_FILE, data)

def get_next_draft_id(drafts=None):
    if drafts is None:
        drafts = load_drafts()
    if not drafts:
        return 1
    return max(d.get('id', 0) for d in drafts) + 1

def draft_fingerprint(amount, date_str, merchant):
    return f"{amount}|{date_str}|{merchant.lower().strip()}"


# ── Email config helpers ─────────────────────────────────────────────────────

def load_email_config():
    if not os.path.exists(EMAIL_CONFIG_FILE):
        return None
    try:
        with open(EMAIL_CONFIG_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None

def save_email_config(config):
    _atomic_json_write(EMAIL_CONFIG_FILE, config)

def get_default_email_config():
    return {
        'enabled': False,
        'llm_url': '',
        'system_prompt': '',
        'account_mapping': {},
        'api_key': secrets.token_urlsafe(32),
        'app_url': 'http://localhost:5000'
    }


# ── Pipeline log helpers ─────────────────────────────────────────────────────

_pipeline_lock = threading.Lock()
MAX_PIPELINE_LOG = 500  # Keep last 500 entries

def load_pipeline_log():
    if not os.path.exists(PIPELINE_LOG_FILE):
        return []
    try:
        with open(PIPELINE_LOG_FILE, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []

def save_pipeline_log(entries):
    # Keep only last MAX_PIPELINE_LOG entries
    entries = entries[-MAX_PIPELINE_LOG:]
    _atomic_json_write(PIPELINE_LOG_FILE, entries)

def log_pipeline_event(status, source, email_preview='', parsed=None, error=None, draft_id=None):
    """Log an email parsing attempt to the pipeline history."""
    with _pipeline_lock:
        entries = load_pipeline_log()
        entry = {
            'id': (max((e.get('id', 0) for e in entries), default=0) + 1),
            'timestamp': datetime.now().isoformat(timespec='seconds'),
            'status': status,  # success, failed, skipped, duplicate
            'source': source,  # webhook, paste
            'email_preview': email_preview[:200] if email_preview else '',
            'parsed': parsed,
            'error': error,
            'draft_id': draft_id
        }
        entries.append(entry)
        save_pipeline_log(entries)
    return entry


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
    draft_count = len([d for d in load_drafts() if d.get('status') == 'pending'])
    email_config = load_email_config()
    llm_enabled = bool(email_config and email_config.get('enabled') and email_config.get('llm_url'))
    return render_template('manage.html', categories=categories, accounts=accounts, today=today, parent=parent, parents=parents, children=children, draft_count=draft_count, llm_enabled=llm_enabled)


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
    nw_increment, _ = get_nw_goal()
    email_config = load_email_config()
    show_email_setup = not email_config or not email_config.get('enabled')
    return render_template('dashboard.html', summary=summary, accounts=accounts, balances=balances, nw_goal_increment=nw_increment, show_email_setup=show_email_setup)


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
    if not data:
        return jsonify({'success': False, 'error': 'Invalid request body'}), 400
    txn_type = data.get('type', 'Expense')
    if txn_type not in ('Expense', 'Income', 'Transfer'):
        return jsonify({'success': False, 'error': 'Type must be Expense, Income, or Transfer'}), 400
    if not data.get('description', '').strip():
        return jsonify({'success': False, 'error': 'Description is required'}), 400
    try:
        amount = float(data['amount'])
    except (KeyError, TypeError, ValueError):
        return jsonify({'success': False, 'error': 'Valid amount is required'}), 400
    if amount <= 0:
        return jsonify({'success': False, 'error': 'Amount must be positive'}), 400
    try:
        units = float(data['units']) if data.get('units') else None
        emi_id = int(data['emi_id']) if data.get('emi_id') else None
        txn_id = add_transaction(
            date_str=data['date'],
            description=data['description'],
            category=data['category'],
            sub_category=data.get('sub_category', ''),
            account=data['account'],
            amount=amount,
            parent_id=data.get('parent_id') or None,
            txn_type=txn_type,
            track=data.get('track', True),
            units=units,
            emi_id=emi_id
        )
        app.logger.info("Transaction created: id=%s desc='%s' amount=%.2f account='%s' type=%s", txn_id, data['description'], float(data['amount']), data['account'], txn_type)
        return jsonify({'success': True, 'id': txn_id})
    except KeyError as e:
        app.logger.error("Transaction create failed: missing field %s", e)
        return jsonify({'success': False, 'error': f'Missing required field: {e}'}), 400
    except (ValueError, TypeError) as e:
        app.logger.error("Transaction create failed: %s | data=%s", e, {k: v for k, v in data.items() if k != 'csrf_token'})
        return jsonify({'success': False, 'error': 'Invalid field value — check date format and numeric fields'}), 400
    except Exception as e:
        app.logger.error("Transaction create failed: %s | data=%s", e, {k: v for k, v in data.items() if k != 'csrf_token'})
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
    if not data:
        return jsonify({'success': False, 'error': 'Invalid request body'}), 400
    txn_type = data.get('type', 'Expense')
    if txn_type not in ('Expense', 'Income', 'Transfer'):
        return jsonify({'success': False, 'error': 'Type must be Expense, Income, or Transfer'}), 400
    if 'amount' in data:
        try:
            if float(data['amount']) <= 0:
                return jsonify({'success': False, 'error': 'Amount must be positive'}), 400
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'Valid amount is required'}), 400
    try:
        updated = update_transaction(txn_id, data)
        app.logger.info("Transaction updated: id=%s", txn_id)
        return jsonify({'success': True, 'transaction': updated})
    except Exception as e:
        app.logger.error("Transaction update failed: id=%s error=%s", txn_id, e)
        return jsonify({'success': False, 'error': 'Operation failed'}), 400


@app.route('/api/transactions/<int:txn_id>', methods=['DELETE'])
@login_required
def api_delete_transaction(txn_id):
    try:
        deleted_ids = delete_transaction(txn_id)
        app.logger.info("Transaction deleted: id=%s (cascade: %s)", txn_id, deleted_ids)
        return jsonify({'success': True, 'deleted_ids': deleted_ids})
    except ValueError as e:
        app.logger.error("Transaction delete failed: id=%s error=%s", txn_id, e)
        return jsonify({'success': False, 'error': 'Operation failed'}), 404


@app.route('/api/transactions/<int:txn_id>/track', methods=['PATCH'])
@login_required
def api_toggle_track(txn_id):
    data = request.get_json(silent=True) or {}
    track = data.get('track', True)
    try:
        txn = get_transaction_by_id(txn_id)
        if not txn:
            return jsonify({'success': False, 'error': 'Transaction not found'}), 404
        # Only update the track field to avoid rewriting all cells
        minimal = {'date': txn['date'], 'description': txn['description'], 'category': txn['category'],
                   'sub_category': txn.get('sub_category', ''), 'account': txn['account'],
                   'amount': txn['amount'], 'type': txn.get('type', 'Expense'), 'track': track,
                   'units': txn.get('units')}
        updated = update_transaction(txn_id, minimal)
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

    name = data.get('name', '').strip()
    acct_type = data.get('type', '').strip()

    if not name:
        return jsonify({'success': False, 'error': 'Account name required'}), 400
    if acct_type not in ('savings', 'credit', 'investment', 'emi'):
        return jsonify({'success': False, 'error': 'Type must be savings, credit, investment, or emi'}), 400

    with _accounts_lock:
        accounts = load_accounts()
        if any(a['name'] == name for a in accounts):
            return jsonify({'success': False, 'error': 'Account name already exists'}), 400

        new_id = max((a['id'] for a in accounts), default=0) + 1
        new_account = {'id': new_id, 'name': name, 'type': acct_type}

        try:
            if acct_type == 'savings':
                new_account['balance'] = float(data.get('balance', 0))
            elif acct_type == 'credit':
                new_account['limit'] = float(data.get('limit', 0))
                if 'billing_date' in data and data['billing_date']:
                    new_account['billing_date'] = int(data['billing_date'])
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
            elif acct_type == 'emi':
                new_account['principal'] = float(data.get('principal', 0))
                new_account['interest_rate'] = float(data.get('interest_rate', 0))
                new_account['tenure_months'] = int(data.get('tenure_months', 0))
                new_account['booking_date'] = data.get('booking_date', '')
                new_account['first_installment_date'] = data.get('first_installment_date', '')
                linked = data.get('linked_account_id')
                if linked:
                    new_account['linked_account_id'] = int(linked)
                if new_account['principal'] <= 0 or new_account['tenure_months'] <= 0:
                    return jsonify({'success': False, 'error': 'Principal and tenure must be positive'}), 400
                if not new_account['first_installment_date']:
                    return jsonify({'success': False, 'error': 'First installment date is required'}), 400
        except (ValueError, TypeError) as e:
            return jsonify({'success': False, 'error': 'Invalid numeric value in account fields'}), 400

        accounts.append(new_account)
        save_accounts(accounts)
    return jsonify({'success': True, 'account': new_account})


@app.route('/api/accounts/<int:account_id>', methods=['PUT'])
@login_required
def api_update_account(account_id):
    data = request.get_json()

    new_name = data.get('name', '').strip()
    if not new_name:
        return jsonify({'success': False, 'error': 'Account name required'}), 400

    with _accounts_lock:
        accounts = load_accounts()
        acct = next((a for a in accounts if a['id'] == account_id), None)
        if not acct:
            return jsonify({'success': False, 'error': 'Account not found'}), 404

        if any(a['name'] == new_name and a['id'] != account_id for a in accounts):
            return jsonify({'success': False, 'error': 'Account name already exists'}), 400

        old_name = acct['name']

        try:
            acct['name'] = new_name
            if acct['type'] == 'savings':
                acct['balance'] = float(data.get('balance', acct.get('balance', 0)))
            elif acct['type'] == 'credit':
                acct['limit'] = float(data.get('limit', acct.get('limit', 0)))
                if 'billing_date' in data and data['billing_date']:
                    acct['billing_date'] = int(data['billing_date'])
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
            elif acct['type'] == 'emi':
                acct['principal'] = float(data.get('principal', acct.get('principal', 0)))
                acct['interest_rate'] = float(data.get('interest_rate', acct.get('interest_rate', 0)))
                acct['tenure_months'] = int(data.get('tenure_months', acct.get('tenure_months', 0)))
                acct['booking_date'] = data.get('booking_date', acct.get('booking_date', ''))
                acct['first_installment_date'] = data.get('first_installment_date', acct.get('first_installment_date', ''))
                if 'linked_account_id' in data:
                    linked = data.get('linked_account_id')
                    if linked:
                        acct['linked_account_id'] = int(linked)
                    else:
                        acct.pop('linked_account_id', None)
        except (ValueError, TypeError):
            return jsonify({'success': False, 'error': 'Invalid numeric value in account fields'}), 400

        save_accounts(accounts)

        if old_name != new_name:
            rename_account_in_sheets(old_name, new_name)

    return jsonify({'success': True, 'account': acct})


@app.route('/api/accounts/<int:account_id>', methods=['DELETE'])
@login_required
def api_delete_account(account_id):
    with _accounts_lock:
        accounts = load_accounts()
        acct = next((a for a in accounts if a['id'] == account_id), None)
        if not acct:
            return jsonify({'success': False, 'error': 'Account not found'}), 404

        transactions = get_all_transactions()
        if acct['type'] == 'emi':
            in_use = any(t.get('emi_id') == account_id for t in transactions)
            if in_use:
                return jsonify({'success': False, 'error': 'Cannot delete — installments reference this EMI'}), 400
        else:
            in_use = any(t['account'] == acct['name'] for t in transactions)
            if in_use:
                return jsonify({'success': False, 'error': 'Cannot delete — transactions use this account'}), 400

        accounts = [a for a in accounts if a['id'] != account_id]
        save_accounts(accounts)
    return jsonify({'success': True})


@app.route('/api/accounts/<int:account_id>/schedule', methods=['GET'])
@login_required
def api_account_schedule(account_id):
    """Return the full EMI schedule for an EMI account with paid/upcoming flags."""
    accounts = load_accounts()
    acct = next((a for a in accounts if a['id'] == account_id), None)
    if not acct or acct.get('type') != 'emi':
        return jsonify({'success': False, 'error': 'EMI account not found'}), 404

    schedule = compute_emi_schedule(
        acct.get('principal', 0),
        acct.get('interest_rate', 0),
        acct.get('tenure_months', 0),
        acct.get('first_installment_date', ''),
    )

    # Mark paid installments by finding transactions with matching emi_id, date-sorted
    paid_txns = sorted(
        [t for t in get_all_transactions() if not t['parent_id'] and t.get('emi_id') == account_id],
        key=lambda t: t['date']
    )
    for i, row in enumerate(schedule):
        if i < len(paid_txns):
            row['paid'] = True
            row['paid_txn_id'] = paid_txns[i]['id']
            row['paid_date'] = paid_txns[i]['date']
        else:
            row['paid'] = False
    return jsonify({'success': True, 'schedule': schedule, 'account': acct})


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
    except Exception as e:
        app.logger.warning("Yahoo Finance fetch failed for %s: %s", ticker, e)
        return None


# ── USD-INR historical rate (for ICICI/USD card transactions) ───────────────

_fx_cache = {}  # {date_str: rate}

def fetch_usd_inr_rate(date_str):
    """Fetch USD-INR close rate on/near the given date via Yahoo Finance.
    Returns float or None. Results cached for the process lifetime."""
    if not date_str:
        return None
    if date_str in _fx_cache:
        return _fx_cache[date_str]
    try:
        target = datetime.strptime(date_str, '%Y-%m-%d').date()
        target_dt = datetime.combine(target, datetime.min.time())
        period1 = int((target_dt - timedelta(days=7)).timestamp())
        period2 = int((target_dt + timedelta(days=2)).timestamp())
        url = f'https://query1.finance.yahoo.com/v8/finance/chart/USDINR=X?period1={period1}&period2={period2}&interval=1d'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        result = data['chart']['result'][0]
        ts_list = result.get('timestamp', []) or []
        closes = result.get('indicators', {}).get('quote', [{}])[0].get('close', []) or []
        target_ts = target_dt.timestamp() + 86400  # allow same-day match
        best = None
        for t, c in zip(ts_list, closes):
            if c is None:
                continue
            if t <= target_ts:
                best = c
        if best is None:
            best = next((c for c in closes if c is not None), None)
        if best:
            _fx_cache[date_str] = best
            return best
    except Exception as e:
        app.logger.warning("USD-INR rate fetch failed for %s: %s", date_str, e)
    return None


def apply_currency_conversion(parsed):
    """If parsed['currency'] is non-INR, convert amount to INR using Yahoo rate
    for parsed['date']. Adds original_amount/original_currency/fx_rate fields.
    Mutates and returns the dict. No-op for INR or None."""
    if not parsed:
        return parsed
    cur = parsed.get('currency', 'INR')
    if cur == 'INR':
        return parsed
    if cur == 'USD':
        rate = fetch_usd_inr_rate(parsed.get('date'))
        if rate:
            parsed['original_amount'] = parsed['amount']
            parsed['original_currency'] = 'USD'
            parsed['fx_rate'] = round(rate, 4)
            parsed['amount'] = round(parsed['amount'] * rate, 2)
            parsed['currency'] = 'INR'
            app.logger.info("FX convert: USD %.2f -> INR %.2f (rate %.4f on %s)",
                            parsed['original_amount'], parsed['amount'], rate, parsed['date'])
        else:
            app.logger.warning("USD-INR rate unavailable for %s; keeping raw USD amount", parsed.get('date'))
    return parsed


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


@app.route('/api/settings/nw-goal', methods=['PUT'])
@login_required
def api_update_nw_goal():
    data = request.get_json()
    try:
        increment = float(data.get('increment', 500000))
    except (ValueError, TypeError):
        return jsonify({'success': False, 'error': 'Invalid increment value'}), 400
    if increment < 10000:
        return jsonify({'success': False, 'error': 'Minimum increment is ₹10,000'}), 400
    auth = load_auth()
    if auth:
        auth['nw_goal_increment'] = increment
        _atomic_json_write(AUTH_FILE, auth)
        os.chmod(AUTH_FILE, 0o600)
    return jsonify({'success': True, 'increment': increment})


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
    def strip_sanitize_prefix(s):
        """Remove the single-quote prefix added by sanitize_cell for CSV export, keeping formula injection protection."""
        if isinstance(s, str) and s.startswith("'") and len(s) > 1 and s[1] in ('=', '+', '-', '@', '|', '\t'):
            # Strip the quote but re-prefix with a space to prevent CSV formula injection
            return ' ' + s[1:]
        return s

    for t in transactions:
        writer.writerow([
            t['date'], t['id'], strip_sanitize_prefix(t['description']),
            strip_sanitize_prefix(t['category']),
            strip_sanitize_prefix(t.get('sub_category', '')),
            strip_sanitize_prefix(t['account']), t['amount'],
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
_undo_lock = threading.Lock()


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

    with _undo_lock:
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
    with _undo_lock:
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


# ── API: Drafts (Email-to-Expense pipeline) ─────────────────────────────────

@app.route('/api/drafts/ingest', methods=['POST'])
@csrf.exempt
@limiter.limit("30 per minute")
def api_ingest_draft():
    """Accept raw email HTML from watcher or webhook. CSRF-exempt, API-key auth."""
    config = load_email_config()
    if not config or not config.get('enabled'):
        log_pipeline_event('failed', 'webhook', error='Email integration not enabled')
        return jsonify({'success': False, 'error': 'Email integration not enabled'}), 400

    # Validate API key (timing-safe comparison)
    api_key = request.headers.get('X-API-Key', '')
    if not api_key or not hmac.compare_digest(api_key, config.get('api_key', '')):
        app.logger.warning("Draft ingest: invalid API key from %s", request.remote_addr)
        log_pipeline_event('failed', 'webhook', error='Invalid API key')
        return jsonify({'success': False, 'error': 'Invalid API key'}), 401

    data = request.get_json(silent=True) or {}
    html = data.get('html', '')
    if not html:
        log_pipeline_event('failed', 'webhook', error='No HTML content provided')
        return jsonify({'success': False, 'error': 'No HTML content provided'}), 400

    app.logger.info("Draft ingest: received email from %s (%d bytes)", request.remote_addr, len(html))

    from email_parser import strip_email_html, parse_with_llm, build_default_prompt

    # Strip HTML to get transaction text
    email_text = strip_email_html(html)
    if not email_text:
        app.logger.info("Draft ingest: skipped (non-transaction/promotional email)")
        log_pipeline_event('skipped', 'webhook', email_preview=html[:200], error='Non-transaction/promotional email')
        return jsonify({'success': True, 'skipped': True, 'reason': 'Non-transaction email'}), 200

    # Build prompt
    system_prompt = config.get('system_prompt', '').strip()
    if not system_prompt:
        system_prompt = build_default_prompt(config.get('account_mapping', {}))

    # Parse with LLM
    llm_url = config.get('llm_url', '')
    if not llm_url:
        log_pipeline_event('failed', 'webhook', email_preview=email_text, error='LLM URL not configured')
        return jsonify({'success': False, 'error': 'LLM URL not configured'}), 400

    parsed = parse_with_llm(email_text, llm_url, system_prompt)
    if not parsed:
        app.logger.error("Draft ingest: LLM failed to parse email text: %s", email_text[:100])
        log_pipeline_event('failed', 'webhook', email_preview=email_text, error='LLM failed to parse email')
        return jsonify({'success': False, 'error': 'Failed to parse email'}), 422

    apply_currency_conversion(parsed)

    app.logger.info("Draft ingest: LLM parsed — merchant='%s' amount=%.2f date=%s account='%s'", parsed['merchant'], parsed['amount'], parsed['date'], parsed['account'])

    # Deduplication check
    fp = draft_fingerprint(parsed['amount'], parsed['date'], parsed['merchant'])
    with _drafts_lock:
        drafts = load_drafts()
        for d in drafts:
            if d.get('fingerprint') == fp:
                app.logger.info("Draft ingest: skipped (duplicate fingerprint: %s)", fp)
                log_pipeline_event('duplicate', 'webhook', email_preview=email_text, parsed=parsed)
                return jsonify({'success': True, 'skipped': True, 'reason': 'Duplicate'}), 200

        draft = {
            'id': get_next_draft_id(drafts),
            'amount': parsed['amount'],
            'merchant': parsed['merchant'],
            'date': parsed['date'],
            'account': parsed['account'],
            'category': parsed.get('category', 'Miscellaneous'),
            'sub_category': '',
            'type': parsed.get('type', 'Expense'),
            'status': 'pending',
            'raw_email_text': email_text[:500],
            'created_at': datetime.now().isoformat(),
            'fingerprint': fp
        }
        drafts.append(draft)
        save_drafts(drafts)

    app.logger.info("Draft created: id=%s merchant='%s' amount=%.2f", draft['id'], draft['merchant'], draft['amount'])
    log_pipeline_event('success', 'webhook', email_preview=email_text, parsed=parsed, draft_id=draft['id'])
    return jsonify({'success': True, 'draft_id': draft['id'], 'parsed': parsed})


@app.route('/api/drafts/paste', methods=['POST'])
@login_required
@limiter.limit("10 per minute")
def api_paste_draft():
    """Parse pasted email text via LLM and store as draft."""
    config = load_email_config()
    if not config or not config.get('enabled') or not config.get('llm_url'):
        log_pipeline_event('failed', 'paste', error='LLM not configured')
        return jsonify({'success': False, 'error': 'LLM not configured. Go to Settings to set up.'}), 400

    data = request.get_json(silent=True) or {}
    text = data.get('text', '').strip()
    if not text:
        return jsonify({'success': False, 'error': 'No text provided'}), 400

    from email_parser import strip_email_html, parse_with_llm, build_default_prompt

    # Try stripping HTML first (user may paste raw HTML)
    stripped = strip_email_html(text)
    email_text = stripped if stripped else text

    system_prompt = config.get('system_prompt', '').strip()
    if not system_prompt:
        system_prompt = build_default_prompt(config.get('account_mapping', {}))

    parsed = parse_with_llm(email_text, config['llm_url'], system_prompt)
    if not parsed:
        log_pipeline_event('failed', 'paste', email_preview=email_text, error='LLM failed to parse email')
        return jsonify({'success': False, 'error': 'Could not parse the email text. Check your LLM configuration.'}), 422

    apply_currency_conversion(parsed)

    fp = draft_fingerprint(parsed['amount'], parsed['date'], parsed['merchant'])
    with _drafts_lock:
        drafts = load_drafts()
        draft = {
            'id': get_next_draft_id(drafts),
            'amount': parsed['amount'],
            'merchant': parsed['merchant'],
            'date': parsed['date'],
            'account': parsed['account'],
            'category': parsed.get('category', 'Miscellaneous'),
            'sub_category': '',
            'type': parsed.get('type', 'Expense'),
            'status': 'pending',
            'raw_email_text': email_text[:500],
            'created_at': datetime.now().isoformat(),
            'fingerprint': fp
        }
        drafts.append(draft)
        save_drafts(drafts)

    log_pipeline_event('success', 'paste', email_preview=email_text, parsed=parsed, draft_id=draft['id'])
    return jsonify({'success': True, 'draft_id': draft['id'], 'draft': draft})


@app.route('/api/drafts', methods=['GET'])
@login_required
def api_get_drafts():
    """List pending drafts."""
    drafts = load_drafts()
    pending = [d for d in drafts if d.get('status') == 'pending']
    return jsonify(pending)


@app.route('/api/drafts/<int:draft_id>/accept', methods=['POST'])
@login_required
def api_accept_draft(draft_id):
    """Accept a draft and create a real transaction."""
    with _drafts_lock:
        drafts = load_drafts()
        draft = next((d for d in drafts if d['id'] == draft_id and d['status'] == 'pending'), None)
        if not draft:
            return jsonify({'success': False, 'error': 'Draft not found or already processed'}), 404

        try:
            txn_id = add_transaction(
                date_str=draft['date'],
                description=draft['merchant'],
                category=draft.get('category', 'Miscellaneous'),
                sub_category=draft.get('sub_category', ''),
                account=draft['account'],
                amount=draft['amount'],
                txn_type=draft.get('type', 'Expense')
            )
            draft['status'] = 'accepted'
            save_drafts(drafts)
            app.logger.info("Draft accepted: draft_id=%s → txn_id=%s merchant='%s' amount=%.2f", draft_id, txn_id, draft['merchant'], draft['amount'])
            return jsonify({'success': True, 'txn_id': txn_id})
        except Exception as e:
            app.logger.error("Draft accept failed: draft_id=%s error=%s", draft_id, e)
            return jsonify({'success': False, 'error': 'Failed to create transaction from draft'}), 400


@app.route('/api/drafts/<int:draft_id>/reject', methods=['POST'])
@login_required
def api_reject_draft(draft_id):
    """Reject/discard a draft."""
    with _drafts_lock:
        drafts = load_drafts()
        draft = next((d for d in drafts if d['id'] == draft_id and d['status'] == 'pending'), None)
        if not draft:
            return jsonify({'success': False, 'error': 'Draft not found'}), 404
        draft['status'] = 'rejected'
        save_drafts(drafts)
    app.logger.info("Draft rejected: draft_id=%s merchant='%s'", draft_id, draft.get('merchant', ''))
    return jsonify({'success': True})


@app.route('/api/drafts/<int:draft_id>', methods=['PUT'])
@login_required
def api_update_draft(draft_id):
    """Edit draft fields before accepting."""
    data = request.get_json(silent=True) or {}
    with _drafts_lock:
        drafts = load_drafts()
        draft = next((d for d in drafts if d['id'] == draft_id and d['status'] == 'pending'), None)
        if not draft:
            return jsonify({'success': False, 'error': 'Draft not found'}), 404

        for field in ('merchant', 'date', 'account', 'category', 'sub_category', 'type'):
            if field in data:
                draft[field] = data[field]

        # Validate and convert amount
        if 'amount' in data:
            try:
                draft['amount'] = float(data['amount'])
                if draft['amount'] <= 0:
                    return jsonify({'success': False, 'error': 'Amount must be positive'}), 400
            except (ValueError, TypeError):
                return jsonify({'success': False, 'error': 'Invalid amount'}), 400

        # Validate type
        if draft.get('type') not in ('Expense', 'Income', 'Transfer'):
            draft['type'] = 'Expense'

        # Update fingerprint if amount/date/merchant changed
        draft['fingerprint'] = draft_fingerprint(draft['amount'], draft['date'], draft['merchant'])
        save_drafts(drafts)
    return jsonify({'success': True, 'draft': draft})


@app.route('/api/drafts/accept-all', methods=['POST'])
@login_required
def api_accept_all_drafts():
    """Bulk accept all pending drafts."""
    with _drafts_lock:
        drafts = load_drafts()
        pending = [d for d in drafts if d['status'] == 'pending']
        if not pending:
            return jsonify({'success': True, 'count': 0, 'txn_ids': []})

        txn_ids = []
        for draft in pending:
            try:
                txn_id = add_transaction(
                    date_str=draft['date'],
                    description=draft['merchant'],
                    category=draft.get('category', 'Miscellaneous'),
                    sub_category=draft.get('sub_category', ''),
                    account=draft['account'],
                    amount=draft['amount'],
                    txn_type=draft.get('type', 'Expense')
                )
                draft['status'] = 'accepted'
                txn_ids.append(txn_id)
            except Exception as e:
                app.logger.warning("Failed to accept draft %s: %s", draft.get('id'), e)

        save_drafts(drafts)
    return jsonify({'success': True, 'count': len(txn_ids), 'txn_ids': txn_ids})


# ── Settings page ────────────────────────────────────────────────────────────

@app.route('/settings')
@login_required
def settings():
    config = load_email_config() or get_default_email_config()
    accounts = load_accounts()
    categories = load_categories()
    return render_template('settings.html', config=config, accounts=accounts, categories=categories)


@app.route('/download/n8n-workflow')
@login_required
def download_n8n_workflow():
    """Serve the n8n workflow template as a downloadable file."""
    from flask import send_from_directory
    return send_from_directory('static', 'n8n-email-workflow.json', as_attachment=True, download_name='n8n-email-workflow.json')


@app.route('/api/pipeline/history', methods=['GET'])
@login_required
def api_pipeline_history():
    """Return pipeline log entries, newest first."""
    entries = load_pipeline_log()
    entries.reverse()
    # Optional filtering
    status_filter = request.args.get('status')
    if status_filter:
        entries = [e for e in entries if e.get('status') == status_filter]
    limit = request.args.get('limit', 50, type=int)
    return jsonify(entries[:limit])


@app.route('/api/pipeline/retry/<int:log_id>', methods=['POST'])
@login_required
def api_pipeline_retry(log_id):
    """Retry a failed pipeline entry."""
    entries = load_pipeline_log()
    entry = next((e for e in entries if e.get('id') == log_id), None)
    if not entry:
        return jsonify({'success': False, 'error': 'Log entry not found'}), 404
    if entry.get('status') not in ('failed',):
        return jsonify({'success': False, 'error': 'Only failed entries can be retried'}), 400

    email_text = entry.get('email_preview', '')
    if not email_text:
        return jsonify({'success': False, 'error': 'No email text to retry'}), 400

    config = load_email_config()
    if not config or not config.get('enabled') or not config.get('llm_url'):
        return jsonify({'success': False, 'error': 'LLM not configured'}), 400

    from email_parser import parse_with_llm, build_default_prompt

    system_prompt = config.get('system_prompt', '').strip()
    if not system_prompt:
        system_prompt = build_default_prompt(config.get('account_mapping', {}))

    parsed = parse_with_llm(email_text, config['llm_url'], system_prompt)
    if not parsed:
        log_pipeline_event('failed', 'retry', email_preview=email_text, error='LLM failed to parse on retry')
        return jsonify({'success': False, 'error': 'LLM failed to parse again'}), 422

    apply_currency_conversion(parsed)

    fp = draft_fingerprint(parsed['amount'], parsed['date'], parsed['merchant'])
    with _drafts_lock:
        drafts = load_drafts()
        draft = {
            'id': get_next_draft_id(drafts),
            'amount': parsed['amount'],
            'merchant': parsed['merchant'],
            'date': parsed['date'],
            'account': parsed['account'],
            'category': parsed.get('category', 'Miscellaneous'),
            'sub_category': '',
            'type': parsed.get('type', 'Expense'),
            'status': 'pending',
            'raw_email_text': email_text[:500],
            'created_at': datetime.now().isoformat(),
            'fingerprint': fp
        }
        drafts.append(draft)
        save_drafts(drafts)

    log_pipeline_event('success', 'retry', email_preview=email_text, parsed=parsed, draft_id=draft['id'])
    app.logger.info("Pipeline retry success: log_id=%s → draft_id=%s", log_id, draft['id'])
    return jsonify({'success': True, 'draft_id': draft['id'], 'parsed': parsed})


@app.route('/api/pipeline/clear', methods=['POST'])
@login_required
def api_pipeline_clear():
    """Clear pipeline history."""
    with _pipeline_lock:
        save_pipeline_log([])
    return jsonify({'success': True})


@app.route('/api/settings/email', methods=['GET'])
@login_required
def api_get_email_config():
    config = load_email_config() or get_default_email_config()
    return jsonify(config)


@app.route('/api/settings/email', methods=['PUT'])
@login_required
def api_update_email_config():
    data = request.get_json(silent=True) or {}
    config = load_email_config() or get_default_email_config()

    # Update top-level fields
    for field in ('enabled', 'llm_url', 'system_prompt', 'account_mapping', 'app_url'):
        if field in data:
            config[field] = data[field]

    # Generate API key if missing
    if not config.get('api_key'):
        config['api_key'] = secrets.token_urlsafe(32)

    save_email_config(config)
    app.logger.info("Email settings updated: enabled=%s llm_url=%s", config.get('enabled'), config.get('llm_url', ''))
    return jsonify({'success': True})


@app.route('/api/settings/email/regenerate-key', methods=['POST'])
@login_required
def api_regenerate_api_key():
    config = load_email_config() or get_default_email_config()
    config['api_key'] = secrets.token_urlsafe(32)
    save_email_config(config)
    return jsonify({'success': True, 'api_key': config['api_key']})


@app.route('/api/settings/email/test-llm', methods=['POST'])
@login_required
def api_test_llm():
    """Test LLM connection server-side."""
    data = request.get_json(silent=True) or {}
    llm_url = data.get('llm_url', '').strip()
    if not llm_url:
        return jsonify({'success': False, 'error': 'Enter a URL first'}), 400

    url = llm_url.rstrip('/') + '/v1/models'
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            models = result.get('models', result.get('data', []))
            model_names = ', '.join(m.get('id', m.get('name', '')) for m in models) or 'unknown'
            return jsonify({'success': True, 'message': f'Connected! Models: {model_names}'})
    except urllib.error.URLError as e:
        return jsonify({'success': False, 'error': f'Connection failed: {str(e)}'}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error: {str(e)}'}), 400


@app.route('/api/settings/email/test-webhook', methods=['POST'])
@login_required
def api_test_webhook():
    """Test the full webhook pipeline: API key → HTML strip → LLM parse → draft creation."""
    data = request.get_json(silent=True) or {}
    html = data.get('html', '').strip()
    if not html:
        return jsonify({'success': False, 'error': 'Paste a sample bank email to test'}), 400

    config = load_email_config()
    if not config or not config.get('enabled'):
        return jsonify({'success': False, 'error': 'Enable LLM parsing in Settings first'}), 400
    if not config.get('llm_url'):
        return jsonify({'success': False, 'error': 'Set LLM URL first'}), 400
    if not config.get('api_key'):
        return jsonify({'success': False, 'error': 'No API key configured'}), 400

    from email_parser import strip_email_html, parse_with_llm, build_default_prompt

    # Step 1: Strip HTML
    email_text = strip_email_html(html)
    if not email_text:
        return jsonify({'success': False, 'error': 'Could not extract transaction text. This may be a promotional email.'}), 400

    # Step 2: Parse with LLM
    system_prompt = config.get('system_prompt', '').strip()
    if not system_prompt:
        system_prompt = build_default_prompt(config.get('account_mapping', {}))

    parsed = parse_with_llm(email_text, config['llm_url'], system_prompt)
    if not parsed:
        return jsonify({'success': False, 'error': 'LLM failed to parse the email. Check your LLM URL and prompt.'}), 422

    apply_currency_conversion(parsed)

    # Step 3: Create draft
    fp = draft_fingerprint(parsed['amount'], parsed['date'], parsed['merchant'])
    with _drafts_lock:
        drafts = load_drafts()
        draft = {
            'id': get_next_draft_id(drafts),
            'amount': parsed['amount'],
            'merchant': parsed['merchant'],
            'date': parsed['date'],
            'account': parsed['account'],
            'category': parsed.get('category', 'Miscellaneous'),
            'sub_category': '',
            'type': parsed.get('type', 'Expense'),
            'status': 'pending',
            'raw_email_text': email_text[:500],
            'created_at': datetime.now().isoformat(),
            'fingerprint': fp
        }
        drafts.append(draft)
        save_drafts(drafts)

    return jsonify({
        'success': True,
        'message': 'Full pipeline test passed! Draft created.',
        'parsed': parsed,
        'draft_id': draft['id'],
        'extracted_text': email_text
    })


@app.route('/api/settings/email/test-parse', methods=['POST'])
@login_required
def api_test_parse():
    """Test LLM parsing with sample email text."""
    data = request.get_json(silent=True) or {}
    text = data.get('text', '').strip()
    llm_url = data.get('llm_url', '').strip()
    system_prompt = data.get('system_prompt', '').strip()

    if not text:
        return jsonify({'success': False, 'error': 'No text provided'}), 400
    if not llm_url:
        return jsonify({'success': False, 'error': 'No LLM URL provided'}), 400

    from email_parser import strip_email_html, parse_with_llm, build_default_prompt

    # Try stripping HTML first
    stripped = strip_email_html(text)
    email_text = stripped if stripped else text

    if not system_prompt:
        config = load_email_config()
        mapping = config.get('account_mapping', {}) if config else {}
        system_prompt = build_default_prompt(mapping)

    parsed = parse_with_llm(email_text, llm_url, system_prompt)
    if parsed:
        apply_currency_conversion(parsed)
        return jsonify({'success': True, 'parsed': parsed, 'extracted_text': email_text})
    else:
        return jsonify({'success': False, 'error': 'LLM failed to parse. Check URL and prompt.'}), 422


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
    if not os.path.exists(sw_path):
        return Response('// sw.js not found', mimetype='application/javascript', status=404)
    with open(sw_path, 'r') as f:
        return Response(f.read(), mimetype='application/javascript',
                       headers={'Service-Worker-Allowed': '/', 'Cache-Control': 'no-cache'})


if __name__ == '__main__':
    host = os.environ.get('HOST', '0.0.0.0')
    port = int(os.environ.get('PORT', 5000))
    app.run(host=host, port=port, debug=False)
