"""Record SOV progress and bill each period once (m736b)."""
import json
from decimal import Decimal

import pytest

from construct_helpers import call_action, ns, is_ok, is_error, load_db_query
from test_progress_bill_g703 import (
    _add_job,
    _add_sov,
    _delegate_selling_in_process,
    _seed_submit_prereqs,
)


@pytest.fixture
def mod():
    return load_db_query()


def _add_line(conn, env, mod, sov_id, item_number, description, scheduled_value, retention_pct="10"):
    r = call_action(mod.ACTIONS["construction-add-sov-line"], conn, ns(
        company_id=env["company_id"], sov_id=sov_id, description=description,
        item_number=item_number, scheduled_value=scheduled_value,
        retention_pct=retention_pct,
    ))
    assert is_ok(r), r
    return r["sov_line_id"]


def _record(conn, mod, line_id, completed, stored=None):
    kw = {"sov_line_id": line_id, "completed_to_date": completed}
    if stored is not None:
        kw["materials_stored"] = stored
    return call_action(mod.ACTIONS["construction-record-sov-progress"], conn, ns(**kw))


def _add_bill(conn, env, mod, job_id, sov_id):
    r = call_action(mod.ACTIONS["construction-add-progress-bill"], conn, ns(
        company_id=env["company_id"], job_id=job_id, sov_id=sov_id,
        total_completed=None, total_retention=None,
        period_from=None, period_to=None, notes=None,
    ))
    assert is_ok(r), r
    return r


def _submit(conn, mod, pb_id):
    r = call_action(mod.ACTIONS["construction-submit-progress-bill"], conn,
                    ns(progress_bill_id=pb_id))
    assert is_ok(r), r
    return r


def _approve(conn, mod, pb_id):
    return call_action(mod.ACTIONS["construction-approve-progress-bill"], conn,
                       ns(progress_bill_id=pb_id, db_path=None))


def _sov_line(conn, line_id):
    row = conn.execute(
        "SELECT * FROM constructclaw_sov_line WHERE id = ?", (line_id,)).fetchone()
    return dict(row)


def _bill_lines(conn, pb_id):
    rows = conn.execute(
        "SELECT * FROM constructclaw_progress_bill_line WHERE bill_id = ? ORDER BY item_number",
        (pb_id,)).fetchall()
    return [dict(r) for r in rows]


def _invoice_totals(conn, si_id):
    si = conn.execute(
        "SELECT grand_total, status FROM sales_invoice WHERE id = ?", (si_id,)).fetchone()
    gl = conn.execute(
        "SELECT debit, credit FROM gl_entry WHERE voucher_type = ? AND voucher_id = ?",
        ("sales_invoice", si_id)).fetchall()
    d = sum((Decimal(str(g["debit"])) for g in gl), Decimal("0"))
    c = sum((Decimal(str(g["credit"])) for g in gl), Decimal("0"))
    return dict(si), d, c


def _setup_worked(conn, env, mod):
    job_id = _add_job(conn, env, mod, contract_amount="100000.00")
    sov_id = _add_sov(conn, env, mod, job_id)
    framing = _add_line(conn, env, mod, sov_id, "1", "Framing", "60000.00")
    finishes = _add_line(conn, env, mod, sov_id, "2", "Finishes", "40000.00")
    return job_id, sov_id, framing, finishes


def test_worked_example_bills_each_period_once(conn, env, mod, monkeypatch):
    _seed_submit_prereqs(conn, env["company_id"])
    _delegate_selling_in_process(conn, monkeypatch)
    job_id, sov_id, framing, finishes = _setup_worked(conn, env, mod)

    r = _record(conn, mod, framing, "30000.00")
    assert is_ok(r), r
    assert r["this_period"] == "30000.00"

    b1 = _add_bill(conn, env, mod, job_id, sov_id)
    assert b1["total_completed"] == "30000.00"
    assert b1["total_retention"] == "3000.00"
    assert b1["total_previous"] == "0.00"
    assert b1["current_due"] == "27000.00"
    bl1 = _bill_lines(conn, b1["progress_bill_id"])
    assert len(bl1) == 2
    by1 = {l["item_number"]: l for l in bl1}
    assert by1["1"]["this_period"] == "30000.00"
    assert by1["1"]["previous_completed"] == "0.00"
    assert by1["1"]["total_completed"] == "30000.00"
    assert by1["2"]["this_period"] == "0.00"

    fr = _sov_line(conn, framing)
    assert fr["previous_completed"] == "30000.00"
    assert fr["this_period"] == "0"

    _submit(conn, mod, b1["progress_bill_id"])
    a1 = _approve(conn, mod, b1["progress_bill_id"])
    assert is_ok(a1), a1
    si1, d1, c1 = _invoice_totals(conn, a1["sales_invoice_id"])
    assert si1["grand_total"] == "27000.00"
    assert d1 == c1 == Decimal("27000.00")

    b2 = _add_bill(conn, env, mod, job_id, sov_id)
    assert b2["total_completed"] == "30000.00"
    assert b2["total_retention"] == "3000.00"
    assert b2["total_previous"] == "27000.00"
    assert b2["current_due"] == "0.00"
    bl2 = _bill_lines(conn, b2["progress_bill_id"])
    by2 = {l["item_number"]: l for l in bl2}
    assert by2["1"]["this_period"] == "0.00"
    assert by2["1"]["previous_completed"] == "30000.00"
    _submit(conn, mod, b2["progress_bill_id"])
    r2 = _approve(conn, mod, b2["progress_bill_id"])
    assert is_error(r2), r2
    assert r2["message"] == "Cannot approve progress bill with zero or negative current_due (0.00)"

    rr1 = _record(conn, mod, framing, "60000.00")
    assert is_ok(rr1), rr1
    rr2 = _record(conn, mod, finishes, "10000.00")
    assert is_ok(rr2), rr2

    b3 = _add_bill(conn, env, mod, job_id, sov_id)
    assert b3["total_completed"] == "70000.00"
    assert b3["total_retention"] == "7000.00"
    assert b3["total_previous"] == "27000.00"
    assert b3["current_due"] == "36000.00"
    bl3 = _bill_lines(conn, b3["progress_bill_id"])
    by3 = {l["item_number"]: l for l in bl3}
    assert by3["1"]["this_period"] == "30000.00"
    assert by3["1"]["previous_completed"] == "30000.00"
    assert by3["2"]["this_period"] == "10000.00"
    assert by3["2"]["previous_completed"] == "0.00"
    _submit(conn, mod, b3["progress_bill_id"])
    a3 = _approve(conn, mod, b3["progress_bill_id"])
    assert is_ok(a3), a3
    si3, d3, c3 = _invoice_totals(conn, a3["sales_invoice_id"])
    assert si3["grand_total"] == "36000.00"
    assert d3 == c3 == Decimal("36000.00")

    total = Decimal(si1["grand_total"]) + Decimal(si3["grand_total"])
    assert total == Decimal("63000.00")
    assert total == Decimal("70000.00") - Decimal("7000.00")


def test_materials_stored_counted_not_rolled(conn, env, mod):
    job_id = _add_job(conn, env, mod, contract_amount="100000.00")
    sov_id = _add_sov(conn, env, mod, job_id)
    framing = _add_line(conn, env, mod, sov_id, "1", "Framing", "60000.00")
    r = _record(conn, mod, framing, "20000.00", stored="5000.00")
    assert is_ok(r), r
    b1 = _add_bill(conn, env, mod, job_id, sov_id)
    assert b1["total_completed"] == "25000.00"
    assert b1["total_retention"] == "2500.00"
    assert b1["current_due"] == "22500.00"
    fr = _sov_line(conn, framing)
    assert fr["previous_completed"] == "20000.00"
    assert fr["materials_stored"] == "5000.00"
    assert fr["this_period"] == "0"
    r2 = _record(conn, mod, framing, "25000.00", stored="0")
    assert is_ok(r2), r2
    b2 = _add_bill(conn, env, mod, job_id, sov_id)
    assert b2["total_completed"] == "25000.00"
    assert b2["current_due"] == "0.00"


def _sov_snapshot(conn, line_id):
    return _sov_line(conn, line_id)


def _audit_count(conn):
    return conn.execute("SELECT COUNT(*) AS c FROM audit_log").fetchone()["c"]


def test_refusal_missing_sov_line_id(conn, env, mod):
    job_id = _add_job(conn, env, mod, contract_amount="100000.00")
    sov_id = _add_sov(conn, env, mod, job_id)
    framing = _add_line(conn, env, mod, sov_id, "1", "Framing", "60000.00")
    before_row = _sov_snapshot(conn, framing)
    before_audit = _audit_count(conn)
    r = call_action(mod.ACTIONS["construction-record-sov-progress"], conn,
                    ns(completed_to_date="100.00"))
    assert is_error(r), r
    assert r["message"] == "--sov-line-id is required"
    assert _sov_snapshot(conn, framing) == before_row
    assert _audit_count(conn) == before_audit


def test_refusal_missing_completed(conn, env, mod):
    job_id = _add_job(conn, env, mod, contract_amount="100000.00")
    sov_id = _add_sov(conn, env, mod, job_id)
    framing = _add_line(conn, env, mod, sov_id, "1", "Framing", "60000.00")
    before_row = _sov_snapshot(conn, framing)
    before_audit = _audit_count(conn)
    r = call_action(mod.ACTIONS["construction-record-sov-progress"], conn,
                    ns(sov_line_id=framing))
    assert is_error(r), r
    assert r["message"] == "--completed-to-date is required"
    assert _sov_snapshot(conn, framing) == before_row
    assert _audit_count(conn) == before_audit


def test_refusal_unknown_line(conn, env, mod):
    job_id = _add_job(conn, env, mod, contract_amount="100000.00")
    sov_id = _add_sov(conn, env, mod, job_id)
    framing = _add_line(conn, env, mod, sov_id, "1", "Framing", "60000.00")
    before_row = _sov_snapshot(conn, framing)
    before_audit = _audit_count(conn)
    r = call_action(mod.ACTIONS["construction-record-sov-progress"], conn,
                    ns(sov_line_id="no-such-id", completed_to_date="100.00"))
    assert is_error(r), r
    assert r["message"] == "SOV line no-such-id not found"
    assert _sov_snapshot(conn, framing) == before_row
    assert _audit_count(conn) == before_audit


def test_refusal_negative(conn, env, mod):
    job_id = _add_job(conn, env, mod, contract_amount="100000.00")
    sov_id = _add_sov(conn, env, mod, job_id)
    framing = _add_line(conn, env, mod, sov_id, "1", "Framing", "60000.00")
    before_row = _sov_snapshot(conn, framing)
    before_audit = _audit_count(conn)
    r = call_action(mod.ACTIONS["construction-record-sov-progress"], conn,
                    ns(sov_line_id=framing, completed_to_date="-1"))
    assert is_error(r), r
    assert r["message"] == "--completed-to-date must be a non-negative amount"
    assert _sov_snapshot(conn, framing) == before_row
    assert _audit_count(conn) == before_audit


def test_refusal_negative_materials(conn, env, mod):
    job_id = _add_job(conn, env, mod, contract_amount="100000.00")
    sov_id = _add_sov(conn, env, mod, job_id)
    framing = _add_line(conn, env, mod, sov_id, "1", "Framing", "60000.00")
    before_row = _sov_snapshot(conn, framing)
    before_audit = _audit_count(conn)
    r = call_action(mod.ACTIONS["construction-record-sov-progress"], conn,
                    ns(sov_line_id=framing, completed_to_date="100.00", materials_stored="-5"))
    assert is_error(r), r
    assert r["message"] == "--materials-stored must be a non-negative amount"
    assert _sov_snapshot(conn, framing) == before_row
    assert _audit_count(conn) == before_audit


def test_refusal_below_previous(conn, env, mod):
    job_id = _add_job(conn, env, mod, contract_amount="100000.00")
    sov_id = _add_sov(conn, env, mod, job_id)
    framing = _add_line(conn, env, mod, sov_id, "1", "Framing", "60000.00")
    assert is_ok(_record(conn, mod, framing, "30000.00"))
    _add_bill(conn, env, mod, job_id, sov_id)
    before_row = _sov_snapshot(conn, framing)
    before_audit = _audit_count(conn)
    r = _record(conn, mod, framing, "29999.99")
    assert is_error(r), r
    assert r["message"] == "Completed to date 29999.99 is below the 30000.00 already billed on SOV line 1"
    assert _sov_snapshot(conn, framing) == before_row
    assert _audit_count(conn) == before_audit


def test_refusal_above_line(conn, env, mod):
    job_id = _add_job(conn, env, mod, contract_amount="100000.00")
    sov_id = _add_sov(conn, env, mod, job_id)
    framing = _add_line(conn, env, mod, sov_id, "1", "Framing", "60000.00")
    before_row = _sov_snapshot(conn, framing)
    before_audit = _audit_count(conn)
    r = _record(conn, mod, framing, "60000.00", stored="0.01")
    assert is_error(r), r
    assert r["message"] == "Completed to date 60000.00 plus materials stored 0.01 exceeds the scheduled value 60000.00 of SOV line 1"
    assert _sov_snapshot(conn, framing) == before_row
    assert _audit_count(conn) == before_audit


def test_record_audit_row(conn, env, mod):
    job_id = _add_job(conn, env, mod, contract_amount="100000.00")
    sov_id = _add_sov(conn, env, mod, job_id)
    framing = _add_line(conn, env, mod, sov_id, "1", "Framing", "60000.00")
    r = _record(conn, mod, framing, "30000.00")
    assert is_ok(r), r
    rows = conn.execute(
        "SELECT * FROM audit_log WHERE action = ? AND entity_type = ? AND entity_id = ?",
        ("construction-record-sov-progress", "constructclaw_sov_line", framing)).fetchall()
    assert len(rows) == 1
    new_values = json.loads(dict(rows[0])["new_values"])
    assert new_values["this_period"] == "30000.00"


def test_rerecord_before_bill_replaces(conn, env, mod):
    job_id = _add_job(conn, env, mod, contract_amount="100000.00")
    sov_id = _add_sov(conn, env, mod, job_id)
    framing = _add_line(conn, env, mod, sov_id, "1", "Framing", "60000.00")
    assert is_ok(_record(conn, mod, framing, "30000.00"))
    r = _record(conn, mod, framing, "25000.00")
    assert is_ok(r), r
    assert r["this_period"] == "25000.00"
    assert _sov_line(conn, framing)["this_period"] == "25000.00"


def test_skill_row_present():
    import os
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "SKILL.md")
    # tests run with cwd at repo root or module dir; fall back to source path
    if not os.path.isfile(path):
        path = "source/constructclaw/SKILL.md"
    text = open(path).read()
    assert "construction-record-sov-progress" in text
    assert len(text.splitlines()) <= 300
