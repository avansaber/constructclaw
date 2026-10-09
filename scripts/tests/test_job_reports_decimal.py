"""Job reports retain exact cents and the owning company's recorded rows."""
from decimal import Decimal

import pytest

from construct_helpers import call_action, ns, seed_company
from erpclaw_lib.query import Q, P, Table
from test_jobs_estimates import TestWipReport as _Setup


def update(conn, name, rid, **values):
    table = Table(name)
    query = Q.update(table)
    for field, value in values.items():
        query = query.set(table[field], P())
    conn.execute(query.where(table.id == P()).get_sql(), (*values.values(), rid))
    conn.commit()


def snapshot(conn):
    return {name: sorted(repr(dict(row)) for row in conn.execute(
        Q.from_(Table(name)).select("*").get_sql()).fetchall())
        for name in ("constructclaw_job", "constructclaw_cost_entry",
                     "constructclaw_cco", "constructclaw_commitment",
                     "constructclaw_progress_bill", "audit_log", "naming_series")}


def fixture(conn, env, mod):
    setup = _Setup()
    job = setup._add_job(conn, env, mod, "9007199254740993.00")
    for amount in ("9007199254740992.10", "0.20"):
        setup._add_cost(conn, env, mod, job, amount)
    cost = Table("constructclaw_cost_entry")
    costs = conn.execute(Q.from_(cost).select(cost.id, cost.amount)
                         .where(cost.job_id == P()).get_sql(), (job,)).fetchall()
    for row in costs:
        update(conn, "constructclaw_cost_entry", row["id"], hours="0.10")
    for amount, status in (("0.10", "approved"), ("0.20", "executed"), ("999.00", "draft")):
        rid = setup._add_cco(conn, env, mod, job, status, amount)
        update(conn, "constructclaw_cco", rid, cco_status=status)
    for amount, status in (("9007199254740990.10", "submitted"), ("0.20", "draft"), ("999.00", "rejected")):
        rid = setup._add_bill(conn, env, mod, job, "1.00")
        update(conn, "constructclaw_progress_bill", rid, current_due=amount, bill_status=status)
    for amount, status in (("9007199254740991.10", "approved"), ("0.20", "draft"), ("999.00", "closed"), ("999.00", "cancelled")):
        result = call_action(mod.ACTIONS["construction-add-commitment"], conn, ns(
            company_id=env["company_id"], job_id=job, original_amount=amount))
        assert result["status"] == "ok", result
        update(conn, "constructclaw_commitment", result["commitment_id"], commitment_status=status)
    return job


@pytest.mark.parametrize("action", ["construction-job-profitability", "construction-job-cost-report"])
@pytest.mark.parametrize("explicit_company", [True, False])
def test_exact_large_cents_and_status_rules_without_writes(conn, env, mod, action, explicit_company):
    job = fixture(conn, env, mod)
    before = snapshot(conn)
    args = ns(job_id=job, company_id=env["company_id"] if explicit_company else None)
    result = call_action(mod.ACTIONS[action], conn, args)
    assert result["status"] == "ok", result
    assert Decimal(result["total_cost"]) == Decimal("9007199254740992.30")
    assert Decimal(result["change_orders"]) == Decimal("0.30")
    assert Decimal(result["revised_contract"]) == Decimal("9007199254740993.30")
    if action.endswith("profitability"):
        assert Decimal(result["total_billed"]) == Decimal("9007199254740990.30")
        assert Decimal(result["gross_profit"]) == Decimal("1.00")
    else:
        assert Decimal(result["total_committed"]) == Decimal("9007199254740991.30")
        assert Decimal(result["variance"]) == Decimal("1.00")
        assert result["by_category"] == [dict(category="labor", entry_count=2,
            total_amount="9007199254740992.30", total_hours="0.20")]
    assert snapshot(conn) == before
    assert not conn.in_transaction


@pytest.mark.parametrize("action", ["construction-job-profitability", "construction-job-cost-report"])
def test_explicit_foreign_company_refused_without_writes(conn, env, mod, action):
    job = _Setup()._add_job(conn, env, mod)
    other = seed_company(conn, name="Other Builder", abbr="OB")
    before = snapshot(conn)
    result = call_action(mod.ACTIONS[action], conn, ns(job_id=job, company_id=other))
    assert result["status"] == "error", result
    assert snapshot(conn) == before
    assert not conn.in_transaction


@pytest.mark.parametrize("action", ["construction-job-profitability", "construction-job-cost-report"])
def test_foreign_child_company_never_contributes(conn, env, mod, action):
    setup = _Setup()
    job = setup._add_job(conn, env, mod)
    setup._add_cost(conn, env, mod, job, "99.00")
    other = seed_company(conn, name="Other Builder", abbr="OB")
    table = Table("constructclaw_cost_entry")
    rid = conn.execute(Q.from_(table).select(table.id).where(table.job_id == P())
                       .get_sql(), (job,)).fetchone()["id"]
    update(conn, "constructclaw_cost_entry", rid, company_id=other)
    before = snapshot(conn)
    result = call_action(mod.ACTIONS[action], conn, ns(job_id=job, company_id=env["company_id"]))
    assert result["status"] == "ok", result
    assert Decimal(result["total_cost"]) == Decimal("0.00")
    assert snapshot(conn) == before
