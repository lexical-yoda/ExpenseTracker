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
