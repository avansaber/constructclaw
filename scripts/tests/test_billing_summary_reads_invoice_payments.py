"""Billing summary paid total reads each bill's invoice payments.

construction-billing-summary no longer treats a progress bill's own
bill_status as the source of the paid figure: no action ever moves a bill to
paid, so that branch always reported 0.00 even when the bill's sales invoice
was paid in full. total_paid is now the exact Decimal sum of live
payment_allocation rows (voucher_type sales_invoice, delinked 0, parent
payment_entry submitted) per bill invoice, and each history entry carrying a
sales_invoice_id also reports amount_paid and the invoice's stored status.
"""
import uuid

import pytest

from construct_helpers import call_action, ns, is_ok, is_error
from test_progress_bill_g703 import (
    _add_job,
    _delegate_selling_in_process,
    _seed_submit_prereqs,
)
from erpclaw_lib.query import Q, P, Table, insert_row


def _add_submit_approve(conn, env, mod, job_id, completed, retention,
                        period_from, period_to):
    r = call_action(mod.ACTIONS["construction-add-progress-bill"], conn, ns(
        company_id=env["company_id"], job_id=job_id, sov_id=None,
        total_completed=completed, total_retention=retention,
        period_from=period_from, period_to=period_to, notes=None))
    assert is_ok(r), r
    pb_id = r["progress_bill_id"]
    s = call_action(mod.ACTIONS["construction-submit-progress-bill"], conn,
                    ns(progress_bill_id=pb_id))
    assert is_ok(s), s
    a = call_action(mod.ACTIONS["construction-approve-progress-bill"], conn,
                    ns(progress_bill_id=pb_id, db_path=None))
    assert is_ok(a), a
    return pb_id


def _invoice_of(conn, pb_id):
    t = Table("constructclaw_progress_bill")
    row = conn.execute(
        Q.from_(t).select(t.sales_invoice_id).where(t.id == P()).get_sql(),
        (pb_id,)).fetchone()
    assert row is not None
    return row["sales_invoice_id"]


def _two_approved_bills(conn, env, mod):
    job_id = _add_job(conn, env, mod, contract_amount="100000.00")
    b1 = _add_submit_approve(conn, env, mod, job_id,
                             "30000.00", "3000.00",
                             "2026-03-01", "2026-03-31")
    b2 = _add_submit_approve(conn, env, mod, job_id,
                             "70000.00", "7000.00",
                             "2026-04-01", "2026-04-30")
    return job_id, _invoice_of(conn, b1), _invoice_of(conn, b2)


def _pay_invoice(conn, invoice_id, amount, status="submitted", delinked=0):
    t_si = Table("sales_invoice")
    inv = conn.execute(
        Q.from_(t_si).select(t_si.star).where(t_si.id == P()).get_sql(),
        (invoice_id,)).fetchone()
    assert inv is not None
    company_id = inv["company_id"]
    customer_id = inv["customer_id"]
    t_acct = Table("account")
    accts = conn.execute(
        Q.from_(t_acct).select(t_acct.id)
        .where(t_acct.company_id == P()).orderby(t_acct.id).get_sql(),
        (company_id,)).fetchall()
    assert len(accts) >= 2
    pe_id = str(uuid.uuid4())
    pe_sql, _ = insert_row("payment_entry", {
        "id": P(), "payment_type": P(), "posting_date": P(),
        "party_type": P(), "party_id": P(),
        "paid_from_account": P(), "paid_to_account": P(),
        "paid_amount": P(), "status": P(), "company_id": P()})
    conn.execute(pe_sql, (
        pe_id, "receive", "2026-06-01", "customer", customer_id,
        accts[0]["id"], accts[1]["id"], str(amount), status, company_id))
    alloc_sql, _ = insert_row("payment_allocation", {
        "id": P(), "payment_entry_id": P(), "voucher_type": P(),
        "voucher_id": P(), "allocated_amount": P(), "delinked": P()})
    conn.execute(alloc_sql, (
        str(uuid.uuid4()), pe_id, "sales_invoice", invoice_id,
        str(amount), delinked))
    conn.commit()
    return pe_id


def _summary(conn, mod, job_id):
    return call_action(mod.ACTIONS["construction-billing-summary"], conn,
                       ns(job_id=job_id))


def _invoice_status(conn, invoice_id):
    t = Table("sales_invoice")
    return conn.execute(
        Q.from_(t).select(t.status).where(t.id == P()).get_sql(),
        (invoice_id,)).fetchone()["status"]


def test_paid_invoice_counts_as_paid(conn, env, mod, monkeypatch):
    _seed_submit_prereqs(conn, env["company_id"])
    _delegate_selling_in_process(conn, monkeypatch)
    job_id, inv1, inv2 = _two_approved_bills(conn, env, mod)
    _pay_invoice(conn, inv1, "27000.00")

    r = _summary(conn, mod, job_id)
    assert is_ok(r), r
    assert (r["total_paid"], r["total_billed"], r["total_retention"],
            r["remaining_to_bill"]) == (
        "27000.00", "63000.00", "7000.00", "30000.00")
    assert r["bill_count"] == 2
    by_number = {h["bill_number"]: h for h in r["bill_history"]}
    assert by_number[1]["amount_paid"] == "27000.00"
    assert by_number[1]["invoice_status"] == _invoice_status(conn, inv1)
    assert by_number[2]["amount_paid"] == "0.00"
    assert by_number[2]["invoice_status"] == _invoice_status(conn, inv2)


def test_partial_payment_is_exact(conn, env, mod, monkeypatch):
    _seed_submit_prereqs(conn, env["company_id"])
    _delegate_selling_in_process(conn, monkeypatch)
    job_id, inv1, inv2 = _two_approved_bills(conn, env, mod)
    _pay_invoice(conn, inv2, "12345.67")
    _pay_invoice(conn, inv2, "0.01")

    r = _summary(conn, mod, job_id)
    assert is_ok(r), r
    assert r["total_paid"] == "12345.68"


def test_draft_and_delinked_payments_do_not_count(conn, env, mod, monkeypatch):
    _seed_submit_prereqs(conn, env["company_id"])
    _delegate_selling_in_process(conn, monkeypatch)
    job_id, inv1, inv2 = _two_approved_bills(conn, env, mod)
    _pay_invoice(conn, inv1, "27000.00", status="draft")
    _pay_invoice(conn, inv1, "27000.00", delinked=1)

    r = _summary(conn, mod, job_id)
    assert is_ok(r), r
    assert r["total_paid"] == "0.00"


def test_bill_status_paid_without_invoice_is_not_paid(conn, env, mod):
    job_id = _add_job(conn, env, mod, contract_amount="100000.00")
    r = call_action(mod.ACTIONS["construction-add-progress-bill"], conn, ns(
        company_id=env["company_id"], job_id=job_id, sov_id=None,
        total_completed="20000.00", total_retention="2000.00",
        period_from="2026-03-01", period_to="2026-03-31", notes=None))
    assert is_ok(r), r
    pb_id = r["progress_bill_id"]
    conn.execute("UPDATE constructclaw_progress_bill SET bill_status = ? "
                 "WHERE id = ?", ("paid", pb_id))
    conn.commit()

    s = _summary(conn, mod, job_id)
    assert is_ok(s), s
    assert s["total_paid"] == "0.00"
    assert len(s["bill_history"]) == 1
    assert "amount_paid" not in s["bill_history"][0]
    assert "invoice_status" not in s["bill_history"][0]


def test_summary_writes_nothing(conn, env, mod, monkeypatch):
    _seed_submit_prereqs(conn, env["company_id"])
    _delegate_selling_in_process(conn, monkeypatch)
    job_id, inv1, inv2 = _two_approved_bills(conn, env, mod)
    _pay_invoice(conn, inv1, "27000.00")
    tables = ("constructclaw_progress_bill", "sales_invoice", "payment_entry",
              "payment_allocation", "gl_entry", "audit_log")
    before = {t: [tuple(r) for r in conn.execute(
        f"SELECT * FROM {t} ORDER BY rowid").fetchall()] for t in tables}

    r = _summary(conn, mod, job_id)
    assert is_ok(r), r

    after = {t: [tuple(r) for r in conn.execute(
        f"SELECT * FROM {t} ORDER BY rowid").fetchall()] for t in tables}
    assert after == before
