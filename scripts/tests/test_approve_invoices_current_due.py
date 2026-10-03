"""Current-due invoicing for construction-approve-progress-bill.

Approving a progress bill invoices exactly the bill's current_due on one
invoice line, whether the bill was built from flat totals or G703 lines.
"""
from decimal import Decimal

import pytest

from construct_helpers import call_action, ns, is_ok, is_error, load_db_query
from test_progress_bill_g703 import (
    _add_job,
    _add_sov,
    _seed_sov_line,
    _delegate_selling_in_process,
    _seed_submit_prereqs,
)


@pytest.fixture
def mod():
    return load_db_query()


def _add_sov_bill(conn, env, mod, job_id, sov_id):
    r = call_action(mod.ACTIONS["construction-add-progress-bill"], conn, ns(
        company_id=env["company_id"], job_id=job_id, sov_id=sov_id,
        total_completed=None, total_retention=None,
        period_from="2026-03-01", period_to="2026-03-31", notes=None,
    ))
    assert is_ok(r), r
    return r


def _submit(conn, mod, pb_id):
    r = call_action(
        mod.ACTIONS["construction-submit-progress-bill"], conn,
        ns(progress_bill_id=pb_id))
    assert is_ok(r), r
    return r


def _approve(conn, mod, pb_id):
    return call_action(
        mod.ACTIONS["construction-approve-progress-bill"], conn,
        ns(progress_bill_id=pb_id, db_path=None))


def _seed_framing_bill(conn, env, mod, job_id):
    sov_id = _add_sov(conn, env, mod, job_id)
    _seed_sov_line(conn, env["company_id"], sov_id, "1", "Framing",
                   "60000.00", "0", "30000.00", "0", "10")
    return sov_id


def test_sov_bill_invoices_current_due(conn, env, mod, monkeypatch):
    _seed_submit_prereqs(conn, env["company_id"])
    _delegate_selling_in_process(conn, monkeypatch)
    job_id = _add_job(conn, env, mod, contract_amount="100000.00")
    sov_id = _seed_framing_bill(conn, env, mod, job_id)
    add_r = _add_sov_bill(conn, env, mod, job_id, sov_id)
    assert add_r["current_due"] == "27000.00"
    pb_id = add_r["progress_bill_id"]
    _submit(conn, mod, pb_id)
    r = _approve(conn, mod, pb_id)
    assert is_ok(r), r
    si_id = r["sales_invoice_id"]
    si = conn.execute(
        "SELECT grand_total, status FROM sales_invoice WHERE id = ?",
        (si_id,)).fetchone()
    assert si["grand_total"] == "27000.00"
    assert si["status"] == "submitted"
    items = conn.execute(
        "SELECT rate FROM sales_invoice_item WHERE sales_invoice_id = ?",
        (si_id,)).fetchall()
    assert len(items) == 1
    assert items[0]["rate"] == "27000.00"
    gl = conn.execute(
        "SELECT debit, credit FROM gl_entry WHERE voucher_type = ? AND voucher_id = ?",
        ("sales_invoice", si_id)).fetchall()
    assert len(gl) > 0
    debit_sum = sum((Decimal(str(g["debit"])) for g in gl), Decimal("0"))
    credit_sum = sum((Decimal(str(g["credit"])) for g in gl), Decimal("0"))
    assert debit_sum == credit_sum
    assert debit_sum == Decimal("27000.00")
    assert credit_sum == Decimal("27000.00")


def test_materials_stored_and_multi_line(conn, env, mod, monkeypatch):
    _seed_submit_prereqs(conn, env["company_id"])
    _delegate_selling_in_process(conn, monkeypatch)
    job_id = _add_job(conn, env, mod, contract_amount="100000.00")
    sov_id = _add_sov(conn, env, mod, job_id)
    _seed_sov_line(conn, env["company_id"], sov_id, "1", "Framing",
                   "60000.00", "0", "20000.00", "5000.00", "10")
    _seed_sov_line(conn, env["company_id"], sov_id, "2", "Finishes",
                   "20000.00", "0", "3333.33", "0", "10")
    add_r = _add_sov_bill(conn, env, mod, job_id, sov_id)
    assert add_r["total_completed"] == "28333.33"
    assert add_r["total_retention"] == "2833.33"
    assert add_r["current_due"] == "25500.00"
    pb_id = add_r["progress_bill_id"]
    lines_before = conn.execute(
        "SELECT * FROM constructclaw_progress_bill_line WHERE bill_id = ? ORDER BY item_number",
        (pb_id,)).fetchall()
    assert len(lines_before) == 2
    by_desc = {dict(l)["description"]: dict(l) for l in lines_before}
    assert by_desc["Framing"]["retention_amount"] == "2500.00"
    assert by_desc["Finishes"]["retention_amount"] == "333.33"
    before_rows = [tuple(str(v) for v in tuple(l)) for l in lines_before]
    _submit(conn, mod, pb_id)
    r = _approve(conn, mod, pb_id)
    assert is_ok(r), r
    si = conn.execute(
        "SELECT grand_total, status FROM sales_invoice WHERE id = ?",
        (r["sales_invoice_id"],)).fetchone()
    assert si["grand_total"] == "25500.00"
    assert si["status"] == "submitted"
    lines_after = conn.execute(
        "SELECT * FROM constructclaw_progress_bill_line WHERE bill_id = ? ORDER BY item_number",
        (pb_id,)).fetchall()
    after_rows = [tuple(str(v) for v in tuple(l)) for l in lines_after]
    assert after_rows == before_rows


def test_second_bill_nets_previous_due(conn, env, mod, monkeypatch):
    _seed_submit_prereqs(conn, env["company_id"])
    _delegate_selling_in_process(conn, monkeypatch)
    job_id = _add_job(conn, env, mod, contract_amount="100000.00")
    sov1 = _seed_framing_bill(conn, env, mod, job_id)
    add1 = _add_sov_bill(conn, env, mod, job_id, sov1)
    assert add1["current_due"] == "27000.00"
    _submit(conn, mod, add1["progress_bill_id"])
    r1 = _approve(conn, mod, add1["progress_bill_id"])
    assert is_ok(r1), r1
    sov2 = _add_sov(conn, env, mod, job_id, name="Second SOV")
    _seed_sov_line(conn, env["company_id"], sov2, "1", "Framing",
                   "120000.00", "30000.00", "30000.00", "0", "10")
    add2 = _add_sov_bill(conn, env, mod, job_id, sov2)
    assert add2["current_due"] == "27000.00"
    _submit(conn, mod, add2["progress_bill_id"])
    r2 = _approve(conn, mod, add2["progress_bill_id"])
    assert is_ok(r2), r2
    si = conn.execute(
        "SELECT grand_total, status FROM sales_invoice WHERE id = ?",
        (r2["sales_invoice_id"],)).fetchone()
    assert si["grand_total"] == "27000.00"
    assert si["status"] == "submitted"


def test_header_not_footing_refused(conn, env, mod, monkeypatch):
    _seed_submit_prereqs(conn, env["company_id"])
    _delegate_selling_in_process(conn, monkeypatch)
    job_id = _add_job(conn, env, mod, contract_amount="100000.00")
    sov_id = _seed_framing_bill(conn, env, mod, job_id)
    add_r = _add_sov_bill(conn, env, mod, job_id, sov_id)
    pb_id = add_r["progress_bill_id"]
    bill_number = add_r["bill_number"]
    conn.execute(
        "UPDATE constructclaw_progress_bill_line SET retention_amount = ? WHERE bill_id = ?",
        ("0.00", pb_id))
    conn.commit()
    _submit(conn, mod, pb_id)
    before_si = conn.execute("SELECT COUNT(*) AS c FROM sales_invoice").fetchone()["c"]
    before_gl = conn.execute("SELECT COUNT(*) AS c FROM gl_entry").fetchone()["c"]
    before_audit = conn.execute("SELECT COUNT(*) AS c FROM audit_log").fetchone()["c"]
    r = _approve(conn, mod, pb_id)
    assert is_error(r), r
    assert r["message"] == (
        f"Progress bill {bill_number} does not foot to its G703 lines; "
        "it cannot be invoiced")
    bill = conn.execute(
        "SELECT bill_status, sales_invoice_id FROM constructclaw_progress_bill WHERE id = ?",
        (pb_id,)).fetchone()
    assert bill["bill_status"] == "submitted"
    assert bill["sales_invoice_id"] is None
    assert conn.execute("SELECT COUNT(*) AS c FROM sales_invoice").fetchone()["c"] == before_si
    assert conn.execute("SELECT COUNT(*) AS c FROM gl_entry").fetchone()["c"] == before_gl
    assert conn.execute("SELECT COUNT(*) AS c FROM audit_log").fetchone()["c"] == before_audit


def test_linked_draft_with_wrong_amount_refused(conn, env, mod, monkeypatch):
    import argparse
    import importlib.util
    import io
    import json as _json
    import os as _os
    from unittest.mock import patch as _patch
    from construct_helpers import SRC_DIR as _SRC
    from erpclaw_lib import cross_skill as _cs

    _seed_submit_prereqs(conn, env["company_id"])
    _delegate_selling_in_process(conn, monkeypatch)
    job_id = _add_job(conn, env, mod, contract_amount="100000.00")
    sov_id = _seed_framing_bill(conn, env, mod, job_id)
    add_r = _add_sov_bill(conn, env, mod, job_id, sov_id)
    assert add_r["current_due"] == "27000.00"
    pb_id = add_r["progress_bill_id"]
    bill_number = add_r["bill_number"]
    _submit(conn, mod, pb_id)
    draft_result = _cs.create_invoice(
        customer_id=env["customer_id"],
        items=[{"description": "stale", "qty": "1", "rate": "30000.00"}],
        company_id=env["company_id"],
        db_path=None,
    )
    draft_data = draft_result.get("sales_invoice", draft_result)
    draft_id = draft_data.get("id") or draft_data.get("sales_invoice_id")
    assert draft_id
    draft = conn.execute(
        "SELECT grand_total, status FROM sales_invoice WHERE id = ?",
        (draft_id,)).fetchone()
    assert draft["grand_total"] == "30000.00"
    assert draft["status"] == "draft"
    conn.execute(
        "UPDATE constructclaw_progress_bill SET sales_invoice_id = ? WHERE id = ?",
        (draft_id, pb_id))
    conn.commit()
    before_gl = conn.execute("SELECT COUNT(*) AS c FROM gl_entry").fetchone()["c"]
    r = _approve(conn, mod, pb_id)
    assert is_error(r), r
    assert r["message"] == (
        f"Progress bill {bill_number} is linked to draft sales invoice {draft_id} "
        "for 30000.00, not its current due 27000.00; "
        "delete that draft and approve again")
    still = conn.execute(
        "SELECT status FROM sales_invoice WHERE id = ?",
        (draft_id,)).fetchone()
    assert still["status"] == "draft"
    assert conn.execute("SELECT COUNT(*) AS c FROM gl_entry").fetchone()["c"] == before_gl

    path = _os.path.join(_SRC, "erpclaw", "scripts", "erpclaw-selling", "db_query.py")
    spec = importlib.util.spec_from_file_location("_fnd_selling_delete", path)
    selling = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(selling)
    buf = io.StringIO()

    def _fake_exit(code=0):
        raise SystemExit(code)

    try:
        with _patch("sys.stdout", buf), _patch("sys.exit", side_effect=_fake_exit):
            selling.delete_sales_invoice(
                conn, argparse.Namespace(sales_invoice_id=draft_id))
    except SystemExit:
        pass
    deleted = _json.loads(buf.getvalue().strip())
    assert deleted.get("status") == "ok", deleted
    assert conn.execute(
        "SELECT COUNT(*) AS c FROM sales_invoice WHERE id = ?",
        (draft_id,)).fetchone()["c"] == 0

    r2 = _approve(conn, mod, pb_id)
    assert is_ok(r2), r2
    assert r2["sales_invoice_id"] != draft_id
    si = conn.execute(
        "SELECT grand_total, status FROM sales_invoice WHERE id = ?",
        (r2["sales_invoice_id"],)).fetchone()
    assert si["grand_total"] == "27000.00"
    assert si["status"] == "submitted"
    bill = conn.execute(
        "SELECT bill_status, sales_invoice_id FROM constructclaw_progress_bill WHERE id = ?",
        (pb_id,)).fetchone()
    assert bill["bill_status"] == "approved"
    assert bill["sales_invoice_id"] == r2["sales_invoice_id"]
    assert conn.execute("SELECT COUNT(*) AS c FROM sales_invoice").fetchone()["c"] == 1
