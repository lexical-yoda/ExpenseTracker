"""Plan-vs-actual target/actual calculations. Pure functions — no Flask/I/O.

Given plan.json (as a dict) and the transaction list from spreadsheet.py, these
functions compute per-bucket monthly targets, cumulative targets, and actuals.
"""

import math
from datetime import date, datetime
from collections import defaultdict


def _parse_date(d):
    if isinstance(d, date):
        return d
    return datetime.strptime(d, '%Y-%m-%d').date()


def _month_offset(start_date, target_date):
    """0-based number of full months between start_date's month and target_date's month."""
    return (target_date.year - start_date.year) * 12 + (target_date.month - start_date.month)


def _month_key(year, month):
    return f'{year:04d}-{month:02d}'


def _add_months(year, month, n):
    total = (year * 12 + (month - 1)) + n
    return total // 12, total % 12 + 1


def default_phase1_buckets(plan):
    """Fallback phase1 split when plan.json doesn't specify one: buffer + fd_topup, 50/50."""
    ids = [b['id'] for b in plan.get('buckets', []) if b['id'] in ('buffer', 'fd_topup')]
    if not ids:
        return {}
    return {bid: 1.0 / len(ids) for bid in ids}


def phase1_month_count(plan):
    """Number of months needed at monthly_base to reach phase1_target_total."""
    monthly_base = plan.get('monthly_base', 0)
    phase1_total = plan.get('phase1_target_total', 0)
    if monthly_base <= 0 or phase1_total <= 0:
        return 0
    return math.ceil(phase1_total / monthly_base)


def monthly_target(plan, month_offset):
    """Target per bucket for the given 0-based month_offset since plan_start_date.

    Returns {bucket_id: amount}.
    """
    buckets = plan.get('buckets', [])
    n_phase1 = phase1_month_count(plan)

    if month_offset < n_phase1:
        split = plan.get('phase1_buckets') or default_phase1_buckets(plan)
        monthly_base = plan.get('monthly_base', 0)
        return {bid: monthly_base * ratio for bid, ratio in split.items()}

    year_index = month_offset // 12
    income_growth = plan.get('income_growth_pct', 0) / 100.0
    expense_growth = plan.get('expense_growth_pct', 0) / 100.0
    base_income = plan.get('base_income', 0)
    base_expense = plan.get('base_expense', 0)
    monthly_base = plan.get('monthly_base', 0)

    income_year = base_income * (1 + income_growth) ** year_index
    expense_year = base_expense * (1 + expense_growth) ** year_index
    surplus_year = income_year - expense_year
    extra = max(0, surplus_year - monthly_base)

    extra_routing = plan.get('extra_routing', 'same_ratio')

    result = {}
    for b in buckets:
        target = b.get('amount', 0)
        if extra_routing == 'same_ratio':
            target += extra * b.get('ratio', 0)
        elif extra_routing == 'savings_only' and b['id'] == 'buffer':
            target += extra
        result[b['id']] = target
    return result


def elapsed_month_offsets(plan, as_of_date=None):
    """List of 0-based month offsets from plan_start_date through as_of_date (inclusive)."""
    if 'plan_start_date' not in plan:
        return []
    start = _parse_date(plan['plan_start_date'])
    as_of = as_of_date or date.today()
    if as_of < start:
        return []
    n = _month_offset(start, as_of)
    return list(range(n + 1))


def completed_month_offsets(plan, as_of_date=None):
    """Like elapsed_month_offsets, but excludes the current, still-in-progress
    month — a month's target isn't "due" until the month is actually over."""
    return elapsed_month_offsets(plan, as_of_date)[:-1]


def cumulative_target(plan, as_of_date=None):
    """Sum of monthly targets per bucket across all COMPLETED months (the
    current in-progress month is excluded — see completed_month_offsets).
    Returns {bucket_id: total, '_total': grand_total}."""
    totals = defaultdict(float)
    for offset in completed_month_offsets(plan, as_of_date):
        for bid, amt in monthly_target(plan, offset).items():
            totals[bid] += amt
    totals['_total'] = sum(v for k, v in totals.items() if k != '_total')
    return dict(totals)


def this_month_target(plan, as_of_date=None):
    offsets = elapsed_month_offsets(plan, as_of_date)
    if not offsets:
        return {}
    return monthly_target(plan, offsets[-1])


def _plan_transactions(transactions, plan):
    """Income or Transfer-with-destination, parent-only transactions tagged with
    a known bucket id, on/after plan_start_date. Transfer counts here too since
    a one-step transfer (source account -> destination account, single row) is
    the normal way to fund a bucket-linked account without a separate Income leg."""
    if 'plan_start_date' not in plan:
        return []
    start = _parse_date(plan['plan_start_date'])
    bucket_ids = {b['id'] for b in plan.get('buckets', [])}
    out = []
    for t in transactions:
        if t.get('type') not in ('Income', 'Transfer') or t.get('parent_id') or not t.get('plan_bucket'):
            continue
        if t['plan_bucket'] not in bucket_ids:
            continue
        if t['type'] == 'Transfer' and not t.get('transfer_to_account'):
            continue  # no destination credited — nothing actually funded the bucket
        try:
            t_date = _parse_date(t['date'])
        except (ValueError, TypeError):
            continue
        if t_date < start:
            continue
        out.append(t)
    return out


def _fd_contributions(accounts, plan, as_of_date=None):
    """FD principal contributions attributed to the 'fd_topup' bucket, keyed by
    each FD account's start_date. FDs are booked as brand-new discrete accounts
    each time (principal set directly at account creation) — there is no Income
    transaction to tag, so this is the only way to count them as plan
    contributions. Returns [(date_str, amount), ...]."""
    if 'plan_start_date' not in plan or not any(b['id'] == 'fd_topup' for b in plan.get('buckets', [])):
        return []
    start = _parse_date(plan['plan_start_date'])
    as_of = as_of_date or date.today()
    out = []
    for acct in (accounts or []):
        if acct.get('type') != 'investment' or acct.get('subtype') != 'fd':
            continue
        fd_start = acct.get('start_date')
        if not fd_start:
            continue
        try:
            fd_date = _parse_date(fd_start)
        except (ValueError, TypeError):
            continue
        if start <= fd_date <= as_of:
            out.append((fd_start, acct.get('balance', 0)))
    return out


def cumulative_actual(transactions, plan, as_of_date=None, accounts=None):
    """Sum of actual contributions per bucket since plan_start_date through as_of_date.
    Returns {bucket_id: total, '_total': grand_total}."""
    as_of = as_of_date or date.today()
    totals = defaultdict(float)
    for t in _plan_transactions(transactions, plan):
        if _parse_date(t['date']) <= as_of:
            totals[t['plan_bucket']] += t['amount']
    for _, amt in _fd_contributions(accounts, plan, as_of_date):
        totals['fd_topup'] += amt
    totals['_total'] = sum(v for k, v in totals.items() if k != '_total')
    return dict(totals)


def this_month_actual(transactions, plan, as_of_date=None, accounts=None):
    as_of = as_of_date or date.today()
    totals = defaultdict(float)
    for t in _plan_transactions(transactions, plan):
        t_date = _parse_date(t['date'])
        if t_date.year == as_of.year and t_date.month == as_of.month:
            totals[t['plan_bucket']] += t['amount']
    for fd_date_str, amt in _fd_contributions(accounts, plan, as_of_date):
        fd_date = _parse_date(fd_date_str)
        if fd_date.year == as_of.year and fd_date.month == as_of.month:
            totals['fd_topup'] = totals.get('fd_topup', 0) + amt
    return dict(totals)


def months_contributed(transactions, plan, as_of_date=None, accounts=None):
    """(N, M): N = distinct completed calendar months with at least one tagged
    contribution (or FD booked), M = total completed months since plan start.
    The current, still-in-progress month isn't counted either way yet."""
    offsets = completed_month_offsets(plan, as_of_date)
    if not offsets:
        return 0, 0
    start = _parse_date(plan['plan_start_date'])
    months_with_activity = set()
    for t in _plan_transactions(transactions, plan):
        t_date = _parse_date(t['date'])
        months_with_activity.add(_month_offset(start, t_date))
    for fd_date_str, _ in _fd_contributions(accounts, plan, as_of_date):
        months_with_activity.add(_month_offset(start, _parse_date(fd_date_str)))
    n = len({o for o in months_with_activity if o in offsets})
    return n, len(offsets)


def trajectory(plan, as_of_date=None, baseline_networth=0):
    """Cumulative projected net worth per COMPLETED elapsed month, assuming every
    monthly target was hit. The current, still-in-progress month is excluded —
    its target hasn't had a chance to be realized yet, so including it would
    make the projection jump a full month ahead of reality on day one of a new
    plan (or right after any plan_start_date change). Returns list of
    (month_key, projected_networth)."""
    if 'plan_start_date' not in plan:
        return []
    start = _parse_date(plan['plan_start_date'])
    completed_offsets = completed_month_offsets(plan, as_of_date)
    running = baseline_networth
    out = []
    for offset in completed_offsets:
        year, month = _add_months(start.year, start.month, offset)
        running += sum(monthly_target(plan, offset).values())
        out.append((_month_key(year, month), running))
    return out


def _month_key_index(month_key):
    """'YYYY-MM' -> a single sortable/subtractable integer (year*12 + month)."""
    y, m = month_key.split('-')
    return int(y) * 12 + int(m)


def average_monthly_growth(actual_series):
    """Average real net worth change per elapsed calendar month, from the first
    to the last point in actual_series ([(month_key, value), ...], sorted).
    Uses the calendar-month gap between the first and last key (not the point
    count), since networth_history.json has no backfill and can have gaps if
    the dashboard wasn't opened in a given month. Returns None with fewer than
    2 points or a zero month gap (can't compute a rate)."""
    if len(actual_series) < 2:
        return None
    first_key, first_val = actual_series[0]
    last_key, last_val = actual_series[-1]
    months_elapsed = _month_key_index(last_key) - _month_key_index(first_key)
    if months_elapsed <= 0:
        return None
    return (last_val - first_val) / months_elapsed


def linear_eta_month_key(current_value, goal, monthly_growth, as_of_date=None):
    """Month key (YYYY-MM) by which current_value reaches goal, extrapolating
    monthly_growth linearly forward from as_of_date (today by default).
    Returns None if goal/monthly_growth is missing or monthly_growth <= 0 (flat
    or declining net worth has no ETA — there's nothing honest to project).
    Returns the current month's key if the goal is already reached."""
    if goal is None or monthly_growth is None or monthly_growth <= 0:
        return None
    as_of = as_of_date or date.today()
    if current_value >= goal:
        return _month_key(as_of.year, as_of.month)
    months_needed = math.ceil((goal - current_value) / monthly_growth)
    year, month = _add_months(as_of.year, as_of.month, months_needed)
    return _month_key(year, month)


def theoretical_eta_month_key(plan, current_value, goal, as_of_date=None, max_months=1200):
    """Month key by which current_value reaches goal if every future monthly
    plan target (monthly_target()) is hit exactly, continuing forward from the
    month after as_of_date. Returns None if goal is missing, plan has no start
    date, or the plan's targets sum to <= 0 (can never reach the goal this way
    — capped at max_months, 100 years, as a safety backstop either way).
    Returns the current month's key if the goal is already reached."""
    if goal is None:
        return None
    as_of = as_of_date or date.today()
    if current_value >= goal:
        return _month_key(as_of.year, as_of.month)
    if 'plan_start_date' not in plan:
        return None
    offsets = elapsed_month_offsets(plan, as_of)
    offset = (offsets[-1] + 1) if offsets else 0
    running = current_value
    months = 0
    while running < goal and months < max_months:
        target_sum = sum(monthly_target(plan, offset).values())
        if target_sum <= 0:
            return None
        running += target_sum
        offset += 1
        months += 1
    if running < goal:
        return None
    year, month = _add_months(as_of.year, as_of.month, months)
    return _month_key(year, month)
