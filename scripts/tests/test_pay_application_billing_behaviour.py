"""Part A: behaviour of subcontractor pay applications, the job billing
summary and batch cost codes, read back from the database.

construction-add-pay-application is pinned by the row it writes: work
completed and materials stored as given, total earned, retention held at the
subcontract's retention percent (rounded half-up to the cent), previous
payments and current payment due, all as exact strings. A pay application's
work completed is cumulative to date, so each later application nets off what
approved applications already certified; three applications that reach the
full subcontract pay exactly the subcontract less its retention.
construction-approve-pay-application and construction-reject-pay-application
are pinned by the status they write and by their refusals once an application
has left draft. construction-get-pay-application and
construction-list-pay-applications are pinned by the stored values they return
and by their filters.

construction-billing-summary is pinned by exact totals over progress bills
this file creates: billed (the sum of each bill's current due), retention (the
latest bill's), paid (from the bills' invoice payments), and remaining to bill,
with rejected bills left out.

construction-batch-add-cost-codes is pinned by the rows and the single audit
row it writes, and by its refusals. A refusal part-way through a batch writes
nothing: the rows the batch already inserted are rolled back.

All document dates are fixed. No handler here posts to the general ledger.
"""
import json
from decimal import Decimal

import pytest

from construct_helpers import call_action, is_error, is_ok, ns
from buying_harness import delegate_buying_in_process, seed_supplier

PA_COLS = ("subcontract_id", "application_number", "period_from", "period_to",
           "work_completed", "materials_stored", "total_earned",
           "retention_held", "previous_payments", "current_payment_due",
           "pay_app_status", "company_id")


@pytest.fixture(autouse=True)
def _buying_bridge(conn, monkeypatch):
    """Setup only: approvals post their payable through the buying module."""
    return delegate_buying_in_process(conn, monkeypatch)


# ── helpers ────────────────────────────────────────────────────────────────

def _job(conn, env, mod, name="Pay App Job", contract_amount="100000.00"):
    r = call_action(mod.ACTIONS["construction-add-job"], conn, ns(
        company_id=env["company_id"], name=name,
        job_type=None, contract_type=None, contract_amount=contract_amount,
        client_name=None, client_id=env["customer_id"], description=None,
        project_manager=None, superintendent=None,
        start_date="2026-01-05", end_date="2026-12-18", address=None,
        city=None, state=None, zip_code=None, notes=None))
    assert is_ok(r), r
    return r["job_id"]


def _sub(conn, env, mod, job_id, name="Summit Mechanical",
         amount="100000.00", retention_pct="10"):
    supplier_id = seed_supplier(conn, env["company_id"])
    r = call_action(mod.ACTIONS["construction-add-subcontract"], conn, ns(
        company_id=env["company_id"], job_id=job_id,
        subcontractor_name=name, trade="hvac", scope_of_work=None,
        original_amount=amount, retention_pct=retention_pct,
        insurance_expiry=None, license_number=None,
        start_date="2026-01-12", end_date="2026-11-30", notes=None,
        supplier_id=supplier_id))
    assert is_ok(r), r
    return r["subcontract_id"]


def _pay_app(conn, env, mod, sub_id, work_completed, materials_stored="0",
             period_from="2026-03-01", period_to="2026-03-31"):
    return call_action(mod.ACTIONS["construction-add-pay-application"], conn, ns(
        company_id=env["company_id"], subcontract_id=sub_id,
        work_completed=work_completed, materials_stored=materials_stored,
        period_from=period_from, period_to=period_to, notes=None))


def _approve(conn, mod, pa_id):
    return call_action(mod.ACTIONS["construction-approve-pay-application"], conn,
                       ns(pay_application_id=pa_id))


def _reject(conn, mod, pa_id):
    return call_action(mod.ACTIONS["construction-reject-pay-application"], conn,
                       ns(pay_application_id=pa_id, notes="Lien waiver missing"))


def _pa_row(conn, pa_id):
    row = conn.execute(
        "SELECT " + ", ".join(PA_COLS) +
        " FROM constructclaw_pay_application WHERE id = ?", (pa_id,)).fetchone()
    return tuple(row) if row else None


def _pa_count(conn):
    return conn.execute(
        "SELECT COUNT(*) FROM constructclaw_pay_application").fetchone()[0]


def _audit_rows(conn, action, entity_id):
    return [tuple(r) for r in conn.execute(
        "SELECT entity_type, new_values FROM audit_log "
        "WHERE action = ? AND entity_id = ?", (action, entity_id)).fetchall()]


def _bill(conn, env, mod, job_id, completed, retention, period_from, period_to):
    r = call_action(mod.ACTIONS["construction-add-progress-bill"], conn, ns(
        company_id=env["company_id"], job_id=job_id, sov_id=None,
        total_completed=completed, total_retention=retention,
        period_from=period_from, period_to=period_to, notes=None))
    assert is_ok(r), r
    return r["progress_bill_id"]


def _set_bill_status(conn, bill_id, status):
    # No action moves a progress bill to paid or rejected; seed the status.
    conn.execute("UPDATE constructclaw_progress_bill SET bill_status = ? "
                 "WHERE id = ?", (status, bill_id))
    conn.commit()


def _summary(conn, mod, job_id):
    return call_action(mod.ACTIONS["construction-billing-summary"], conn,
                       ns(job_id=job_id))


def _cost_codes(conn, job_id):
    return [tuple(r) for r in conn.execute(
        "SELECT code, description, category, budget_amount, budget_hours, "
        "is_active, company_id FROM constructclaw_cost_code "
        "WHERE job_id = ? ORDER BY code", (job_id,)).fetchall()]


def _batch(conn, env, mod, job_id, codes):
    return call_action(mod.ACTIONS["construction-batch-add-cost-codes"], conn, ns(
        company_id=env["company_id"], job_id=job_id,
        codes_json=codes if codes is None else json.dumps(codes)))


# ── construction-add-pay-application ───────────────────────────────────────

def test_first_pay_application_writes_earned_retention_and_due(conn, env, mod):
    job_id = _job(conn, env, mod)
    sub_id = _sub(conn, env, mod, job_id)
    r = _pay_app(conn, env, mod, sub_id, "20000.00", "1500.00")
    assert is_ok(r), r
    pa_id = r["pay_application_id"]
    assert r["naming_series"].startswith("CCPA-")
    assert _pa_row(conn, pa_id) == (
        sub_id, 1, "2026-03-01", "2026-03-31", "20000.00", "1500.00",
        "21500.00", "2150.00", "0.00", "19350.00", "draft", env["company_id"])
    assert (r["total_earned"], r["retention_held"], r["current_payment_due"]) == (
        "21500.00", "2150.00", "19350.00")
    audits = _audit_rows(conn, "construction-add-pay-application", pa_id)
    assert len(audits) == 1
    assert audits[0][0] == "constructclaw_pay_application"
    assert json.loads(audits[0][1]) == {"application_number": 1,
                                        "current_payment_due": "19350.00"}


def test_retention_is_rounded_half_up_to_the_cent(conn, env, mod):
    job_id = _job(conn, env, mod)
    sub_id = _sub(conn, env, mod, job_id, amount="50000.00", retention_pct="5")
    r = _pay_app(conn, env, mod, sub_id, "1234.50")
    assert is_ok(r), r
    # 5% of 1234.50 is 61.725: half-up gives 61.73 (half-even would give 61.72).
    assert _pa_row(conn, r["pay_application_id"])[6:10] == (
        "1234.50", "61.73", "0.00", "1172.77")


def test_later_applications_net_off_approved_certificates(conn, env, mod):
    job_id = _job(conn, env, mod)
    sub_id = _sub(conn, env, mod, job_id)

    first = _pay_app(conn, env, mod, sub_id, "20000.00", "1500.00")
    assert is_ok(_approve(conn, mod, first["pay_application_id"]))

    second = _pay_app(conn, env, mod, sub_id, "50000.00", "2500.00",
                      "2026-04-01", "2026-04-30")
    assert is_ok(second), second
    assert _pa_row(conn, second["pay_application_id"]) == (
        sub_id, 2, "2026-04-01", "2026-04-30", "50000.00", "2500.00",
        "52500.00", "5250.00", "19350.00", "27900.00", "draft",
        env["company_id"])
    assert is_ok(_approve(conn, mod, second["pay_application_id"]))

    third = _pay_app(conn, env, mod, sub_id, "100000.00", "0",
                     "2026-05-01", "2026-05-31")
    assert is_ok(third), third
    assert _pa_row(conn, third["pay_application_id"])[1:2] + \
        _pa_row(conn, third["pay_application_id"])[4:11] == (
            3, "100000.00", "0", "100000.00", "10000.00", "47250.00",
            "42750.00", "draft")
    assert is_ok(_approve(conn, mod, third["pay_application_id"]))

    # Three certificates for the whole subcontract pay it less its retention.
    dues = [r[0] for r in conn.execute(
        "SELECT current_payment_due FROM constructclaw_pay_application "
        "WHERE subcontract_id = ? AND pay_app_status = 'approved' "
        "ORDER BY application_number", (sub_id,)).fetchall()]
    assert dues == ["19350.00", "27900.00", "42750.00"]
    assert str(sum(Decimal(d) for d in dues)) == "90000.00"


def test_rejected_application_is_not_a_previous_certificate(conn, env, mod):
    job_id = _job(conn, env, mod)
    sub_id = _sub(conn, env, mod, job_id)
    first = _pay_app(conn, env, mod, sub_id, "30000.00")
    r = _reject(conn, mod, first["pay_application_id"])
    assert is_ok(r), r
    assert _pa_row(conn, first["pay_application_id"])[10] == "rejected"

    second = _pay_app(conn, env, mod, sub_id, "30000.00", "0",
                      "2026-04-01", "2026-04-30")
    assert is_ok(second), second
    assert _pa_row(conn, second["pay_application_id"])[1:2] + \
        _pa_row(conn, second["pay_application_id"])[6:10] == (
            2, "30000.00", "3000.00", "0.00", "27000.00")


def test_add_pay_application_refusals_write_nothing(conn, env, mod):
    job_id = _job(conn, env, mod)
    sub_id = _sub(conn, env, mod, job_id)
    add = mod.ACTIONS["construction-add-pay-application"]
    cases = [
        (dict(company_id=None, subcontract_id=sub_id), "--company-id is required"),
        (dict(company_id=env["company_id"], subcontract_id=None),
         "--subcontract-id is required"),
        (dict(company_id=env["company_id"], subcontract_id="no-such-sub"),
         "Subcontract no-such-sub not found"),
    ]
    for kwargs, message in cases:
        r = call_action(add, conn, ns(work_completed="1000.00",
                                      materials_stored="0", period_from=None,
                                      period_to=None, notes=None, **kwargs))
        assert is_error(r), r
        assert r["message"] == message
    assert _pa_count(conn) == 0
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = ?",
                        ("construction-add-pay-application",)).fetchone()[0] == 0


# ── construction-approve / reject-pay-application ──────────────────────────

def test_approve_and_reject_refuse_an_application_that_left_draft(conn, env, mod):
    job_id = _job(conn, env, mod)
    sub_id = _sub(conn, env, mod, job_id)
    approved = _pay_app(conn, env, mod, sub_id, "10000.00")["pay_application_id"]
    r = _approve(conn, mod, approved)
    assert is_ok(r), r
    assert _pa_row(conn, approved)[10] == "approved"
    assert len(_audit_rows(conn, "construction-approve-pay-application", approved)) == 1
    before = _pa_row(conn, approved)

    r = _approve(conn, mod, approved)
    assert is_error(r)
    assert r["message"] == ("Pay application must be draft or submitted to "
                            "approve (current: approved)")
    r = _reject(conn, mod, approved)
    assert is_error(r)
    assert r["message"] == ("Pay application must be draft or submitted to "
                            "reject (current: approved)")
    assert _pa_row(conn, approved) == before
    assert len(_audit_rows(conn, "construction-approve-pay-application", approved)) == 1
    assert _audit_rows(conn, "construction-reject-pay-application", approved) == []

    rejected = _pay_app(conn, env, mod, sub_id, "12000.00")["pay_application_id"]
    assert is_ok(_reject(conn, mod, rejected))
    r = _approve(conn, mod, rejected)
    assert is_error(r)
    assert r["message"] == ("Pay application must be draft or submitted to "
                            "approve (current: rejected)")
    assert _pa_row(conn, rejected)[10] == "rejected"

    r = _approve(conn, mod, "no-such-app")
    assert is_error(r)
    assert r["message"] == "Pay application no-such-app not found"
    r = _approve(conn, mod, None)
    assert is_error(r)
    assert r["message"] == "--pay-application-id is required"


# ── construction-get-pay-application ────────────────────────────────────────

def test_get_pay_application_returns_the_stored_figures(conn, env, mod):
    job_id = _job(conn, env, mod)
    sub_id = _sub(conn, env, mod, job_id)
    pa_id = _pay_app(conn, env, mod, sub_id, "20000.00", "1500.00")["pay_application_id"]
    get = mod.ACTIONS["construction-get-pay-application"]
    r = call_action(get, conn, ns(pay_application_id=pa_id))
    assert is_ok(r), r
    assert tuple(r[c] for c in PA_COLS) == _pa_row(conn, pa_id)
    assert (r["total_earned"], r["retention_held"], r["previous_payments"],
            r["current_payment_due"]) == ("21500.00", "2150.00", "0.00", "19350.00")

    r = call_action(get, conn, ns(pay_application_id="no-such-app"))
    assert is_error(r)
    assert r["message"] == "Pay application no-such-app not found"
    r = call_action(get, conn, ns(pay_application_id=None))
    assert is_error(r)
    assert r["message"] == "--pay-application-id is required"


# ── construction-list-pay-applications ──────────────────────────────────────

def test_list_pay_applications_filters_and_orders(conn, env, mod):
    job_id = _job(conn, env, mod)
    sub_a = _sub(conn, env, mod, job_id, name="Summit Mechanical")
    sub_b = _sub(conn, env, mod, job_id, name="Ridge Electric",
                 amount="40000.00", retention_pct="5")
    a1 = _pay_app(conn, env, mod, sub_a, "20000.00", "1500.00")["pay_application_id"]
    assert is_ok(_approve(conn, mod, a1))
    a2 = _pay_app(conn, env, mod, sub_a, "50000.00", "2500.00")["pay_application_id"]
    b1 = _pay_app(conn, env, mod, sub_b, "8000.00")["pay_application_id"]

    lst = mod.ACTIONS["construction-list-pay-applications"]
    r = call_action(lst, conn, ns(subcontract_id=sub_a, company_id=None,
                                  pay_app_status=None))
    assert is_ok(r), r
    assert r["total_count"] == 2
    assert [(x["id"], x["application_number"], x["total_earned"],
             x["retention_held"], x["previous_payments"],
             x["current_payment_due"], x["pay_app_status"])
            for x in r["pay_applications"]] == [
        (a2, 2, "52500.00", "5250.00", "19350.00", "27900.00", "draft"),
        (a1, 1, "21500.00", "2150.00", "0.00", "19350.00", "approved"),
    ]

    r = call_action(lst, conn, ns(subcontract_id=None,
                                  company_id=env["company_id"],
                                  pay_app_status="draft"))
    assert is_ok(r), r
    assert r["total_count"] == 2
    assert {(x["id"], x["current_payment_due"]) for x in r["pay_applications"]} == {
        (a2, "27900.00"), (b1, "7600.00")}

    r = call_action(lst, conn, ns(subcontract_id=sub_b, company_id=None,
                                  pay_app_status="approved"))
    assert is_ok(r), r
    assert (r["total_count"], r["pay_applications"]) == (0, [])


# ── construction-billing-summary ────────────────────────────────────────────

def test_billing_summary_totals_over_the_jobs_bills(conn, env, mod):
    job_id = _job(conn, env, mod, contract_amount="100000.00")
    b1 = _bill(conn, env, mod, job_id, "20000.00", "2000.00", "2026-03-01", "2026-03-31")
    _bill(conn, env, mod, job_id, "50000.00", "5000.00", "2026-04-01", "2026-04-30")
    b3 = _bill(conn, env, mod, job_id, "70000.00", "7000.00", "2026-05-01", "2026-05-31")
    assert [tuple(r) for r in conn.execute(
        "SELECT bill_number, total_previous, current_due FROM "
        "constructclaw_progress_bill WHERE job_id = ? ORDER BY bill_number",
        (job_id,)).fetchall()] == [
        (1, "0.00", "18000.00"), (2, "18000.00", "27000.00"),
        (3, "45000.00", "18000.00")]
    _set_bill_status(conn, b1, "paid")
    _set_bill_status(conn, b3, "rejected")

    r = _summary(conn, mod, job_id)
    assert is_ok(r), r
    assert (r["job_name"], r["contract_amount"], r["total_billed"],
            r["total_retention"], r["total_paid"], r["remaining_to_bill"],
            r["bill_count"]) == (
        "Pay App Job", "100000.00", "45000.00", "5000.00", "0.00",
        "50000.00", 2)
    assert r["bill_history"] == [
        {"bill_number": 1, "bill_status": "paid", "current_due": "18000.00",
         "period_from": "2026-03-01", "period_to": "2026-03-31"},
        {"bill_number": 2, "bill_status": "draft", "current_due": "27000.00",
         "period_from": "2026-04-01", "period_to": "2026-04-30"},
    ]

    # The rejected bill is not a previous certificate for the next bill either.
    b4 = _bill(conn, env, mod, job_id, "70000.00", "7000.00", "2026-05-01", "2026-05-31")
    assert tuple(conn.execute(
        "SELECT bill_number, total_previous, current_due FROM "
        "constructclaw_progress_bill WHERE id = ?", (b4,)).fetchone()) == (
        4, "45000.00", "18000.00")
    r = _summary(conn, mod, job_id)
    assert (r["total_billed"], r["total_retention"], r["total_paid"],
            r["remaining_to_bill"], r["bill_count"]) == (
        "63000.00", "7000.00", "0.00", "30000.00", 3)
    assert [h["bill_number"] for h in r["bill_history"]] == [1, 2, 4]


def test_billing_summary_for_a_job_with_no_bills_and_refusals(conn, env, mod):
    job_id = _job(conn, env, mod, name="Unbilled Job", contract_amount="75000.50")
    r = _summary(conn, mod, job_id)
    assert is_ok(r), r
    assert (r["contract_amount"], r["total_billed"], r["total_retention"],
            r["total_paid"], r["remaining_to_bill"], r["bill_count"],
            r["bill_history"]) == (
        "75000.50", "0.00", "0.00", "0.00", "75000.50", 0, [])

    r = _summary(conn, mod, "no-such-job")
    assert is_error(r)
    assert r["message"] == "Job no-such-job not found"
    r = _summary(conn, mod, None)
    assert is_error(r)
    assert r["message"] == "--job-id is required"


# ── construction-batch-add-cost-codes ───────────────────────────────────────

def test_batch_add_cost_codes_writes_every_row_and_one_audit(conn, env, mod):
    job_id = _job(conn, env, mod)
    r = _batch(conn, env, mod, job_id, [
        {"code": "03-300", "description": "Cast-in-place concrete",
         "category": "subcontract", "budget_amount": "48250.75"},
        {"code": "01-100", "description": "Site supervision",
         "budget_amount": "12000.00", "budget_hours": "320"},
        {"code": "02-200", "description": "Excavator rental",
         "category": "equipment"},
    ])
    assert is_ok(r), r
    assert r["created_count"] == 3
    assert [(c["code"], c["category"]) for c in r["cost_codes"]] == [
        ("03-300", "subcontract"), ("01-100", "labor"), ("02-200", "equipment")]
    cid = env["company_id"]
    assert _cost_codes(conn, job_id) == [
        ("01-100", "Site supervision", "labor", "12000.00", "320", 1, cid),
        ("02-200", "Excavator rental", "equipment", "0", "0", 1, cid),
        ("03-300", "Cast-in-place concrete", "subcontract", "48250.75", "0", 1, cid),
    ]
    audits = _audit_rows(conn, "construction-batch-add-cost-codes", job_id)
    assert len(audits) == 1
    assert audits[0][0] == "constructclaw_cost_code"
    assert json.loads(audits[0][1]) == {"count": 3}


def test_batch_add_cost_codes_refusals_before_any_row(conn, env, mod):
    job_id = _job(conn, env, mod)
    batch = mod.ACTIONS["construction-batch-add-cost-codes"]
    r = call_action(batch, conn, ns(company_id=None, job_id=job_id,
                                    codes_json='[{"code": "01-100"}]'))
    assert r["message"] == "--company-id is required"
    r = call_action(batch, conn, ns(company_id=env["company_id"], job_id=None,
                                    codes_json='[{"code": "01-100"}]'))
    assert r["message"] == "--job-id is required"
    r = _batch(conn, env, mod, job_id, None)
    assert r["message"] == "--codes-json is required (JSON array of cost code objects)"
    r = _batch(conn, env, mod, "no-such-job", [{"code": "01-100"}])
    assert r["message"] == "Job no-such-job not found"
    r = call_action(batch, conn, ns(company_id=env["company_id"], job_id=job_id,
                                    codes_json="[{not json"))
    assert is_error(r)
    assert r["message"].startswith("Invalid JSON for --codes-json: ")
    r = _batch(conn, env, mod, job_id, [])
    assert r["message"] == "--codes-json must be a non-empty JSON array"
    r = _batch(conn, env, mod, job_id, {"code": "01-100"})
    assert r["message"] == "--codes-json must be a non-empty JSON array"
    assert _cost_codes(conn, job_id) == []
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = ?",
                        ("construction-batch-add-cost-codes",)).fetchone()[0] == 0


def test_a_refusal_part_way_through_a_batch_writes_nothing(conn, env, mod):
    job_id = _job(conn, env, mod)
    cases = [
        ([{"code": "01-100", "budget_amount": "500.00"},
          {"code": "02-200", "category": "bogus"}],
         "Invalid category 'bogus' for cost code 02-200"),
        ([{"code": "01-100"}, {"code": "01-100"}],
         "Cost code 01-100 already exists for this job"),
        ([{"code": "01-100"}, {"description": "No code"}],
         "Cost code at index 1 missing 'code' field"),
    ]
    for codes, message in cases:
        r = _batch(conn, env, mod, job_id, codes)
        assert is_error(r), r
        assert r["message"] == message
        assert _cost_codes(conn, job_id) == []
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = ?",
                        ("construction-batch-add-cost-codes",)).fetchone()[0] == 0


def test_a_batch_that_repeats_an_existing_code_keeps_only_the_existing_row(conn, env, mod):
    job_id = _job(conn, env, mod)
    assert is_ok(_batch(conn, env, mod, job_id, [
        {"code": "01-100", "description": "Site supervision",
         "budget_amount": "12000.00"}]))
    r = _batch(conn, env, mod, job_id, [
        {"code": "05-500", "description": "Structural steel",
         "category": "material", "budget_amount": "9000.00"},
        {"code": "01-100", "description": "Duplicate"}])
    assert is_error(r), r
    assert r["message"] == "Cost code 01-100 already exists for this job"
    conn.commit()
    assert _cost_codes(conn, job_id) == [
        ("01-100", "Site supervision", "labor", "12000.00", "0", 1,
         env["company_id"])]
