"""Progress bills are capped at the contract sum to date (incl. approved CCOs)."""
import pytest

from construct_helpers import call_action, ns, is_ok, is_error, load_db_query
from test_progress_bill_g703 import _add_job, _add_sov, _seed_sov_line


@pytest.fixture
def mod():
    return load_db_query()


_SNAP_TABLES = (
    "constructclaw_progress_bill",
    "constructclaw_progress_bill_line",
    "audit_log",
    "naming_series",
)


def _snapshot(conn):
    snap = {}
    for table in _SNAP_TABLES:
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()
        snap[table] = sorted(repr(dict(r)) for r in rows)
    return snap


def _add_bill(conn, env, mod, job_id, completed, retention):
    return call_action(mod.ACTIONS["construction-add-progress-bill"], conn, ns(
        company_id=env["company_id"], job_id=job_id, sov_id=None,
        total_completed=completed, total_retention=retention,
        period_from="2026-03-01", period_to="2026-03-31", notes=None))


def _add_cost_plus_job(conn, env, mod, name="Cost Plus Job", contract_amount="0"):
    r = call_action(mod.ACTIONS["construction-add-job"], conn, ns(
        company_id=env["company_id"], name=name,
        job_type=None, contract_type="cost_plus", contract_amount=contract_amount,
        client_name=None, client_id=env["customer_id"], description=None,
        project_manager=None, superintendent=None,
        start_date=None, end_date=None, address=None,
        city=None, state=None, zip_code=None, notes=None,
    ))
    assert is_ok(r), r
    return r["job_id"]


def _add_cco(conn, env, mod, job_id, title, cost_change):
    r = call_action(mod.ACTIONS["construction-add-cco"], conn, ns(
        company_id=env["company_id"], job_id=job_id, pco_id=None,
        title=title, description=None, cost_change=cost_change,
        time_change_days=None, notes=None))
    assert is_ok(r), r
    return r["cco_id"]


def test_flat_bill_over_contract_refused(conn, env, mod):
    job_id = _add_job(conn, env, mod, contract_amount="100000.00")
    r1 = _add_bill(conn, env, mod, job_id, "30000.00", "3000.00")
    assert is_ok(r1), r1
    r2 = _add_bill(conn, env, mod, job_id, "70000.00", "7000.00")
    assert is_ok(r2), r2
    before = _snapshot(conn)
    r3 = _add_bill(conn, env, mod, job_id, "150000.00", "15000.00")
    assert is_error(r3), r3
    assert r3["message"] == (
        f"Completed to date 150000.00 exceeds the contract amount 100000.00 "
        f"for job {job_id}; approve a change order to bill more")
    assert _snapshot(conn) == before


def test_bill_at_contract_allowed(conn, env, mod):
    job_id = _add_job(conn, env, mod, contract_amount="100000.00")
    r = _add_bill(conn, env, mod, job_id, "100000.00", "10000.00")
    assert is_ok(r), r
    assert r["current_due"] == "90000.00"


def test_approved_change_order_raises_the_cap(conn, env, mod):
    job_id = _add_job(conn, env, mod, contract_amount="100000.00")
    cco_id = _add_cco(conn, env, mod, job_id, "Extra work", "25000.00")
    r = call_action(mod.ACTIONS["construction-approve-cco"], conn, ns(
        cco_id=cco_id, approved_by="Owner"))
    assert is_ok(r), r
    ok_bill = _add_bill(conn, env, mod, job_id, "125000.00", "12500.00")
    assert is_ok(ok_bill), ok_bill
    over = _add_bill(conn, env, mod, job_id, "125000.01", "12500.00")
    assert is_error(over), over
    assert over["message"] == (
        f"Completed to date 125000.01 exceeds the contract amount 125000.00 "
        f"for job {job_id}; approve a change order to bill more")
    draft_id = _add_cco(conn, env, mod, job_id, "Not yet approved", "50000.00")
    assert draft_id
    still_over = _add_bill(conn, env, mod, job_id, "125000.01", "12500.00")
    assert is_error(still_over), still_over
    assert still_over["message"] == (
        f"Completed to date 125000.01 exceeds the contract amount 125000.00 "
        f"for job {job_id}; approve a change order to bill more")


def test_sov_derived_total_is_capped(conn, env, mod):
    job_id = _add_job(conn, env, mod, contract_amount="100000.00")
    sov_id = _add_sov(conn, env, mod, job_id)
    _seed_sov_line(conn, env["company_id"], sov_id, "1", "Foundations",
                   "200000", "100000.01", "0", "0", "10")
    before = _snapshot(conn)
    r = call_action(mod.ACTIONS["construction-add-progress-bill"], conn, ns(
        company_id=env["company_id"], job_id=job_id, sov_id=sov_id,
        total_completed=None, total_retention=None,
        period_from="2026-03-01", period_to="2026-03-31", notes=None))
    assert is_error(r), r
    assert r["message"] == (
        f"Completed to date 100000.01 exceeds the contract amount 100000.00 "
        f"for job {job_id}; approve a change order to bill more")
    assert _snapshot(conn) == before


def test_cost_plus_job_not_capped(conn, env, mod):
    job_id = _add_cost_plus_job(conn, env, mod)
    r = _add_bill(conn, env, mod, job_id, "5000.00", "500.00")
    assert is_ok(r), r
