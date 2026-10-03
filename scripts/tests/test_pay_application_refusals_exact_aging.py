"""Refused pay applications consume no number, linked invoices must match, exact aging (m697)."""
from construct_helpers import (
    call_action, ns, is_ok, is_error, seed_company, seed_naming_series,
)
from buying_harness import delegate_buying_in_process, seed_supplier

from erpclaw_lib import cross_skill
from erpclaw_lib.query import Q, P, Table


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


def _link(conn, pa_id, pi_id):
    t = Table("constructclaw_pay_application")
    conn.execute(Q.update(t).set(t.purchase_invoice_id, P())
                 .where(t.id == P()).get_sql(), (pi_id, pa_id))
    conn.commit()


def _ns_rows(conn):
    return [dict(r) for r in conn.execute(
        "SELECT * FROM naming_series WHERE entity_type = ?"
        " ORDER BY company_id, id",
        ("constructclaw_pay_application",)).fetchall()]


def _pi_calls(captured):
    return [c for c in captured.get("calls", [])
            if c["action"] == "create-purchase-invoice"]


def _approve_counts(conn, pa_id):
    return (
        conn.execute("SELECT COUNT(*) FROM purchase_invoice").fetchone()[0],
        conn.execute("SELECT COUNT(*) FROM purchase_invoice_item").fetchone()[0],
        conn.execute("SELECT COUNT(*) FROM gl_entry").fetchone()[0],
        conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = ?"
                     " AND entity_id = ?",
                     ("construction-approve-pay-application", pa_id)).fetchone()[0],
    )


def _other_company(conn):
    other = seed_company(conn, name="Other Co", abbr="OTH")
    seed_naming_series(conn, other)
    foreign_id = seed_supplier(conn, other, "Foreign Supplier")
    return other, foreign_id


# ---------------------------------------------------------------------------
# 1. refused add consumes no number
# ---------------------------------------------------------------------------

def test_refused_add_consumes_no_number(conn, env, mod, monkeypatch):
    delegate_buying_in_process(conn, monkeypatch)
    supplier_id = seed_supplier(conn, env["company_id"])
    job_id = _job(conn, env, mod)
    sub_id, sub_number = _sub(conn, env, mod, job_id, supplier_id)
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
    before_ns = _ns_rows(conn)
    assert before_ns, "expected pay-application naming_series rows"
    for kwargs, message in cases:
        r = call_action(add, conn, ns(
            company_id=env["company_id"], subcontract_id=sub_id,
            period_from=None, period_to=None, notes=None, **kwargs))
        assert is_error(r), r
        assert r["message"] == message, r
        assert _ns_rows(conn) == before_ns
        assert conn.execute(
            "SELECT COUNT(*) FROM constructclaw_pay_application").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action = ?",
                            ("construction-add-pay-application",)).fetchone()[0] == 0
    r = _add_app(conn, env, mod, sub_id, "20000.00")
    assert is_ok(r), r
    assert r["naming_series"].endswith("-00001"), r


# ---------------------------------------------------------------------------
# 2. supplier on update stays inside the company
# ---------------------------------------------------------------------------

def test_update_subcontract_supplier(conn, env, mod, monkeypatch):
    delegate_buying_in_process(conn, monkeypatch)
    supplier_id = seed_supplier(conn, env["company_id"])
    job_id = _job(conn, env, mod)
    sub_id, _ = _sub(conn, env, mod, job_id, supplier_id)
    update = mod.ACTIONS["construction-update-subcontract"]

    second_id = seed_supplier(conn, env["company_id"], "Second Supplier")
    r = call_action(update, conn, ns(
        subcontract_id=sub_id, supplier_id=second_id))
    assert is_ok(r), r
    assert r["updated_fields"] == ["supplier_id"], r
    stored = dict(conn.execute(
        "SELECT * FROM constructclaw_subcontract WHERE id = ?",
        (sub_id,)).fetchone())
    assert stored["supplier_id"] == second_id

    _, foreign_id = _other_company(conn)
    before_row = dict(conn.execute(
        "SELECT * FROM constructclaw_subcontract WHERE id = ?",
        (sub_id,)).fetchone())
    before_audit = conn.execute(
        "SELECT COUNT(*) FROM audit_log WHERE action = ? AND entity_id = ?",
        ("construction-update-subcontract", sub_id)).fetchone()[0]
    r = call_action(update, conn, ns(
        subcontract_id=sub_id, supplier_id=foreign_id))
    assert is_error(r), r
    assert r["message"] == (
        "Supplier %s not found for company %s"
        % (foreign_id, env["company_id"])), r
    assert dict(conn.execute(
        "SELECT * FROM constructclaw_subcontract WHERE id = ?",
        (sub_id,)).fetchone()) == before_row
    assert conn.execute(
        "SELECT COUNT(*) FROM audit_log WHERE action = ? AND entity_id = ?",
        ("construction-update-subcontract", sub_id)).fetchone()[0] == before_audit


# ---------------------------------------------------------------------------
# 3. linked invoice of another company refuses
# ---------------------------------------------------------------------------

def test_linked_invoice_of_other_company_refuses(conn, env, mod, monkeypatch):
    captured = delegate_buying_in_process(conn, monkeypatch)
    supplier_id = seed_supplier(conn, env["company_id"])
    job_id = _job(conn, env, mod)
    sub_id, _ = _sub(conn, env, mod, job_id, supplier_id)
    other, foreign_supplier = _other_company(conn)

    made = cross_skill.create_purchase_invoice(
        supplier_id=foreign_supplier,
        items=[{"description": "setup draft", "qty": "1",
                "rate": "18000.00"}],
        company_id=other)
    pi_id = made["purchase_invoice_id"]

    app = _add_app(conn, env, mod, sub_id, "20000.00")
    assert is_ok(app), app
    pa_id = app["pay_application_id"]
    _link(conn, pa_id, pi_id)

    before_row = _pa_row(conn, pa_id)
    before_counts = _approve_counts(conn, pa_id)
    calls_before = len(_pi_calls(captured))
    r = _approve(conn, mod, pa_id)
    assert is_error(r), r
    assert r["message"] == (
        "Pay application %s is linked to purchase invoice %s"
        " of another company; it cannot be approved against that invoice."
        % (app["naming_series"], pi_id)), r
    assert _pa_row(conn, pa_id) == before_row
    assert _approve_counts(conn, pa_id) == before_counts
    assert len(_pi_calls(captured)) == calls_before


# ---------------------------------------------------------------------------
# 4. linked invoice of another supplier refuses
# ---------------------------------------------------------------------------

def test_linked_invoice_of_other_supplier_refuses(conn, env, mod, monkeypatch):
    captured = delegate_buying_in_process(conn, monkeypatch)
    supplier_id = seed_supplier(conn, env["company_id"])
    job_id = _job(conn, env, mod)
    sub_id, sub_number = _sub(conn, env, mod, job_id, supplier_id)

    second_id = seed_supplier(conn, env["company_id"], "Second Supplier")
    made = cross_skill.create_purchase_invoice(
        supplier_id=second_id,
        items=[{"description": "setup draft", "qty": "1",
                "rate": "18000.00"}],
        company_id=env["company_id"])
    pi_id = made["purchase_invoice_id"]

    app = _add_app(conn, env, mod, sub_id, "20000.00")
    assert is_ok(app), app
    pa_id = app["pay_application_id"]
    _link(conn, pa_id, pi_id)

    before_row = _pa_row(conn, pa_id)
    before_counts = _approve_counts(conn, pa_id)
    calls_before = len(_pi_calls(captured))
    r = _approve(conn, mod, pa_id)
    assert is_error(r), r
    assert r["message"] == (
        "Pay application %s is linked to purchase invoice %s"
        " for a different supplier than subcontract %s;"
        " it cannot be approved against that invoice."
        % (app["naming_series"], pi_id, sub_number)), r
    assert _pa_row(conn, pa_id) == before_row
    assert _approve_counts(conn, pa_id) == before_counts
    assert len(_pi_calls(captured)) == calls_before


# ---------------------------------------------------------------------------
# 5. matching linked invoice is still reused
# ---------------------------------------------------------------------------

def test_linked_matching_invoice_still_reused(conn, env, mod, monkeypatch):
    captured = delegate_buying_in_process(conn, monkeypatch)
    supplier_id = seed_supplier(conn, env["company_id"])
    job_id = _job(conn, env, mod)
    sub_id, _ = _sub(conn, env, mod, job_id, supplier_id)

    made = cross_skill.create_purchase_invoice(
        supplier_id=supplier_id,
        items=[{"description": "setup draft", "qty": "1",
                "rate": "18000.00"}],
        company_id=env["company_id"])
    pi_id = made["purchase_invoice_id"]

    app = _add_app(conn, env, mod, sub_id, "20000.00")
    assert is_ok(app), app
    pa_id = app["pay_application_id"]
    _link(conn, pa_id, pi_id)

    calls_before = len(_pi_calls(captured))
    r = _approve(conn, mod, pa_id)
    assert is_ok(r), r
    assert r["purchase_invoice_id"] == pi_id, r
    assert _pa_row(conn, pa_id)["purchase_invoice_id"] == pi_id
    assert len(_pi_calls(captured)) == calls_before


# ---------------------------------------------------------------------------
# 6. aging paid is exact
# ---------------------------------------------------------------------------

def test_aging_paid_is_exact(conn, env, mod, monkeypatch):
    delegate_buying_in_process(conn, monkeypatch)
    supplier_id = seed_supplier(conn, env["company_id"])
    job_id = _job(conn, env, mod)
    r = call_action(mod.ACTIONS["construction-add-subcontract"], conn, ns(
        company_id=env["company_id"], job_id=job_id,
        subcontractor_name="Payable Mechanical", trade="hvac",
        scope_of_work=None, original_amount="100000000000000.00",
        retention_pct="0",
        insurance_expiry=None, license_number=None,
        start_date=None, end_date=None, notes=None,
        supplier_id=supplier_id))
    assert is_ok(r), r
    sub_id = r["subcontract_id"]

    first = _add_app(conn, env, mod, sub_id, "0.01")
    assert is_ok(first), first
    assert is_ok(_approve(conn, mod, first["pay_application_id"]))
    second = _add_app(conn, env, mod, sub_id, "90071992547409.94")
    assert is_ok(second), second
    assert is_ok(_approve(conn, mod, second["pay_application_id"]))

    r = call_action(mod.ACTIONS["construction-subcontractor-aging-report"],
                    conn, ns(company_id=env["company_id"]))
    assert is_ok(r), r
    assert r["total_count"] == 1
    entry = r["subcontractors"][0]
    assert entry["paid"] == "90071992547409.94", entry
    assert entry["remaining"] == "9928007452590.06", entry
    assert r["total_paid"] == "90071992547409.94", r
