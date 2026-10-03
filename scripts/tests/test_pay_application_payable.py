"""Pay-application certify-once rule and payable posting (m675).

A pay application's work completed is cumulative to date. On approval its
previous payments are recomputed from the applications already approved or
paid, so two applications that were open together cannot both certify the
same work. Approving creates the payable: a draft purchase invoice for the
subcontract's supplier, made through the buying module and linked to the
application. An application that already carries a link reuses that invoice
and never creates a second one.

No ledger effect anywhere here: the payable stays a draft until someone
submits it in the buying module, so gl_entry never moves in these tests.
"""
import datetime

from construct_helpers import call_action, is_error, is_ok, ns
from buying_harness import delegate_buying_in_process, seed_supplier

from erpclaw_lib import cross_skill
from erpclaw_lib.cross_skill import CrossSkillError
from erpclaw_lib.query import Q, P, Table


def _utc_today():
    return datetime.datetime.now(datetime.timezone.utc).date().isoformat()


def _job(conn, env, mod):
    r = call_action(mod.ACTIONS["construction-add-job"], conn, ns(
        company_id=env["company_id"], name="Payable Job",
        job_type=None, contract_type=None, contract_amount="500000.00",
        client_name=None, client_id=env["customer_id"], description=None,
        project_manager=None, superintendent=None,
        start_date=None, end_date=None, address=None,
        city=None, state=None, zip_code=None, notes=None))
    assert is_ok(r), r
    return r["job_id"]


def _sub(conn, env, mod, job_id, supplier_id, amount="100000.00"):
    r = call_action(mod.ACTIONS["construction-add-subcontract"], conn, ns(
        company_id=env["company_id"], job_id=job_id,
        subcontractor_name="Payable Mechanical", trade="hvac",
        scope_of_work=None, original_amount=amount, retention_pct="10",
        insurance_expiry=None, license_number=None,
        start_date=None, end_date=None, notes=None,
        supplier_id=supplier_id))
    assert is_ok(r), r
    return r["subcontract_id"], r["naming_series"]


def _add_app(conn, env, mod, sub_id, work_completed, materials_stored="0"):
    return call_action(mod.ACTIONS["construction-add-pay-application"], conn, ns(
        company_id=env["company_id"], subcontract_id=sub_id,
        work_completed=work_completed, materials_stored=materials_stored,
        period_from=None, period_to=None, notes=None))


def _approve(conn, mod, pa_id, **extra):
    return call_action(mod.ACTIONS["construction-approve-pay-application"], conn,
                       ns(pay_application_id=pa_id, **extra))


def _pa_row(conn, pa_id):
    row = conn.execute(
        "SELECT * FROM constructclaw_pay_application WHERE id = ?",
        (pa_id,)).fetchone()
    return dict(row) if row is not None else None


def _counts(conn, pa_id):
    return (
        conn.execute("SELECT COUNT(*) FROM purchase_invoice").fetchone()[0],
        conn.execute("SELECT COUNT(*) FROM purchase_invoice_item").fetchone()[0],
        conn.execute("SELECT COUNT(*) FROM gl_entry").fetchone()[0],
        conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = ?"
                     " AND entity_id = ?",
                     ("construction-approve-pay-application", pa_id)).fetchone()[0],
    )


def _state(conn, pa_id):
    return (_pa_row(conn, pa_id),) + _counts(conn, pa_id)


def _pi_calls(captured):
    return [c for c in captured.get("calls", [])
            if c["action"] == "create-purchase-invoice"]


def _setup(conn, env, mod, monkeypatch, amount="100000.00"):
    captured = delegate_buying_in_process(conn, monkeypatch)
    supplier_id = seed_supplier(conn, env["company_id"])
    job_id = _job(conn, env, mod)
    sub_id, sub_number = _sub(conn, env, mod, job_id, supplier_id,
                              amount=amount)
    return captured, supplier_id, sub_id, sub_number


# ---------------------------------------------------------------------------
# 1. two open applications certify once
# ---------------------------------------------------------------------------

def test_two_open_applications_certify_once(conn, env, mod, monkeypatch):
    captured, supplier_id, sub_id, _ = _setup(conn, env, mod, monkeypatch)

    a = _add_app(conn, env, mod, sub_id, "20000.00")
    assert is_ok(a), a
    b = _add_app(conn, env, mod, sub_id, "40000.00")
    assert is_ok(b), b
    assert (_pa_row(conn, b["pay_application_id"])["previous_payments"],
            _pa_row(conn, b["pay_application_id"])["current_payment_due"]) == (
        "0.00", "36000.00")

    gl_before = conn.execute("SELECT COUNT(*) FROM gl_entry").fetchone()[0]

    day_before_a = _utc_today()
    ra = _approve(conn, mod, a["pay_application_id"])
    day_after_a = _utc_today()
    assert is_ok(ra), ra
    day_before_b = _utc_today()
    rb = _approve(conn, mod, b["pay_application_id"])
    day_after_b = _utc_today()
    assert is_ok(rb), rb

    row_b = _pa_row(conn, b["pay_application_id"])
    assert (row_b["previous_payments"], row_b["current_payment_due"],
            row_b["pay_app_status"]) == ("18000.00", "18000.00", "approved")
    assert (rb["previous_payments"], rb["current_payment_due"],
            rb["pay_app_status"]) == ("18000.00", "18000.00", "approved")
    assert row_b["purchase_invoice_id"] == rb["purchase_invoice_id"]
    assert ra["purchase_invoice_id"] != rb["purchase_invoice_id"]

    for resp, day_before, day_after in (
            (ra, day_before_a, day_after_a), (rb, day_before_b, day_after_b)):
        inv = dict(conn.execute(
            "SELECT * FROM purchase_invoice WHERE id = ?",
            (resp["purchase_invoice_id"],)).fetchone())
        assert inv["status"] == "draft"
        assert inv["supplier_id"] == supplier_id
        assert (inv["total_amount"], inv["grand_total"],
                inv["outstanding_amount"]) == (
            "18000.00", "18000.00", "18000.00")
        assert inv["posting_date"] in (day_before, day_after)
        lines = [dict(r) for r in conn.execute(
            "SELECT * FROM purchase_invoice_item WHERE purchase_invoice_id = ?",
            (resp["purchase_invoice_id"],)).fetchall()]
        assert len(lines) == 1
        assert (lines[0]["quantity"], lines[0]["rate"],
                lines[0]["amount"]) == ("1.00", "18000.00", "18000.00")
        item = dict(conn.execute("SELECT * FROM item WHERE id = ?",
                                 (lines[0]["item_id"],)).fetchone())
        assert item["item_code"] == "SVC-%s" % env["company_id"]

    assert conn.execute("SELECT COUNT(*) FROM gl_entry").fetchone()[0] == gl_before
    assert len(_pi_calls(captured)) == 2


# ---------------------------------------------------------------------------
# 2. second application for the same work is refused
# ---------------------------------------------------------------------------

def test_second_application_for_the_same_work_is_refused(
        conn, env, mod, monkeypatch):
    captured, _, sub_id, _ = _setup(conn, env, mod, monkeypatch)

    first = _add_app(conn, env, mod, sub_id, "20000.00")
    second = _add_app(conn, env, mod, sub_id, "20000.00")
    assert is_ok(_approve(conn, mod, first["pay_application_id"]))

    before = _state(conn, second["pay_application_id"])
    calls_before = len(_pi_calls(captured))
    r = _approve(conn, mod, second["pay_application_id"])
    assert is_error(r), r
    assert r["message"] == (
        "Nothing is due on pay application %s: total earned 20000.00"
        " less retention 2000.00 less previous payments 18000.00 is 0.00"
        % second["naming_series"])
    assert _state(conn, second["pay_application_id"]) == before
    assert len(_pi_calls(captured)) == calls_before


# ---------------------------------------------------------------------------
# 3. amounts refused at add
# ---------------------------------------------------------------------------

def test_amounts_refused_at_add(conn, env, mod, monkeypatch):
    _, _, sub_id, sub_number = _setup(conn, env, mod, monkeypatch)
    add = mod.ACTIONS["construction-add-pay-application"]
    cases = [
        (dict(work_completed="-100.00", materials_stored="0"),
         "--work-completed must be a non-negative number"),
        (dict(work_completed="0", materials_stored="-1"),
         "--materials-stored must be a non-negative number"),
        (dict(work_completed="abc", materials_stored="0"),
         "--work-completed must be a non-negative number"),
        (dict(work_completed="95000.00", materials_stored="6000.00"),
         "Total earned 101000.00 exceeds the subcontract amount 100000.00"
         " for subcontract %s" % sub_number),
    ]
    for kwargs, message in cases:
        r = call_action(add, conn, ns(
            company_id=env["company_id"], subcontract_id=sub_id,
            period_from=None, period_to=None, notes=None, **kwargs))
        assert is_error(r), r
        assert r["message"] == message, r
    assert conn.execute(
        "SELECT COUNT(*) FROM constructclaw_pay_application").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = ?",
                        ("construction-add-pay-application",)).fetchone()[0] == 0


# ---------------------------------------------------------------------------
# 4. cap rechecked at approval
# ---------------------------------------------------------------------------

def test_cap_rechecked_at_approval(conn, env, mod, monkeypatch):
    _, _, sub_id, sub_number = _setup(conn, env, mod, monkeypatch)

    app = _add_app(conn, env, mod, sub_id, "50000.00")
    assert is_ok(app), app
    r = call_action(mod.ACTIONS["construction-update-subcontract"], conn, ns(
        subcontract_id=sub_id, revised_amount="40000.00"))
    assert is_ok(r), r

    before = _state(conn, app["pay_application_id"])
    r = _approve(conn, mod, app["pay_application_id"])
    assert is_error(r), r
    assert r["message"] == (
        "Total earned 50000.00 exceeds the subcontract amount 40000.00"
        " for subcontract %s" % sub_number)
    assert _state(conn, app["pay_application_id"]) == before


# ---------------------------------------------------------------------------
# 5. no supplier refuses
# ---------------------------------------------------------------------------

def test_no_supplier_refuses(conn, env, mod, monkeypatch):
    captured = delegate_buying_in_process(conn, monkeypatch)
    job_id = _job(conn, env, mod)
    r = call_action(mod.ACTIONS["construction-add-subcontract"], conn, ns(
        company_id=env["company_id"], job_id=job_id,
        subcontractor_name="No Supplier Sub", trade="hvac",
        scope_of_work=None, original_amount="100000.00", retention_pct="10",
        insurance_expiry=None, license_number=None,
        start_date=None, end_date=None, notes=None))
    assert is_ok(r), r
    sub_id, sub_number = r["subcontract_id"], r["naming_series"]

    app = _add_app(conn, env, mod, sub_id, "20000.00")
    assert is_ok(app), app
    r = _approve(conn, mod, app["pay_application_id"])
    assert is_error(r), r
    assert r["message"] == (
        "Subcontract %s has no supplier_id set. Assign a supplier to the"
        " subcontract before approving a pay application." % sub_number)
    assert captured.get("calls", []) == []


# ---------------------------------------------------------------------------
# 6. buying refusal writes nothing
# ---------------------------------------------------------------------------

def test_buying_refusal_writes_nothing(conn, env, mod, monkeypatch):
    delegate_buying_in_process(conn, monkeypatch)
    supplier_id = seed_supplier(conn, env["company_id"])
    job_id = _job(conn, env, mod)
    sub_id, _ = _sub(conn, env, mod, job_id, supplier_id)

    real = cross_skill.call_skill_action

    def _refuse(skill_name, action, args=None, db_path=None, timeout=30):
        if action == "create-purchase-invoice":
            raise CrossSkillError("simulated purchase refusal")
        return real(skill_name, action, args=args, db_path=db_path,
                    timeout=timeout)

    monkeypatch.setattr(cross_skill, "call_skill_action", _refuse)

    app = _add_app(conn, env, mod, sub_id, "20000.00")
    assert is_ok(app), app
    before = _state(conn, app["pay_application_id"])
    r = _approve(conn, mod, app["pay_application_id"])
    assert is_error(r), r
    assert r["message"] == (
        "Purchase invoice could not be created for pay application %s:"
        " simulated purchase refusal" % app["naming_series"])
    after = _pa_row(conn, app["pay_application_id"])
    assert after["pay_app_status"] == "draft"
    assert after["purchase_invoice_id"] is None
    assert _state(conn, app["pay_application_id"]) == before


# ---------------------------------------------------------------------------
# 7. linked draft is reused
# ---------------------------------------------------------------------------

def _link(conn, pa_id, pi_id):
    t = Table("constructclaw_pay_application")
    conn.execute(Q.update(t).set(t.purchase_invoice_id, P())
                 .where(t.id == P()).get_sql(), (pi_id, pa_id))
    conn.commit()


def test_linked_draft_is_reused(conn, env, mod, monkeypatch):
    captured, supplier_id, sub_id, _ = _setup(conn, env, mod, monkeypatch)

    made = cross_skill.create_purchase_invoice(
        supplier_id=supplier_id,
        items=[{"description": "setup draft", "qty": "1",
                "rate": "18000.00"}],
        company_id=env["company_id"])
    pi_id = made["purchase_invoice_id"]

    app = _add_app(conn, env, mod, sub_id, "20000.00")
    assert is_ok(app), app
    _link(conn, app["pay_application_id"], pi_id)

    before_counts = _counts(conn, app["pay_application_id"])
    calls_before = len(_pi_calls(captured))
    r = _approve(conn, mod, app["pay_application_id"])
    assert is_ok(r), r
    assert r["purchase_invoice_id"] == pi_id
    assert _pa_row(conn, app["pay_application_id"])[
        "purchase_invoice_id"] == pi_id
    assert _counts(conn, app["pay_application_id"])[:3] == before_counts[:3]
    assert len(_pi_calls(captured)) == calls_before


# ---------------------------------------------------------------------------
# 8. linked cancelled or wrong amount refuses
# ---------------------------------------------------------------------------

def _set_invoice_status(conn, pi_id, status):
    t = Table("purchase_invoice")
    conn.execute(Q.update(t).set(t.status, P()).where(t.id == P()).get_sql(),
                 (status, pi_id))
    conn.commit()


def test_linked_cancelled_or_wrong_amount_refuses(
        conn, env, mod, monkeypatch):
    captured, supplier_id, sub_id, _ = _setup(conn, env, mod, monkeypatch)

    made = cross_skill.create_purchase_invoice(
        supplier_id=supplier_id,
        items=[{"description": "setup draft", "qty": "1",
                "rate": "18000.00"}],
        company_id=env["company_id"])
    cancelled_id = made["purchase_invoice_id"]
    app = _add_app(conn, env, mod, sub_id, "20000.00")
    assert is_ok(app), app
    _link(conn, app["pay_application_id"], cancelled_id)
    _set_invoice_status(conn, cancelled_id, "cancelled")

    before = _state(conn, app["pay_application_id"])
    r = _approve(conn, mod, app["pay_application_id"])
    assert is_error(r), r
    assert r["message"] == (
        "Pay application %s is linked to purchase invoice %s"
        " in status 'cancelled'; it cannot be approved against that invoice."
        % (app["naming_series"], cancelled_id))
    assert _state(conn, app["pay_application_id"]) == before

    other = cross_skill.create_purchase_invoice(
        supplier_id=supplier_id,
        items=[{"description": "setup draft", "qty": "1",
                "rate": "17000.00"}],
        company_id=env["company_id"])
    other_id = other["purchase_invoice_id"]
    app2 = _add_app(conn, env, mod, sub_id, "20000.00")
    assert is_ok(app2), app2
    _link(conn, app2["pay_application_id"], other_id)

    before2 = _state(conn, app2["pay_application_id"])
    r = _approve(conn, mod, app2["pay_application_id"])
    assert is_error(r), r
    assert r["message"] == (
        "Pay application %s is linked to purchase invoice %s"
        " for 17000.00, but 18000.00 is due; it cannot be approved"
        " against that invoice." % (app2["naming_series"], other_id))
    assert _state(conn, app2["pay_application_id"]) == before2
    assert len(_pi_calls(captured)) == 2


# ---------------------------------------------------------------------------
# 9. aging report uses latest retention
# ---------------------------------------------------------------------------

def test_aging_report_uses_latest_retention(conn, env, mod, monkeypatch):
    _, _, sub_id, _ = _setup(conn, env, mod, monkeypatch)

    first = _add_app(conn, env, mod, sub_id, "20000.00")
    assert is_ok(_approve(conn, mod, first["pay_application_id"]))
    second = _add_app(conn, env, mod, sub_id, "50000.00")
    assert is_ok(second), second
    assert second["current_payment_due"] == "27000.00"
    assert is_ok(_approve(conn, mod, second["pay_application_id"]))

    r = call_action(mod.ACTIONS["construction-subcontractor-aging-report"],
                    conn, ns(company_id=env["company_id"]))
    assert is_ok(r), r
    assert r["total_count"] == 1
    entry = r["subcontractors"][0]
    assert entry["paid"] == "45000.00"
    assert entry["retention_held"] == "5000.00"
    assert entry["remaining"] == "50000.00"
    assert r["total_retention"] == "5000.00"


# ---------------------------------------------------------------------------
# 10. supplier must exist in company
# ---------------------------------------------------------------------------

def test_supplier_must_exist_in_company(conn, env, mod, monkeypatch):
    delegate_buying_in_process(conn, monkeypatch)
    job_id = _job(conn, env, mod)
    before = conn.execute(
        "SELECT COUNT(*) FROM constructclaw_subcontract").fetchone()[0]
    r = call_action(mod.ACTIONS["construction-add-subcontract"], conn, ns(
        company_id=env["company_id"], job_id=job_id,
        subcontractor_name="Ghost Supplier Sub", trade="hvac",
        scope_of_work=None, original_amount="100000.00", retention_pct="10",
        insurance_expiry=None, license_number=None,
        start_date=None, end_date=None, notes=None,
        supplier_id="supplier-that-does-not-exist"))
    assert is_error(r), r
    assert r["message"] == (
        "Supplier supplier-that-does-not-exist not found for company %s"
        % env["company_id"])
    assert conn.execute(
        "SELECT COUNT(*) FROM constructclaw_subcontract").fetchone()[0] == before


# ---------------------------------------------------------------------------
# 11. status change during approval refuses and links nothing
# ---------------------------------------------------------------------------

def test_status_change_during_approval_refuses_and_links_nothing(
        conn, env, mod, monkeypatch):
    _, _, sub_id, _ = _setup(conn, env, mod, monkeypatch)

    app = _add_app(conn, env, mod, sub_id, "20000.00")
    assert is_ok(app), app
    pa_id = app["pay_application_id"]
    pre_row = _pa_row(conn, pa_id)
    invoices_before = conn.execute(
        "SELECT COUNT(*) FROM purchase_invoice").fetchone()[0]
    audit_before = conn.execute(
        "SELECT COUNT(*) FROM audit_log WHERE action = ? AND entity_id = ?",
        ("construction-approve-pay-application", pa_id)).fetchone()[0]

    real = cross_skill.call_skill_action
    t = Table("constructclaw_pay_application")

    def _race(skill_name, action, args=None, db_path=None, timeout=30):
        # A concurrent approval landing between the payable's commit and the
        # guarded update: it must be applied after the buying call returns so
        # the same-connection buying commit cannot absorb it (in which case no
        # rollback could undo it). The pinned property is identical: the
        # guarded update sees the raced status and refuses without linking.
        result = real(skill_name, action, args=args, db_path=db_path,
                      timeout=timeout)
        if action == "create-purchase-invoice":
            conn.execute(Q.update(t).set(t.pay_app_status, P())
                         .where(t.id == P()).get_sql(), ("approved", pa_id))
        return result

    monkeypatch.setattr(cross_skill, "call_skill_action", _race)
    r = _approve(conn, mod, pa_id)
    assert is_error(r), r

    assert r["message"] == (
        "Pay application %s changed while it was being approved;"
        " purchase invoice %s is not linked to it"
        % (app["naming_series"], _new_invoice_id(conn, invoices_before)))
    assert _pa_row(conn, pa_id) == pre_row
    assert conn.execute(
        "SELECT COUNT(*) FROM audit_log WHERE action = ? AND entity_id = ?",
        ("construction-approve-pay-application", pa_id)).fetchone()[0] == audit_before
    assert conn.execute(
        "SELECT COUNT(*) FROM purchase_invoice").fetchone()[0] == invoices_before + 1
    assert _pa_row(conn, pa_id)["purchase_invoice_id"] is None


def _new_invoice_id(conn, invoices_before):
    rows = [dict(r) for r in conn.execute(
        "SELECT id FROM purchase_invoice").fetchall()]
    assert len(rows) == invoices_before + 1
    linked = set(row[0] for row in conn.execute(
        "SELECT purchase_invoice_id FROM constructclaw_pay_application"
        " WHERE purchase_invoice_id IS NOT NULL").fetchall())
    orphans = [r["id"] for r in rows if r["id"] not in linked]
    assert len(orphans) == 1
    return orphans[0]
