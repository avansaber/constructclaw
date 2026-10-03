"""Refusal tests for construction-approve-progress-bill.

Approving a progress bill means the customer has been invoiced and the
invoice is posted. A create or submit refusal leaves the bill 'submitted',
names the real cause, and links the committed draft so a retry submits it
instead of creating a second invoice.
"""
import json

import pytest

from construct_helpers import call_action, ns, is_ok, is_error, load_db_query
from test_progress_bill_g703 import (
    _add_job,
    _delegate_selling_in_process,
    _seed_submit_prereqs,
)
from erpclaw_lib import cross_skill as _cs
from erpclaw_lib.cross_skill import CrossSkillError
from erpclaw_lib.query import Q, P, Table, Field, fn

_APPROVE_ACTION = "construction-approve-progress-bill"


@pytest.fixture
def mod():
    return load_db_query()


def _submitted_bill(conn, env, mod, seed_prereqs=True):
    """Seed prerequisites unless told not to, add a header-only bill and submit it."""
    if seed_prereqs:
        _seed_submit_prereqs(conn, env["company_id"])
    job_id = _add_job(conn, env, mod)
    add_r = call_action(mod.ACTIONS["construction-add-progress-bill"], conn, ns(
        company_id=env["company_id"], job_id=job_id, sov_id=None,
        total_completed="10000.00", total_retention="1000.00",
        period_from="2026-03-01", period_to="2026-03-31", notes=None,
    ))
    assert is_ok(add_r), add_r
    pb_id = add_r["progress_bill_id"]
    sub_r = call_action(
        mod.ACTIONS["construction-submit-progress-bill"], conn,
        ns(progress_bill_id=pb_id))
    assert is_ok(sub_r), sub_r
    return pb_id


def _bill_row(conn, pb_id):
    t = Table("constructclaw_progress_bill")
    row = conn.execute(
        Q.from_(t).select(t.star).where(t.id == P()).get_sql(), (pb_id,)).fetchone()
    assert row is not None
    return dict(row)


def _count(conn, table, action=None):
    t = Table(table)
    q = Q.from_(t).select(fn.Count(t.star))
    params = []
    if action is not None:
        q = q.where(Field("action") == P())
        params.append(action)
    return conn.execute(q.get_sql(), params).fetchone()[0]


def _snapshot(conn, pb_id):
    return (
        _bill_row(conn, pb_id),
        _count(conn, "sales_invoice"),
        _count(conn, "gl_entry"),
        _count(conn, "audit_log", action=_APPROVE_ACTION),
    )


def _fail_only(monkeypatch, action, message):
    """Wrap the patched call_skill_action so one action refuses; return the wrapped fn."""
    real = _cs.call_skill_action

    def _wrapper(skill_name, act, args=None, db_path=None, timeout=30):
        if act == action:
            raise CrossSkillError(message)
        return real(skill_name, act, args=args, db_path=db_path, timeout=timeout)

    monkeypatch.setattr(_cs, "call_skill_action", _wrapper)
    return real


def _approve(conn, mod, pb_id):
    return call_action(
        mod.ACTIONS["construction-approve-progress-bill"], conn,
        ns(progress_bill_id=pb_id, db_path=None))


def test_create_failure_refuses_and_writes_nothing(conn, env, mod, monkeypatch):
    _delegate_selling_in_process(conn, monkeypatch)
    pb_id = _submitted_bill(conn, env, mod)
    bill_number = _bill_row(conn, pb_id)["bill_number"]
    before = _snapshot(conn, pb_id)
    _fail_only(monkeypatch, "create-sales-invoice", "simulated create refusal")
    r = _approve(conn, mod, pb_id)
    assert is_error(r), r
    assert r["message"] == (
        f"Sales invoice could not be created for progress bill {bill_number}: "
        "simulated create refusal")
    assert _snapshot(conn, pb_id) == before
    bill = _bill_row(conn, pb_id)
    assert bill["bill_status"] == "submitted"
    assert bill["sales_invoice_id"] is None


def test_submit_failure_refuses_and_links_the_draft(conn, env, mod, monkeypatch):
    _delegate_selling_in_process(conn, monkeypatch)
    pb_id = _submitted_bill(conn, env, mod)
    bill_number = _bill_row(conn, pb_id)["bill_number"]
    before = _snapshot(conn, pb_id)
    _fail_only(monkeypatch, "submit-sales-invoice", "simulated submit refusal")
    r = _approve(conn, mod, pb_id)
    assert is_error(r), r
    bill = _bill_row(conn, pb_id)
    si_id = bill["sales_invoice_id"]
    assert si_id, bill
    assert r["message"] == (
        f"Sales invoice {si_id} was created but could not be submitted: "
        "simulated submit refusal. The progress bill stays submitted and is "
        "linked to the draft invoice; approve it again once the cause is fixed.")
    assert bill["bill_status"] == "submitted"
    assert _count(conn, "sales_invoice") == before[1] + 1
    t = Table("sales_invoice")
    si = conn.execute(
        Q.from_(t).select(t.star).where(t.id == P()).get_sql(), (si_id,)).fetchone()
    assert si["status"] == "draft"
    assert si["grand_total"] == "9000.00"
    assert _count(conn, "gl_entry") == before[2]
    assert _count(conn, "audit_log", action=_APPROVE_ACTION) == before[3] + 1
    rows = conn.execute(
        Q.from_(Table("audit_log")).select(Table("audit_log").star)
        .where(Field("action") == P()).get_sql(), (_APPROVE_ACTION,)).fetchall()
    assert len(rows) == 1
    assert json.loads(rows[0]["old_values"]) == {"sales_invoice_id": None}
    assert json.loads(rows[0]["new_values"]) == {"sales_invoice_id": si_id}


def test_real_submit_failure_names_the_selling_cause(conn, env, mod, monkeypatch):
    _delegate_selling_in_process(conn, monkeypatch)
    pb_id = _submitted_bill(conn, env, mod, seed_prereqs=False)
    r = _approve(conn, mod, pb_id)
    assert is_error(r), r
    assert r["message"].startswith("Sales invoice "), r
    assert " was created but could not be submitted: " in r["message"], r
    _, rest = r["message"].split(" was created but could not be submitted: ", 1)
    cause, sep, _ = rest.partition(
        ". The progress bill stays submitted and is linked to the draft "
        "invoice; approve it again once the cause is fixed.")
    assert sep, r
    # The cause is the selling module's own submit refusal, verbatim.
    assert cause == "No receivable account found for company", r
    bill = _bill_row(conn, pb_id)
    assert bill["bill_status"] == "submitted"
    assert bill["sales_invoice_id"], bill


def test_retry_submits_the_linked_draft_without_a_second_invoice(
        conn, env, mod, monkeypatch):
    captured = _delegate_selling_in_process(conn, monkeypatch)
    pb_id = _submitted_bill(conn, env, mod)
    real = _fail_only(monkeypatch, "submit-sales-invoice", "simulated submit refusal")
    r1 = _approve(conn, mod, pb_id)
    assert is_error(r1), r1
    si_id = _bill_row(conn, pb_id)["sales_invoice_id"]
    assert si_id
    monkeypatch.setattr(_cs, "call_skill_action", real)
    mark = len(captured["calls"])
    r2 = _approve(conn, mod, pb_id)
    assert is_ok(r2), r2
    assert r2["bill_status"] == "approved"
    assert r2["sales_invoice_id"] == si_id
    fresh = [c["action"] for c in captured["calls"][mark:]]
    assert fresh == ["submit-sales-invoice"], fresh
    assert _count(conn, "sales_invoice") == 1
    t = Table("sales_invoice")
    si = conn.execute(
        Q.from_(t).select(t.star).where(t.id == P()).get_sql(), (si_id,)).fetchone()
    assert si["status"] == "submitted"
    acc = Table("account")
    recv_id = conn.execute(
        Q.from_(acc).select(acc.id).where(acc.account_type == P())
        .where(acc.company_id == P()).get_sql(),
        ("receivable", env["company_id"])).fetchone()["id"]
    rev_id = conn.execute(
        Q.from_(acc).select(acc.id).where(acc.account_type == P())
        .where(acc.company_id == P()).get_sql(),
        ("revenue", env["company_id"])).fetchone()["id"]
    gl = Table("gl_entry")
    rows = conn.execute(
        Q.from_(gl).select(gl.star).where(gl.voucher_type == P())
        .where(gl.voucher_id == P()).get_sql(),
        ("sales_invoice", si_id)).fetchall()
    assert len(rows) == 2
    by_account = {row["account_id"]: dict(row) for row in rows}
    assert by_account[recv_id]["debit"] == "9000.00"
    assert by_account[recv_id]["credit"] == "0.00"
    assert by_account[rev_id]["debit"] == "0.00"
    assert by_account[rev_id]["credit"] == "9000.00"


def test_submit_timeout_after_commit_approves(conn, env, mod, monkeypatch):
    _delegate_selling_in_process(conn, monkeypatch)
    pb_id = _submitted_bill(conn, env, mod)
    real = _cs.call_skill_action

    def _timeout_after_commit(skill_name, act, args=None, db_path=None, timeout=30):
        out = real(skill_name, act, args=args, db_path=db_path, timeout=timeout)
        if act == "submit-sales-invoice":
            raise CrossSkillError("erpclaw submit-sales-invoice timed out after 30s")
        return out

    monkeypatch.setattr(_cs, "call_skill_action", _timeout_after_commit)
    r = _approve(conn, mod, pb_id)
    assert is_ok(r), r
    assert r["bill_status"] == "approved"
    t = Table("sales_invoice")
    si = conn.execute(
        Q.from_(t).select(t.star).where(t.id == P()).get_sql(),
        (r["sales_invoice_id"],)).fetchone()
    assert si["status"] == "submitted"


def test_linked_invoice_in_unusable_status_refuses(conn, env, mod, monkeypatch):
    captured = _delegate_selling_in_process(conn, monkeypatch)
    pb_id = _submitted_bill(conn, env, mod)
    _fail_only(monkeypatch, "submit-sales-invoice", "simulated submit refusal")
    r1 = _approve(conn, mod, pb_id)
    assert is_error(r1), r1
    bill_number = _bill_row(conn, pb_id)["bill_number"]
    si_id = _bill_row(conn, pb_id)["sales_invoice_id"]
    assert si_id
    t = Table("sales_invoice")
    conn.execute(
        Q.update(t).set(t.status, P()).where(t.id == P()).get_sql(),
        ("cancelled", si_id))
    conn.commit()

    def _must_not_call(skill_name, act, args=None, db_path=None, timeout=30):
        raise AssertionError(f"no cross-skill call allowed, got {act}")

    monkeypatch.setattr(_cs, "call_skill_action", _must_not_call)
    mark = len(captured["calls"])
    before = _snapshot(conn, pb_id)
    r = _approve(conn, mod, pb_id)
    assert is_error(r), r
    assert r["message"] == (
        f"Progress bill {bill_number} is linked to sales invoice {si_id} "
        "in status 'cancelled'; it cannot be approved against that invoice.")
    assert _snapshot(conn, pb_id) == before
    assert len(captured["calls"]) == mark
