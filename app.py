from flask import Flask, render_template, request, jsonify, redirect, url_for
import json
import os
from spreadsheet import (
    get_all_transactions, add_transaction, get_transaction_by_id,
    get_monthly_summary, get_header_info, ensure_month_sheet
)
from datetime import date

app = Flask(__name__)

CATEGORIES_FILE = os.path.join(os.path.dirname(__file__), 'categories.json')

def load_categories():
    with open(CATEGORIES_FILE, 'r') as f:
        return json.load(f)

def save_categories(data):
    with open(CATEGORIES_FILE, 'w') as f:
        json.dump(data, f, indent=2)


# ── Pages ──────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return redirect(url_for('add_expense'))


@app.route('/add')
def add_expense():
    categories = load_categories()
    today = date.today().strftime('%Y-%m-%d')
    return render_template('add.html', categories=categories, today=today, parent=None)


@app.route('/add/sub/<int:parent_id>')
def add_sub_expense(parent_id):
    categories = load_categories()
    today = date.today().strftime('%Y-%m-%d')
    parent = get_transaction_by_id(parent_id)
    if not parent:
        return redirect(url_for('add_expense'))
    return render_template('add.html', categories=categories, today=today, parent=parent)


@app.route('/expenses')
def expenses():
    transactions = get_all_transactions()
    # Group sub-items under parents
    parents = [t for t in transactions if not t['parent_id']]
    children = {}
    for t in transactions:
        if t['parent_id']:
            children.setdefault(t['parent_id'], []).append(t)
    return render_template('expenses.html', parents=parents, children=children)


@app.route('/dashboard')
def dashboard():
    summary = get_monthly_summary()
    return render_template('dashboard.html', summary=json.dumps(summary))


# ── API ────────────────────────────────────────────────────────────────────────

@app.route('/api/transactions', methods=['POST'])
def api_add_transaction():
    data = request.get_json()
    try:
        txn_id = add_transaction(
            date_str=data['date'],
            description=data['description'],
            category=data['category'],
            sub_category=data.get('sub_category', ''),
            account=data['account'],
            amount=float(data['amount']),
            parent_id=data.get('parent_id') or None
        )
        return jsonify({'success': True, 'id': txn_id})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route('/api/categories', methods=['GET'])
def api_get_categories():
    return jsonify(load_categories())


@app.route('/api/categories', methods=['POST'])
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


@app.route('/api/transactions', methods=['GET'])
def api_get_transactions():
    transactions = get_all_transactions()
    return jsonify(transactions)


@app.route('/api/summary', methods=['GET'])
def api_get_summary():
    summary = get_monthly_summary()
    return jsonify(summary)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
