import sys
import os
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import plan


SAMPLE_PLAN = {
    "plan_start_date": "2026-08-01",
    "phase1_target_total": 255000,
    "monthly_base": 130000,
    "base_income": 150000,
    "base_expense": 20000,
    "buckets": [
        {"id": "equity", "label": "Core equity", "amount": 60000, "ratio": 0.4615, "account_id": 3, "color": "blue"},
        {"id": "gold", "label": "Gold hedge", "amount": 15000, "ratio": 0.1154, "account_id": 4, "color": "amber"},
        {"id": "fd_topup", "label": "FD top-up", "amount": 15000, "ratio": 0.1154, "account_id": None, "color": "green"},
        {"id": "fun_fund", "label": "Fun fund", "amount": 30000, "ratio": 0.2308, "account_id": 8, "color": "pink"},
        {"id": "buffer", "label": "Flexible buffer", "amount": 10000, "ratio": 0.0769, "account_id": 1, "color": "gray"},
    ],
    "income_growth_pct": 18,
    "expense_growth_pct": 5,
    "extra_routing": "same_ratio",
    "no_penalty_mode": True,
}


def test_phase1_month_count():
    # ceil(255000 / 130000) = 2
    assert plan.phase1_month_count(SAMPLE_PLAN) == 2


def test_phase1_monthly_target_uses_buffer_and_fd_split():
    targets = plan.monthly_target(SAMPLE_PLAN, 0)
    assert set(targets.keys()) == {'buffer', 'fd_topup'}
    assert targets['buffer'] == 65000
    assert targets['fd_topup'] == 65000
    # month 2 (offset 1) still phase 1
    assert plan.monthly_target(SAMPLE_PLAN, 1) == targets


def test_post_phase1_target_no_extra_when_surplus_equals_base():
    # base_income - base_expense == monthly_base -> extra == 0, targets == bucket.amount
    targets = plan.monthly_target(SAMPLE_PLAN, 2)
    assert targets == {'equity': 60000, 'gold': 15000, 'fd_topup': 15000, 'fun_fund': 30000, 'buffer': 10000}


def test_extra_routed_same_ratio():
    p = dict(SAMPLE_PLAN, base_income=200000)
    targets = plan.monthly_target(p, 2)
    # surplus = 180000, extra = 50000
    assert round(targets['equity'], 2) == round(60000 + 50000 * 0.4615, 2)
    assert round(targets['buffer'], 2) == round(10000 + 50000 * 0.0769, 2)


def test_extra_routed_savings_only():
    p = dict(SAMPLE_PLAN, base_income=200000, extra_routing='savings_only')
    targets = plan.monthly_target(p, 2)
    assert targets['buffer'] == 10000 + 50000
    assert targets['equity'] == 60000  # unaffected


def test_income_growth_applies_per_plan_year():
    p = dict(SAMPLE_PLAN, base_income=200000)
    # offset 14 -> year_index 1
    targets_y1 = plan.monthly_target(p, 14)
    income_year1 = 200000 * 1.18
    expense_year1 = 20000 * 1.05
    extra_y1 = max(0, (income_year1 - expense_year1) - 130000)
    assert round(targets_y1['equity'], 2) == round(60000 + extra_y1 * 0.4615, 2)


def test_elapsed_month_offsets():
    assert plan.elapsed_month_offsets(SAMPLE_PLAN, date(2026, 8, 15)) == [0]
    assert plan.elapsed_month_offsets(SAMPLE_PLAN, date(2026, 10, 5)) == [0, 1, 2]
    assert plan.elapsed_month_offsets(SAMPLE_PLAN, date(2026, 7, 1)) == []


def test_cumulative_target_sums_completed_months_only():
    # elapsed offsets are 0,1,2 (Aug/Sep/Oct) but Oct (offset 2) is still in
    # progress as of Oct 5, so only Aug+Sep (both phase 1) should count.
    cum = plan.cumulative_target(SAMPLE_PLAN, date(2026, 10, 5))
    expected_buffer = 65000 + 65000
    assert cum['buffer'] == expected_buffer
    assert cum['_total'] > 0

    # Nothing completed yet on day one of the plan.
    cum_day1 = plan.cumulative_target(SAMPLE_PLAN, date(2026, 8, 15))
    assert cum_day1 == {'_total': 0}


def test_this_month_target_matches_last_elapsed_offset():
    assert plan.this_month_target(SAMPLE_PLAN, date(2026, 8, 15)) == plan.monthly_target(SAMPLE_PLAN, 0)
    assert plan.this_month_target(SAMPLE_PLAN, date(2026, 10, 20)) == plan.monthly_target(SAMPLE_PLAN, 2)


SAMPLE_TXNS = [
    {'type': 'Income', 'parent_id': None, 'plan_bucket': 'equity', 'date': '2026-08-10', 'amount': 60000},
    {'type': 'Income', 'parent_id': None, 'plan_bucket': 'gold', 'date': '2026-08-10', 'amount': 15000},
    {'type': 'Income', 'parent_id': None, 'plan_bucket': None, 'date': '2026-08-12', 'amount': 5000},  # untagged, excluded
    {'type': 'Expense', 'parent_id': None, 'plan_bucket': 'equity', 'date': '2026-08-15', 'amount': 100},  # not Income, excluded
    {'type': 'Income', 'parent_id': 3, 'plan_bucket': 'equity', 'date': '2026-08-15', 'amount': 200},  # sub-item, excluded
    {'type': 'Income', 'parent_id': None, 'plan_bucket': 'equity', 'date': '2026-07-01', 'amount': 999},  # before plan start, excluded
    {'type': 'Income', 'parent_id': None, 'plan_bucket': 'equity', 'date': '2026-09-05', 'amount': 60000},
]


def test_cumulative_actual_filters_correctly():
    actual = plan.cumulative_actual(SAMPLE_TXNS, SAMPLE_PLAN, date(2026, 10, 5))
    assert actual['equity'] == 120000
    assert actual['gold'] == 15000
    assert actual['_total'] == 135000


def test_this_month_actual():
    actual_aug = plan.this_month_actual(SAMPLE_TXNS, SAMPLE_PLAN, date(2026, 8, 20))
    assert actual_aug == {'equity': 60000, 'gold': 15000}
    actual_sep = plan.this_month_actual(SAMPLE_TXNS, SAMPLE_PLAN, date(2026, 9, 20))
    assert actual_sep == {'equity': 60000}


def test_months_contributed():
    # Oct (offset 2) is still in progress as of Oct 5, so only Aug+Sep count
    # as completed months — both have activity, so 2 of 2.
    n, m = plan.months_contributed(SAMPLE_TXNS, SAMPLE_PLAN, date(2026, 10, 5))
    assert n == 2
    assert m == 2

    # Nothing completed yet on day one of the plan.
    assert plan.months_contributed(SAMPLE_TXNS, SAMPLE_PLAN, date(2026, 8, 15)) == (0, 0)


def test_trajectory_excludes_in_progress_month():
    # Only the plan's start month has elapsed so far — nothing is "completed" yet,
    # so the trajectory shouldn't assume that month's target already happened.
    traj = plan.trajectory(SAMPLE_PLAN, date(2026, 8, 15), baseline_networth=100000)
    assert traj == []


def test_trajectory_includes_completed_months_only():
    # As of Sep 15: Aug (offset 0) is complete, Sep (offset 1) is still in progress.
    traj = plan.trajectory(SAMPLE_PLAN, date(2026, 9, 15), baseline_networth=100000)
    assert len(traj) == 1
    month_key, value = traj[0]
    assert month_key == '2026-08'
    assert value == 100000 + sum(plan.monthly_target(SAMPLE_PLAN, 0).values())

    # As of Oct 15: Aug and Sep are both complete now, Oct is in progress.
    traj2 = plan.trajectory(SAMPLE_PLAN, date(2026, 10, 15), baseline_networth=100000)
    assert [m for m, _ in traj2] == ['2026-08', '2026-09']


SAMPLE_ACCOUNTS = [
    {'id': 10, 'name': 'ICICI FD', 'type': 'investment', 'subtype': 'fd', 'balance': 112500, 'start_date': '2026-08-10'},
    {'id': 11, 'name': 'HDFC FD', 'type': 'investment', 'subtype': 'fd', 'balance': 112500, 'start_date': '2026-09-01'},
    {'id': 12, 'name': 'Old FD, before plan start', 'type': 'investment', 'subtype': 'fd', 'balance': 999, 'start_date': '2026-07-01'},
    {'id': 3, 'name': 'NIFTYBEES', 'type': 'investment', 'subtype': 'market', 'balance': 60000, 'ticker': 'NIFTYBEES.NS', 'units': 200},
]


def test_fd_contributions_counted_as_fd_topup_actual():
    # FDs have no Income transaction (principal is set at account creation) —
    # only accounts.json's start_date identifies them as plan contributions.
    cum = plan.cumulative_actual([], SAMPLE_PLAN, date(2026, 10, 5), accounts=SAMPLE_ACCOUNTS)
    assert cum['fd_topup'] == 112500 + 112500  # both FDs, pre-plan-start one excluded
    assert cum['_total'] == 225000


def test_fd_contribution_scoped_to_month():
    actual_aug = plan.this_month_actual([], SAMPLE_PLAN, date(2026, 8, 20), accounts=SAMPLE_ACCOUNTS)
    assert actual_aug == {'fd_topup': 112500}
    actual_sep = plan.this_month_actual([], SAMPLE_PLAN, date(2026, 9, 20), accounts=SAMPLE_ACCOUNTS)
    assert actual_sep == {'fd_topup': 112500}


def test_fd_booking_counts_toward_months_contributed():
    n, m = plan.months_contributed([], SAMPLE_PLAN, date(2026, 10, 5), accounts=SAMPLE_ACCOUNTS)
    assert n == 2  # Aug (ICICI FD) and Sep (HDFC FD) both booked
    assert m == 2


def test_no_fd_bucket_means_no_fd_matching():
    plan_without_fd_bucket = dict(SAMPLE_PLAN, buckets=[b for b in SAMPLE_PLAN['buckets'] if b['id'] != 'fd_topup'])
    cum = plan.cumulative_actual([], plan_without_fd_bucket, date(2026, 10, 5), accounts=SAMPLE_ACCOUNTS)
    assert 'fd_topup' not in cum


def test_transfer_with_bucket_tag_counts_as_actual():
    # One-step transfer (source -> destination, single row) tagged with a
    # bucket should count identically to a tagged Income transaction.
    txns = [
        {'type': 'Transfer', 'parent_id': None, 'plan_bucket': 'fun_fund', 'date': '2026-08-10',
         'amount': 30000, 'account': 'HDFC Savings', 'transfer_to_account': 'IDBI Savings Account'},
    ]
    actual = plan.cumulative_actual(txns, SAMPLE_PLAN, date(2026, 10, 5))
    assert actual['fun_fund'] == 30000


def test_transfer_without_destination_does_not_count():
    # A Transfer tagged with a bucket but no transfer_to_account credited
    # nothing anywhere — shouldn't count as a real contribution.
    txns = [
        {'type': 'Transfer', 'parent_id': None, 'plan_bucket': 'fun_fund', 'date': '2026-08-10',
         'amount': 30000, 'account': 'HDFC Savings', 'transfer_to_account': None},
    ]
    actual = plan.cumulative_actual(txns, SAMPLE_PLAN, date(2026, 10, 5))
    assert actual == {'_total': 0}


def test_average_monthly_growth_needs_two_points():
    assert plan.average_monthly_growth([]) is None
    assert plan.average_monthly_growth([('2026-08', 100000)]) is None


def test_average_monthly_growth_uses_calendar_gap_not_point_count():
    # 3 data points but a gap (no Oct snapshot) — gap is Aug->Dec = 4 months,
    # not 2 (point count - 1), so growth-per-month should be spread over 4.
    series = [('2026-08', 100000), ('2026-09', 120000), ('2026-12', 180000)]
    assert plan.average_monthly_growth(series) == (180000 - 100000) / 4


def test_linear_eta_no_growth_means_no_eta():
    assert plan.linear_eta_month_key(500000, 10000000, None) is None
    assert plan.linear_eta_month_key(500000, 10000000, 0) is None
    assert plan.linear_eta_month_key(500000, 10000000, -1000) is None


def test_linear_eta_already_reached():
    assert plan.linear_eta_month_key(10000000, 10000000, 50000, date(2026, 8, 15)) == '2026-08'
    assert plan.linear_eta_month_key(12000000, 10000000, 50000, date(2026, 8, 15)) == '2026-08'


def test_linear_eta_projects_forward():
    # Need 9,500,000 more at 100,000/month -> ceil(95) = 95 months from Aug 2026.
    eta = plan.linear_eta_month_key(500000, 10000000, 100000, date(2026, 8, 15))
    assert eta == '2034-07'  # Aug 2026 + 95 months


def test_theoretical_eta_already_reached():
    assert plan.theoretical_eta_month_key(SAMPLE_PLAN, 10000000, 10000000, date(2026, 8, 15)) == '2026-08'


def test_theoretical_eta_no_goal_or_no_plan_start():
    assert plan.theoretical_eta_month_key(SAMPLE_PLAN, 500000, None, date(2026, 8, 15)) is None
    assert plan.theoretical_eta_month_key({}, 500000, 10000000, date(2026, 8, 15)) is None


def test_theoretical_eta_zero_target_never_reaches():
    zero_plan = dict(SAMPLE_PLAN, buckets=[], phase1_target_total=0, monthly_base=0, base_income=0, base_expense=0)
    assert plan.theoretical_eta_month_key(zero_plan, 500000, 10000000, date(2026, 10, 5), max_months=12) is None


def test_theoretical_eta_projects_forward_from_next_month():
    # As of Oct 5 2026: offsets elapsed are [0,1,2] (Aug/Sep/Oct), so projection
    # starts at offset 3 (Nov). Phase 1 (2 months) is already done by then.
    eta = plan.theoretical_eta_month_key(SAMPLE_PLAN, 9950000, 10000000, date(2026, 10, 5))
    # Post-phase-1 monthly target total with no extra = 60000+15000+15000+30000+10000 = 130000
    # Needs 50000 more -> 1 month -> Nov 2026.
    assert eta == '2026-11'
