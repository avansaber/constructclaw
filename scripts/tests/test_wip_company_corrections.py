"""Company-scoped WIP parity and change-order ownership regressions."""

from decimal import Decimal

import pytest

from erpclaw_lib.db import get_connection
from erpclaw_lib.query import P, Q, Table

from construct_helpers import (
    build_env, call_action, init_all_tables, is_error, is_ok, load_db_query, ns,
)
from test_jobs_estimates import TestWipReport as _WipSetup


@pytest.fixture
def case(tmp_path, monkeypatch):
    path = str(tmp_path / "construction.sqlite")
    init_all_tables(path)
    monkeypatch.setenv("ERPCLAW_DB_PATH", path)
    conn = get_connection(path)
    try:
        yield conn, build_env(conn), load_db_query(), _WipSetup()
    finally:
        conn.close()


def _set(conn, table_name, row_id, **values):
    table = Table(table_name)
    query = Q.update(table)
    for key in values:
        query = query.set(getattr(table, key), P())
    query = query.where(table.id == P())
    conn.execute(query.get_sql(), (*values.values(), row_id))
    conn.commit()


def _state(conn):
    names = (
        "constructclaw_job", "constructclaw_cost_code", "constructclaw_cost_entry",
        "constructclaw_cco", "constructclaw_progress_bill", "constructclaw_commitment",
        "naming_series", "audit_log",
    )
    return {
        name: sorted(repr(dict(row)) for row in conn.execute(
            Q.from_(Table(name)).select(Table(name).star).get_sql()
        ).fetchall())
        for name in names
    }


def _active_job(case, contract="500.00", budget="100.00", job_status="active"):
    conn, env, mod, setup = case
    job_id = setup._add_job(conn, env, mod, contract)
    _set(conn, "constructclaw_job", job_id,
         job_status=job_status, percent_complete="99")
    if budget is not None:
        setup._add_code(conn, env, mod, job_id, "LABOUR", budget)
    return job_id


def _all(case):
    conn, env, mod, _ = case
    return call_action(mod.ACTIONS["construction-wip-report-all"], conn,
                       ns(company_id=env["company_id"]))


def _assert_parity(case, result):
    conn, _, mod, _ = case
    assert is_ok(result), result
    for row in result["jobs"]:
        single = call_action(mod.ACTIONS["construction-wip-report"], conn,
                             ns(job_id=row["job_id"]))
        assert is_ok(single), single
        assert row == {key: value for key, value in single.items() if key != "status"}


def test_fractional_costs_active_budgets_and_read_only_parity(case):
    conn, env, mod, setup = case
    job_id = _active_job(case, contract="500.05", budget="0.33")
    setup._add_code(conn, env, mod, job_id, "MATERIAL", "0.67")
    setup._add_code(conn, env, mod, job_id, "INACTIVE", "9999.00")
    code = Table("constructclaw_cost_code")
    conn.execute(Q.update(code).set(code.is_active, P()).where(
        code.job_id == P()).where(code.code == P()).get_sql(), (0, job_id, "INACTIVE"))
    conn.commit()
    setup._add_cost(conn, env, mod, job_id, "0.10")
    setup._add_cost(conn, env, mod, job_id, "0.20")
    before = _state(conn)
    result = _all(case)
    _assert_parity(case, result)
    row = result["jobs"][0]
    assert row["total_cost"] == "0.30"
    assert row["estimated_total_cost"] == "1.00"
    assert row["percent_complete"] == "30.00"
    assert row["earned_revenue"] == "150.02"
    assert result["total_contract_value"] == "500.05"
    assert result["total_cost"] == "0.30"
    assert _state(conn) == before


def test_revised_contract_and_bill_lifecycle_use_identical_basis(case):
    conn, env, mod, setup = case
    job_id = _active_job(case)
    setup._add_cost(conn, env, mod, job_id, "50.00")
    for status, amount in (("approved", "100.10"), ("executed", "50.20"),
                           ("draft", "999.00"), ("rejected", "888.00")):
        cco_id = setup._add_cco(conn, env, mod, job_id, status, amount)
        _set(conn, "constructclaw_cco", cco_id, cco_status=status)
    for status, amount in (("submitted", "40.10"), ("approved", "20.20"),
                           ("draft", "999.00"), ("rejected", "888.00"),
                           ("paid", "777.00")):
        bill_id = setup._add_bill(conn, env, mod, job_id, "100.00")
        _set(conn, "constructclaw_progress_bill", bill_id,
             bill_status=status, current_due=amount)
    before = _state(conn)
    result = _all(case)
    _assert_parity(case, result)
    row = result["jobs"][0]
    assert row["change_orders"] == "150.30"
    assert row["revised_contract"] == "650.30"
    assert row["earned_revenue"] == "325.15"
    assert row["total_billed"] == "60.30"
    assert row["costs_in_excess_of_billings"] == "264.85"
    assert row["billing_status"] == "underbilled"
    assert result["total_contract_value"] == "650.30"
    assert result["total_billed"] == "60.30"
    assert _state(conn) == before


@pytest.mark.parametrize("cost,billed,completion,earned,excess", [
    ("25.00", "150.10", "25.00", "125.00", "25.10"),
    ("125.05", "500.00", "100.00", "500.00", "0.00"),
])
def test_overbilling_and_capped_completion_match_single_job(
        case, cost, billed, completion, earned, excess):
    conn, env, mod, setup = case
    job_id = _active_job(case)
    setup._add_cost(conn, env, mod, job_id, cost)
    bill_id = setup._add_bill(conn, env, mod, job_id, billed)
    setup._submit_bill(conn, mod, bill_id)
    result = _all(case)
    _assert_parity(case, result)
    row = result["jobs"][0]
    assert row["percent_complete"] == completion
    assert row["earned_revenue"] == earned
    assert row["billings_in_excess_of_costs"] == excess
    assert row["costs_in_excess_of_billings"] == "0.00"
    assert row["over_under_billing"] == excess
    assert row["billing_status"] == ("overbilled" if Decimal(excess) else "balanced")


def test_unrounded_ratio_is_used_for_revenue(case):
    conn, env, mod, setup = case
    job_id = _active_job(case, contract="1000000.00", budget="3.00")
    setup._add_cost(conn, env, mod, job_id, "1.00")
    result = _all(case)
    _assert_parity(case, result)
    assert result["jobs"][0]["percent_complete"] == "33.33"
    assert result["jobs"][0]["earned_revenue"] == "333333.33"


def test_company_and_job_status_filter_with_exact_portfolio_totals(case):
    conn, env, mod, setup = case
    included = []
    for status, contract, cost in (("active", "100.10", "0.10"),
                                  ("on_hold", "200.20", "0.20"),
                                  ("substantially_complete", "300.30", "0.30")):
        job_id = _active_job(case, contract=contract, job_status=status)
        setup._add_cost(conn, env, mod, job_id, cost)
        included.append(job_id)
    change = setup._add_cco(conn, env, mod, included[0], "Approved", "10.01")
    _set(conn, "constructclaw_cco", change, cco_status="approved")
    for status in ("planning", "closed", "cancelled"):
        _active_job(case, contract="999.00", job_status=status)
    other = build_env(conn)
    foreign = _active_job((conn, other, mod, setup), contract="888.00")
    result = _all(case)
    _assert_parity(case, result)
    assert {row["job_id"] for row in result["jobs"]} == set(included)
    assert foreign not in {row["job_id"] for row in result["jobs"]}
    assert result["total_count"] == 3
    assert Decimal(result["total_contract_value"]) == Decimal("610.61")
    assert result["total_cost"] == "0.60"
    assert result["total_billed"] == "0.00"


def test_draft_commitment_does_not_become_actual_cost(case):
    conn, env, mod, setup = case
    job_id = _active_job(case)
    commitment = call_action(mod.ACTIONS["construction-add-commitment"], conn, ns(
        company_id=env["company_id"], job_id=job_id,
        vendor="Synthetic Vendor", original_amount="900.00",
        commitment_type=None, cost_code_id=None, description=None,
        vendor_id=None, notes=None,
    ))
    assert is_ok(commitment), commitment
    assert commitment["commitment_status"] == "draft"
    result = _all(case)
    _assert_parity(case, result)
    assert result["jobs"][0]["total_cost"] == "0.00"
    assert result["jobs"][0]["earned_revenue"] == "0.00"


@pytest.mark.parametrize("budget", [None, "0.00", "-1.00"])
def test_nonpositive_estimate_refuses_with_single_job_error_without_writes(case, budget):
    conn, _, mod, _ = case
    job_id = _active_job(case, budget=budget)
    before = _state(conn)
    single = call_action(mod.ACTIONS["construction-wip-report"], conn, ns(job_id=job_id))
    result = _all(case)
    assert is_error(single), single
    assert result == single
    assert "must be greater than zero" in result["message"]
    assert _state(conn) == before


def test_foreign_company_change_order_refuses_without_any_write(case):
    conn, env, mod, setup = case
    other = build_env(conn)
    job_id = setup._add_job(conn, other, mod)
    before = _state(conn)
    result = call_action(mod.ACTIONS["construction-add-cco"], conn, ns(
        company_id=env["company_id"], job_id=job_id,
        title="Foreign job", cost_change="100.10",
    ))
    assert is_error(result), result
    assert "company" in result["message"].lower()
    assert _state(conn) == before


def test_own_company_change_order_still_creates_draft(case):
    conn, env, mod, setup = case
    job_id = setup._add_job(conn, env, mod)
    cco_id = setup._add_cco(conn, env, mod, job_id, "Own job", "100.10")
    cco = Table("constructclaw_cco")
    row = conn.execute(Q.from_(cco).select(cco.star).where(cco.id == P()).get_sql(),
                       (cco_id,)).fetchone()
    assert row["company_id"] == env["company_id"]
    assert row["job_id"] == job_id
    assert row["cco_status"] == "draft"
    assert row["cost_change"] == "100.10"


def test_missing_job_change_order_refusal_preserves_counters_and_audit(case):
    conn, env, mod, _ = case
    before = _state(conn)
    result = call_action(mod.ACTIONS["construction-add-cco"], conn, ns(
        company_id=env["company_id"], job_id="missing-job",
        title="No job", cost_change="100.10",
    ))
    assert is_error(result), result
    assert result["message"] == "Job missing-job not found"
    assert _state(conn) == before
