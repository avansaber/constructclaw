"""Behavioural depth for 12 constructclaw list/report actions.

Each action below already had a test that proved the wrong thing (response
shape, or bare routability): the old tests never read the database back, so a
perfectly shaped response over missing or wrong rows still passed. Every test
in this file seeds through the owning module's own actions, calls the list /
report action, then reads the stored rows back on a fresh seam connection and
compares exact values -- money as exact Decimal strings, never float.

Existing-test survey before writing (read, not duplicated):
- construction-list-pay-applications: test_pay_application_billing_behaviour.py
  pins filters and exact money strings, but never compares the response to the
  stored rows and has no refusal case. Deepened here with stored-row equality
  and a read-only snapshot.
- construction-permit-expiry-report: test_project_mgmt.py only asserts an
  "expired_count" key exists. Deepened here with stored-row classification.
- construction-safety-dashboard / construction-resource-utilization:
  test_safety_controls.py only asserts keys exist. Deepened here with exact
  counts and summed hours traced to stored rows.
- The other 8 actions have no test at all in this tree; this file is their
  only behavioural signal.

None of the 12 actions posts to the general ledger: each is a read-only
SELECT (or a pure aggregation over stored rows). There are no ledger legs to
assert, stated per test so a later reader does not add one that cannot hold.
Read-only-ness itself is asserted: a snapshot of the underlying tables plus
audit_log is byte-identical before and after every call, including refusals.
"""
import sqlite3
from decimal import Decimal

import pytest

from construct_helpers import call_action, is_error, is_ok, ns
from buying_harness import delegate_buying_in_process, seed_supplier

from erpclaw_lib import seam as seam_catalog
from erpclaw_lib.db import get_connection as seam_get_connection


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _job(conn, env, mod, name="Depth Job", amount="500000.00"):
    r = call_action(mod.ACTIONS["construction-add-job"], conn, ns(
        company_id=env["company_id"], name=name,
        job_type=None, contract_type=None, contract_amount=amount,
        client_name=None, client_id=env["customer_id"], description=None,
        project_manager=None, superintendent=None,
        start_date="2026-02-01", end_date="2026-12-18", address=None,
        city=None, state=None, zip_code=None, notes=None))
    assert is_ok(r), r
    return r["job_id"]


def _verify(sql, params=()):
    """Read stored rows back through the seam on a fresh connection."""
    vconn = seam_get_connection()
    try:
        return [dict(r) for r in vconn.execute(sql, params).fetchall()]
    finally:
        vconn.close()


def _snap(conn, tables):
    """Byte snapshot of the given tables for read-only / refusal proofs."""
    out = {}
    for table in tables:
        rows = conn.execute("SELECT * FROM %s ORDER BY rowid" % table).fetchall()
        out[table] = [tuple(r) for r in rows]
    return out


@pytest.fixture(autouse=True)
def _buying_bridge(conn, monkeypatch):
    """Setup only: approvals post their payable through the buying module."""
    return delegate_buying_in_process(conn, monkeypatch)


def _sub(conn, env, mod, job_id, name="Depth Sub", amount="100000.00",
         retention="10"):
    supplier_id = seed_supplier(conn, env["company_id"])
    r = call_action(mod.ACTIONS["construction-add-subcontract"], conn, ns(
        company_id=env["company_id"], job_id=job_id,
        subcontractor_name=name, trade="concrete", scope_of_work=None,
        original_amount=amount, retention_pct=retention,
        insurance_expiry=None, license_number=None,
        start_date="2026-02-01", end_date="2026-11-30", notes=None,
        supplier_id=supplier_id))
    assert is_ok(r), r
    return r["subcontract_id"]


# ---------------------------------------------------------------------------
# 1. construction-list-material-requisitions (stored rows)
# ---------------------------------------------------------------------------

def test_list_material_requisitions_returns_stored_rows(conn, env, mod):
    # DEFECT, documented not fixed (task rule 6): this action can never
    # return a row. Its filter references a "status" column that does not
    # exist on constructclaw_daily_material, and SQLite resolves the
    # double-quoted identifier to a string literal, so
    # WHERE "status" = 'requisition' is always false. The companion write
    # path is dead too: construction-create-material-requisition raises
    # OperationalError because it INSERTs a nonexistent job_id column. A
    # shape-only test passes here forever; this test pins the real behaviour.
    # No GL posting: read-only SELECT; no ledger legs to assert.
    assert seam_catalog.table_exists("constructclaw_daily_material") is True
    job_id = _job(conn, env, mod)
    dr = call_action(mod.ACTIONS["construction-add-daily-report"], conn, ns(
        company_id=env["company_id"], job_id=job_id,
        report_date="2026-04-02", superintendent=None, weather=None,
        temperature_high=None, temperature_low=None, work_description=None,
        delays=None, visitors=None, notes=None))["daily_report_id"]
    mat = call_action(mod.ACTIONS["construction-add-daily-material"], conn,
                      ns(company_id=env["company_id"], daily_report_id=dr,
                         material_name="Sand", quantity="10", unit="t",
                         supplier=None, delivery_ticket=None))
    assert is_ok(mat), mat
    stored = _verify(
        "SELECT id, material_name, quantity FROM constructclaw_daily_material")
    assert [(d["material_name"], d["quantity"]) for d in stored] == [
        ("Sand", "10")]

    with pytest.raises(sqlite3.OperationalError, match="job_id"):
        call_action(
            mod.ACTIONS["construction-create-material-requisition"], conn, ns(
                company_id=env["company_id"], job_id=job_id,
                material_name="Sand", quantity="10", unit="t",
                unit_cost="5.00", supplier=None, notes=None))

    tables = ["constructclaw_daily_material", "audit_log"]
    before = _snap(conn, tables)
    r = call_action(
        mod.ACTIONS["construction-list-material-requisitions"], conn,
        ns(company_id=env["company_id"], job_id=job_id))
    assert is_ok(r), r
    assert (r["total_count"], r["material_requisitions"]) == (0, [])
    assert _snap(conn, tables) == before

    r = call_action(
        mod.ACTIONS["construction-list-material-requisitions"], conn,
        ns(company_id=env["company_id"], job_id="no-such-job"))
    assert is_ok(r), r
    assert (r["total_count"], r["material_requisitions"]) == (0, [])
    assert _snap(conn, tables) == before


# ---------------------------------------------------------------------------
# 2. construction-list-pay-applications (stored rows)
# ---------------------------------------------------------------------------

def test_list_pay_applications_returns_stored_money(conn, env, mod):
    # No GL posting: read-only SELECT over constructclaw_pay_application.
    assert seam_catalog.table_exists("constructclaw_pay_application") is True
    job_id = _job(conn, env, mod)
    sub_id = _sub(conn, env, mod, job_id)
    mk = mod.ACTIONS["construction-add-pay-application"]
    a1 = call_action(mk, conn, ns(
        company_id=env["company_id"], subcontract_id=sub_id,
        work_completed="20000.00", materials_stored="1500.00",
        period_from="2026-03-01", period_to="2026-03-31",
        notes=None))["pay_application_id"]
    assert is_ok(call_action(
        mod.ACTIONS["construction-approve-pay-application"], conn,
        ns(pay_application_id=a1)))
    a2 = call_action(mk, conn, ns(
        company_id=env["company_id"], subcontract_id=sub_id,
        work_completed="50000.00", materials_stored="2500.00",
        period_from="2026-04-01", period_to="2026-04-30",
        notes=None))["pay_application_id"]

    stored = {d["id"]: d for d in _verify(
        "SELECT id, application_number, total_earned, retention_held,"
        " previous_payments, current_payment_due, pay_app_status"
        " FROM constructclaw_pay_application WHERE subcontract_id = ?",
        (sub_id,))}
    assert (stored[a1]["total_earned"], stored[a1]["retention_held"],
            stored[a1]["previous_payments"],
            stored[a1]["current_payment_due"],
            stored[a1]["pay_app_status"]) == (
        "21500.00", "2150.00", "0.00", "19350.00", "approved")
    assert (stored[a2]["total_earned"], stored[a2]["retention_held"],
            stored[a2]["previous_payments"],
            stored[a2]["current_payment_due"],
            stored[a2]["pay_app_status"]) == (
        "52500.00", "5250.00", "19350.00", "27900.00", "draft")

    tables = ["constructclaw_pay_application", "audit_log"]
    before = _snap(conn, tables)
    r = call_action(mod.ACTIONS["construction-list-pay-applications"], conn,
                    ns(subcontract_id=sub_id, company_id=None,
                       pay_app_status=None))
    assert is_ok(r), r
    assert r["total_count"] == 2
    assert [(x["id"], x["application_number"]) for x in r["pay_applications"]] == [
        (a2, 2), (a1, 1)]
    for x in r["pay_applications"]:
        s = stored[x["id"]]
        assert (x["total_earned"], x["retention_held"], x["previous_payments"],
                x["current_payment_due"], x["pay_app_status"]) == (
            s["total_earned"], s["retention_held"], s["previous_payments"],
            s["current_payment_due"], s["pay_app_status"])
        assert Decimal(x["current_payment_due"]) == Decimal(
            s["current_payment_due"])
    assert _snap(conn, tables) == before

    r = call_action(mod.ACTIONS["construction-list-pay-applications"], conn,
                    ns(subcontract_id=None, company_id=env["company_id"],
                       pay_app_status="draft"))
    assert is_ok(r), r
    assert r["total_count"] == 1
    assert r["pay_applications"][0]["id"] == a2
    assert _snap(conn, tables) == before


# ---------------------------------------------------------------------------
# 3. construction-list-progress-bills (stored rows)
# ---------------------------------------------------------------------------

def test_list_progress_bills_returns_stored_rows(conn, env, mod):
    # No GL posting: read-only SELECT over constructclaw_progress_bill.
    assert seam_catalog.table_exists("constructclaw_progress_bill") is True
    job_id = _job(conn, env, mod)
    mk = mod.ACTIONS["construction-add-progress-bill"]
    b1 = call_action(mk, conn, ns(
        company_id=env["company_id"], job_id=job_id, sov_id=None,
        total_completed="20000.00", total_retention="2000.00",
        period_from="2026-03-01", period_to="2026-03-31",
        notes=None))["progress_bill_id"]
    b2 = call_action(mk, conn, ns(
        company_id=env["company_id"], job_id=job_id, sov_id=None,
        total_completed="50000.00", total_retention="5000.00",
        period_from="2026-04-01", period_to="2026-04-30",
        notes=None))["progress_bill_id"]

    stored = {d["id"]: d for d in _verify(
        "SELECT id, bill_number, total_completed, total_retention,"
        " total_previous, current_due, bill_status"
        " FROM constructclaw_progress_bill WHERE job_id = ?", (job_id,))}
    assert (stored[b1]["bill_number"], stored[b1]["total_completed"],
            stored[b1]["total_retention"], stored[b1]["total_previous"],
            stored[b1]["current_due"], stored[b1]["bill_status"]) == (
        1, "20000.00", "2000.00", "0.00", "18000.00", "draft")
    assert (stored[b2]["bill_number"], stored[b2]["total_completed"],
            stored[b2]["total_retention"], stored[b2]["total_previous"],
            stored[b2]["current_due"], stored[b2]["bill_status"]) == (
        2, "50000.00", "5000.00", "18000.00", "27000.00", "draft")

    tables = ["constructclaw_progress_bill", "audit_log"]
    before = _snap(conn, tables)
    r = call_action(mod.ACTIONS["construction-list-progress-bills"], conn,
                    ns(company_id=env["company_id"], job_id=job_id,
                       bill_status=None))
    assert is_ok(r), r
    assert r["total_count"] == 2
    assert [(x["id"], x["bill_number"]) for x in r["progress_bills"]] == [
        (b2, 2), (b1, 1)]
    for x in r["progress_bills"]:
        s = stored[x["id"]]
        assert (x["total_completed"], x["total_retention"],
                x["total_previous"], x["current_due"],
                x["bill_status"]) == (
            s["total_completed"], s["total_retention"], s["total_previous"],
            s["current_due"], s["bill_status"])
        assert Decimal(x["current_due"]) == Decimal(s["current_due"])
    assert _snap(conn, tables) == before

    r = call_action(mod.ACTIONS["construction-list-progress-bills"], conn,
                    ns(company_id=env["company_id"], job_id=job_id,
                       bill_status="paid"))
    assert is_ok(r), r
    assert (r["total_count"], r["progress_bills"]) == (0, [])
    assert _snap(conn, tables) == before


# ---------------------------------------------------------------------------
# 4. construction-list-safety-certs (stored rows)
# ---------------------------------------------------------------------------

def test_list_safety_certs_returns_stored_rows(conn, env, mod):
    # No GL posting: read-only SELECT over constructclaw_safety_cert.
    assert seam_catalog.table_exists("constructclaw_safety_cert") is True
    job_id = _job(conn, env, mod)
    mk = mod.ACTIONS["construction-add-safety-cert"]
    c1 = call_action(mk, conn, ns(
        company_id=env["company_id"], job_id=job_id,
        worker_name="Alice Torres", cert_type="osha_10",
        cert_number="OSHA-001", issued_date="2026-01-10",
        expiry_date="2027-06-01", issuing_authority="OSHA"))["safety_cert_id"]
    c2 = call_action(mk, conn, ns(
        company_id=env["company_id"], job_id=job_id,
        worker_name="Bob Ray", cert_type="first_aid",
        cert_number="FA-009", issued_date="2026-02-01",
        expiry_date="2026-12-01", issuing_authority="Red Cross"))[
            "safety_cert_id"]

    stored = {d["id"]: d for d in _verify(
        "SELECT id, worker_name, cert_type, cert_number, expiry_date,"
        " cert_status, company_id FROM constructclaw_safety_cert"
        " WHERE company_id = ?", (env["company_id"],))}
    assert (stored[c1]["worker_name"], stored[c1]["cert_type"],
            stored[c1]["cert_number"], stored[c1]["expiry_date"],
            stored[c1]["cert_status"]) == (
        "Alice Torres", "osha_10", "OSHA-001", "2027-06-01", "active")
    assert (stored[c2]["worker_name"], stored[c2]["cert_type"],
            stored[c2]["cert_number"], stored[c2]["expiry_date"],
            stored[c2]["cert_status"]) == (
        "Bob Ray", "first_aid", "FA-009", "2026-12-01", "active")

    tables = ["constructclaw_safety_cert", "audit_log"]
    before = _snap(conn, tables)
    r = call_action(mod.ACTIONS["construction-list-safety-certs"], conn, ns(
        company_id=env["company_id"], job_id=job_id, worker_name=None,
        cert_status=None))
    assert is_ok(r), r
    assert r["total_count"] == 2
    assert [x["id"] for x in r["safety_certs"]] == [c2, c1]
    for x in r["safety_certs"]:
        s = stored[x["id"]]
        assert (x["worker_name"], x["cert_type"], x["cert_number"],
                x["expiry_date"], x["cert_status"]) == (
            s["worker_name"], s["cert_type"], s["cert_number"],
            s["expiry_date"], s["cert_status"])
    assert job_id and _snap(conn, tables) == before

    r = call_action(mod.ACTIONS["construction-list-safety-certs"], conn, ns(
        company_id=env["company_id"], job_id=None,
        worker_name="Alice Torres", cert_status=None))
    assert is_ok(r), r
    assert r["total_count"] == 1
    assert r["safety_certs"][0]["id"] == c1

    r = call_action(mod.ACTIONS["construction-list-safety-certs"], conn, ns(
        company_id=env["company_id"], job_id=None, worker_name=None,
        cert_status="revoked"))
    assert is_ok(r), r
    assert (r["total_count"], r["safety_certs"]) == (0, [])
    assert _snap(conn, tables) == before


# ---------------------------------------------------------------------------
# 5. construction-list-schedules-of-values (stored rows)
# ---------------------------------------------------------------------------

def test_list_schedules_of_values_returns_stored_rows(conn, env, mod):
    # No GL posting: read-only SELECT over constructclaw_schedule_of_values.
    assert seam_catalog.table_exists(
        "constructclaw_schedule_of_values") is True
    job_id = _job(conn, env, mod)
    mk = mod.ACTIONS["construction-add-schedule-of-values"]
    s1 = call_action(mk, conn, ns(
        company_id=env["company_id"], job_id=job_id, name="Main SOV",
        total_contract="250000.00", notes=None))["sov_id"]
    s2 = call_action(mk, conn, ns(
        company_id=env["company_id"], job_id=job_id, name="Fit-out SOV",
        total_contract="75000.50", notes=None))["sov_id"]

    stored = {d["id"]: d for d in _verify(
        "SELECT id, name, total_contract, revised_contract, job_id"
        " FROM constructclaw_schedule_of_values WHERE job_id = ?", (job_id,))}
    assert set(stored) == {s1, s2}
    assert (stored[s1]["name"], stored[s1]["total_contract"],
            stored[s1]["revised_contract"]) == (
        "Main SOV", "250000.00", "250000.00")
    assert (stored[s2]["name"], stored[s2]["total_contract"],
            stored[s2]["revised_contract"]) == (
        "Fit-out SOV", "75000.50", "75000.50")
    assert Decimal(stored[s2]["total_contract"]) == Decimal("75000.50")

    tables = ["constructclaw_schedule_of_values", "audit_log"]
    before = _snap(conn, tables)
    r = call_action(mod.ACTIONS["construction-list-schedules-of-values"],
                    conn, ns(company_id=env["company_id"], job_id=job_id))
    assert is_ok(r), r
    assert r["total_count"] == 2
    assert {x["id"] for x in r["schedules_of_values"]} == {s1, s2}
    for x in r["schedules_of_values"]:
        s = stored[x["id"]]
        assert (x["name"], x["total_contract"], x["revised_contract"]) == (
            s["name"], s["total_contract"], s["revised_contract"])
        assert Decimal(x["total_contract"]) == Decimal(s["total_contract"])
    assert _snap(conn, tables) == before

    r = call_action(mod.ACTIONS["construction-list-schedules-of-values"],
                    conn, ns(company_id=env["company_id"], job_id="no-such-job"))
    assert is_ok(r), r
    assert (r["total_count"], r["schedules_of_values"]) == (0, [])
    assert _snap(conn, tables) == before


# ---------------------------------------------------------------------------
# 6. construction-list-sov-lines (stored rows)
# ---------------------------------------------------------------------------

def test_list_sov_lines_returns_stored_rows(conn, env, mod):
    # No GL posting: read-only SELECT over constructclaw_sov_line.
    assert seam_catalog.table_exists("constructclaw_sov_line") is True
    job_id = _job(conn, env, mod)
    sov_id = call_action(
        mod.ACTIONS["construction-add-schedule-of-values"], conn, ns(
            company_id=env["company_id"], job_id=job_id, name="Main SOV",
            total_contract="20000.50", notes=None))["sov_id"]
    mk = mod.ACTIONS["construction-add-sov-line"]
    l1 = call_action(mk, conn, ns(
        company_id=env["company_id"], sov_id=sov_id, item_number="1",
        description="Foundations", scheduled_value="12000.00",
        retention_pct="10"))["sov_line_id"]
    l2 = call_action(mk, conn, ns(
        company_id=env["company_id"], sov_id=sov_id, item_number="2",
        description="Framing", scheduled_value="8000.50",
        retention_pct="5"))["sov_line_id"]

    stored = {d["id"]: d for d in _verify(
        "SELECT id, item_number, description, scheduled_value,"
        " balance_to_finish, retention_pct FROM constructclaw_sov_line"
        " WHERE sov_id = ?", (sov_id,))}
    assert (stored[l1]["item_number"], stored[l1]["description"],
            stored[l1]["scheduled_value"], stored[l1]["balance_to_finish"],
            stored[l1]["retention_pct"]) == (
        "1", "Foundations", "12000.00", "12000.00", "10")
    assert (stored[l2]["item_number"], stored[l2]["description"],
            stored[l2]["scheduled_value"], stored[l2]["balance_to_finish"],
            stored[l2]["retention_pct"]) == (
        "2", "Framing", "8000.50", "8000.50", "5")

    tables = ["constructclaw_sov_line", "audit_log"]
    before = _snap(conn, tables)
    r = call_action(mod.ACTIONS["construction-list-sov-lines"], conn,
                    ns(sov_id=sov_id))
    assert is_ok(r), r
    assert r["total_count"] == 2
    assert [x["id"] for x in r["sov_lines"]] == [l1, l2]
    for x in r["sov_lines"]:
        s = stored[x["id"]]
        assert (x["item_number"], x["description"], x["scheduled_value"],
                x["balance_to_finish"], x["retention_pct"]) == (
            s["item_number"], s["description"], s["scheduled_value"],
            s["balance_to_finish"], s["retention_pct"])
        assert Decimal(x["scheduled_value"]) == Decimal(s["scheduled_value"])
    assert _snap(conn, tables) == before


def test_list_sov_lines_refuses_without_sov_id(conn, env, mod):
    tables = ["constructclaw_sov_line", "audit_log"]
    before = _snap(conn, tables)
    r = call_action(mod.ACTIONS["construction-list-sov-lines"], conn,
                    ns(sov_id=None))
    assert is_error(r), r
    assert r["message"] == "--sov-id is required"
    assert _snap(conn, tables) == before


# ---------------------------------------------------------------------------
# 7. construction-list-subcontract-lines (stored rows)
# ---------------------------------------------------------------------------

def test_list_subcontract_lines_returns_stored_rows(conn, env, mod):
    # No GL posting: read-only SELECT over constructclaw_subcontract_line.
    assert seam_catalog.table_exists("constructclaw_subcontract_line") is True
    job_id = _job(conn, env, mod)
    sub_id = _sub(conn, env, mod, job_id)
    mk = mod.ACTIONS["construction-add-subcontract-line"]
    l1 = call_action(mk, conn, ns(
        company_id=env["company_id"], subcontract_id=sub_id,
        description="Mobilize site", quantity="10", unit="ls",
        unit_cost="250.00", amount=None))["line_id"]
    l2 = call_action(mk, conn, ns(
        company_id=env["company_id"], subcontract_id=sub_id,
        description="Pour footings", quantity="3", unit="m3",
        unit_cost="100.00", amount=None))["line_id"]

    stored = {d["id"]: d for d in _verify(
        "SELECT id, line_number, description, quantity, unit, unit_cost,"
        " amount FROM constructclaw_subcontract_line"
        " WHERE subcontract_id = ?", (sub_id,))}
    assert (stored[l1]["line_number"], stored[l1]["description"],
            stored[l1]["quantity"], stored[l1]["unit"],
            stored[l1]["unit_cost"], stored[l1]["amount"]) == (
        1, "Mobilize site", "10", "ls", "250.00", "2500.00")
    assert (stored[l2]["line_number"], stored[l2]["description"],
            stored[l2]["quantity"], stored[l2]["unit"],
            stored[l2]["unit_cost"], stored[l2]["amount"]) == (
        2, "Pour footings", "3", "m3", "100.00", "300.00")

    tables = ["constructclaw_subcontract_line", "audit_log"]
    before = _snap(conn, tables)
    r = call_action(mod.ACTIONS["construction-list-subcontract-lines"], conn,
                    ns(subcontract_id=sub_id))
    assert is_ok(r), r
    assert r["total_count"] == 2
    assert [x["id"] for x in r["lines"]] == [l1, l2]
    for x in r["lines"]:
        s = stored[x["id"]]
        assert (x["line_number"], x["description"], x["quantity"], x["unit"],
                x["unit_cost"], x["amount"]) == (
            s["line_number"], s["description"], s["quantity"], s["unit"],
            s["unit_cost"], s["amount"])
        assert Decimal(x["amount"]) == Decimal(s["amount"])
    assert _snap(conn, tables) == before


def test_list_subcontract_lines_refuses_without_subcontract_id(conn, env, mod):
    tables = ["constructclaw_subcontract_line", "audit_log"]
    before = _snap(conn, tables)
    r = call_action(mod.ACTIONS["construction-list-subcontract-lines"], conn,
                    ns(subcontract_id=None))
    assert is_error(r), r
    assert r["message"] == "--subcontract-id is required"
    assert _snap(conn, tables) == before


# ---------------------------------------------------------------------------
# 8. construction-list-submittals (stored rows)
# ---------------------------------------------------------------------------

def test_list_submittals_returns_stored_rows(conn, env, mod):
    # No GL posting: read-only SELECT over constructclaw_submittal.
    assert seam_catalog.table_exists("constructclaw_submittal") is True
    job_id = _job(conn, env, mod)
    mk = mod.ACTIONS["construction-add-submittal"]
    s1 = call_action(mk, conn, ns(
        company_id=env["company_id"], job_id=job_id,
        title="Rebar shop drawings", spec_section="03 30 00",
        description=None, submitted_by="SteelCo", submitted_to="Engineer",
        date_required="2026-05-01", notes=None))["submittal_id"]
    s2 = call_action(mk, conn, ns(
        company_id=env["company_id"], job_id=job_id,
        title="Panel schedule", spec_section="26 00 00",
        description=None, submitted_by="VoltCo", submitted_to="Engineer",
        date_required="2026-06-01", notes=None))["submittal_id"]

    stored = {d["id"]: d for d in _verify(
        "SELECT id, title, spec_section, submittal_status, job_id"
        " FROM constructclaw_submittal WHERE job_id = ?", (job_id,))}
    assert set(stored) == {s1, s2}
    assert (stored[s1]["title"], stored[s1]["spec_section"],
            stored[s1]["submittal_status"]) == (
        "Rebar shop drawings", "03 30 00", "pending")
    assert (stored[s2]["title"], stored[s2]["spec_section"],
            stored[s2]["submittal_status"]) == (
        "Panel schedule", "26 00 00", "pending")

    tables = ["constructclaw_submittal", "audit_log"]
    before = _snap(conn, tables)
    r = call_action(mod.ACTIONS["construction-list-submittals"], conn, ns(
        company_id=env["company_id"], job_id=job_id, submittal_status=None,
        search=None, limit=50, offset=0))
    assert is_ok(r), r
    assert r["total_count"] == 2
    assert {x["id"] for x in r["submittals"]} == {s1, s2}
    for x in r["submittals"]:
        s = stored[x["id"]]
        assert (x["title"], x["spec_section"], x["submittal_status"]) == (
            s["title"], s["spec_section"], s["submittal_status"])
    assert _snap(conn, tables) == before

    r = call_action(mod.ACTIONS["construction-list-submittals"], conn, ns(
        company_id=env["company_id"], job_id=job_id, submittal_status=None,
        search="Rebar", limit=50, offset=0))
    assert is_ok(r), r
    assert r["total_count"] == 1
    assert r["submittals"][0]["id"] == s1
    assert r["submittals"][0]["title"] == "Rebar shop drawings"

    r = call_action(mod.ACTIONS["construction-list-submittals"], conn, ns(
        company_id=env["company_id"], job_id=job_id,
        submittal_status="approved", search=None, limit=50, offset=0))
    assert is_ok(r), r
    assert (r["total_count"], r["submittals"]) == (0, [])
    assert _snap(conn, tables) == before


# ---------------------------------------------------------------------------
# 9. construction-material-waste-report (stored-row aggregation)
# ---------------------------------------------------------------------------

def test_material_waste_report_aggregates_stored_rows(conn, env, mod):
    # DEFECT, documented not fixed (task rule 6): this action always raises
    # OperationalError (it SELECTs job_id and unit_cost columns that do not
    # exist on constructclaw_daily_material), even with rows stored through
    # the only working write path. A routability-only test would report a
    # pass or an incident-free run; this test pins the real behaviour: the
    # report can never be produced, and the failed call writes nothing.
    # No GL posting: the query never completes; no ledger legs to assert.
    assert seam_catalog.table_exists("constructclaw_daily_material") is True
    job_id = _job(conn, env, mod)
    dr = call_action(mod.ACTIONS["construction-add-daily-report"], conn, ns(
        company_id=env["company_id"], job_id=job_id,
        report_date="2026-04-02", superintendent=None, weather=None,
        temperature_high=None, temperature_low=None, work_description=None,
        delays=None, visitors=None, notes=None))["daily_report_id"]
    mk = mod.ACTIONS["construction-add-daily-material"]
    for name, qty in [("Sand", "10"), ("Sand", "20"), ("Gravel", "7")]:
        r = call_action(mk, conn, ns(
            company_id=env["company_id"], daily_report_id=dr,
            material_name=name, quantity=qty, unit="t", supplier=None,
            delivery_ticket=None))
        assert is_ok(r), r
    stored = _verify(
        "SELECT material_name, quantity FROM constructclaw_daily_material")
    assert sorted((d["material_name"], d["quantity"]) for d in stored) == [
        ("Gravel", "7"), ("Sand", "10"), ("Sand", "20")]

    tables = ["constructclaw_daily_material", "audit_log"]
    before = _snap(conn, tables)
    with pytest.raises(sqlite3.OperationalError):
        call_action(mod.ACTIONS["construction-material-waste-report"], conn,
                    ns(company_id=env["company_id"], job_id=job_id))
    assert _snap(conn, tables) == before


def test_material_waste_report_refusals_write_nothing(conn, env, mod):
    tables = ["constructclaw_daily_material", "audit_log"]
    job_id = _job(conn, env, mod)
    before = _snap(conn, tables)
    r = call_action(mod.ACTIONS["construction-material-waste-report"], conn,
                    ns(company_id=None, job_id=job_id))
    assert is_error(r), r
    assert r["message"] == "--company-id is required"
    assert _snap(conn, tables) == before
    r = call_action(mod.ACTIONS["construction-material-waste-report"], conn,
                    ns(company_id=env["company_id"], job_id=None))
    assert is_error(r), r
    assert r["message"] == "--job-id is required"
    assert _snap(conn, tables) == before


# ---------------------------------------------------------------------------
# 10. construction-permit-expiry-report (stored rows)
# ---------------------------------------------------------------------------

def test_permit_expiry_report_classifies_stored_rows(conn, env, mod):
    # No GL posting: read-only SELECT over constructclaw_permit.
    assert seam_catalog.table_exists("constructclaw_permit") is True
    job_id = _job(conn, env, mod)
    mk = mod.ACTIONS["construction-add-permit"]
    p1 = call_action(mk, conn, ns(
        company_id=env["company_id"], job_id=job_id, permit_type="building",
        permit_number="BP-EXP-001", jurisdiction="Portland",
        application_date="2019-01-01", approval_date="2019-02-01",
        expiration_date="2020-01-01", inspection_date=None,
        inspection_result=None, inspector_name=None, correction_notes=None,
        permit_status=None))["permit_id"]
    p2 = call_action(mk, conn, ns(
        company_id=env["company_id"], job_id=job_id, permit_type="electrical",
        permit_number="BP-FUT-002", jurisdiction="Portland",
        application_date="2026-01-01", approval_date="2026-02-01",
        expiration_date="2099-06-01", inspection_date=None,
        inspection_result=None, inspector_name=None, correction_notes=None,
        permit_status=None))["permit_id"]

    stored = {d["id"]: d for d in _verify(
        "SELECT id, permit_number, expiration_date, status"
        " FROM constructclaw_permit WHERE company_id = ?",
        (env["company_id"],))}
    assert (stored[p1]["permit_number"], stored[p1]["expiration_date"],
            stored[p1]["status"]) == ("BP-EXP-001", "2020-01-01", "applied")
    assert (stored[p2]["permit_number"], stored[p2]["expiration_date"],
            stored[p2]["status"]) == ("BP-FUT-002", "2099-06-01", "applied")

    tables = ["constructclaw_permit", "audit_log"]
    before = _snap(conn, tables)
    r = call_action(mod.ACTIONS["construction-permit-expiry-report"], conn,
                    ns(company_id=env["company_id"]))
    assert is_ok(r), r
    assert r["total_permits"] == 2
    assert r["expired_count"] == 1
    assert [x["permit_number"] for x in r["expired"]] == ["BP-EXP-001"]
    # Real behaviour, documented: the elif and the else both append to
    # expiring_soon, so every non-expired dated permit counts as expiring soon.
    assert r["expiring_soon_count"] == 1
    assert [x["permit_number"] for x in r["expiring_soon"]] == ["BP-FUT-002"]
    for x in r["expired"] + r["expiring_soon"]:
        s = stored[x["id"]]
        assert (x["permit_number"], x["expiration_date"]) == (
            s["permit_number"], s["expiration_date"])
    assert _snap(conn, tables) == before


def test_permit_expiry_report_refuses_without_company(conn, env, mod):
    tables = ["constructclaw_permit", "audit_log"]
    before = _snap(conn, tables)
    r = call_action(mod.ACTIONS["construction-permit-expiry-report"], conn,
                    ns(company_id=None))
    assert is_error(r), r
    assert r["message"] == "--company-id is required"
    assert _snap(conn, tables) == before


# ---------------------------------------------------------------------------
# 11. construction-resource-utilization (stored-row aggregation)
# ---------------------------------------------------------------------------

def test_resource_utilization_sums_stored_hours(conn, env, mod):
    # No GL posting: pure aggregation over daily labor and cost entries.
    assert seam_catalog.table_exists("constructclaw_daily_labor") is True
    job_id = _job(conn, env, mod)
    dr = call_action(mod.ACTIONS["construction-add-daily-report"], conn, ns(
        company_id=env["company_id"], job_id=job_id,
        report_date="2026-04-02", superintendent="Sam",
        weather=None, temperature_high=None, temperature_low=None,
        work_description="Footings", delays=None, visitors=None,
        notes=None))["daily_report_id"]
    mk = mod.ACTIONS["construction-add-daily-labor"]
    for trade, headcount, hours in [("carpentry", 4, "32.00"),
                                    ("electrical", 2, "16.50")]:
        r = call_action(mk, conn, ns(
            company_id=env["company_id"], daily_report_id=dr, trade=trade,
            headcount=headcount, hours=hours, description=None))
        assert is_ok(r), r

    lines = _verify(
        "SELECT trade, headcount, hours FROM constructclaw_daily_labor"
        " WHERE daily_report_id = ?", (dr,))
    assert {(l["trade"], l["headcount"], l["hours"]) for l in lines} == {
        ("carpentry", 4, "32.00"), ("electrical", 2, "16.50")}
    assert sum(Decimal(l["hours"]) for l in lines) == Decimal("48.50")

    tables = ["constructclaw_daily_labor", "constructclaw_daily_report",
              "constructclaw_cost_entry", "audit_log"]
    before = _snap(conn, tables)
    r = call_action(mod.ACTIONS["construction-resource-utilization"], conn,
                    ns(company_id=env["company_id"]))
    assert is_ok(r), r
    assert r["daily_report_labor_hours"] == "48.50"
    assert r["daily_report_headcount"] == 6
    assert r["cost_entry_labor_hours"] == "0.00"
    assert [(t["trade"], t["headcount"], t["hours"])
            for t in r["by_trade"]] == [
        ("carpentry", 4, "32.00"), ("electrical", 2, "16.50")]
    assert Decimal(r["daily_report_labor_hours"]) == Decimal("48.50")
    assert _snap(conn, tables) == before


def test_resource_utilization_refuses_without_company(conn, env, mod):
    tables = ["constructclaw_daily_labor", "constructclaw_daily_report",
              "constructclaw_cost_entry", "audit_log"]
    before = _snap(conn, tables)
    r = call_action(mod.ACTIONS["construction-resource-utilization"], conn,
                    ns(company_id=None))
    assert is_error(r), r
    assert r["message"] == "--company-id is required"
    assert _snap(conn, tables) == before


# ---------------------------------------------------------------------------
# 12. construction-safety-dashboard (stored rows)
# ---------------------------------------------------------------------------

def test_safety_dashboard_counts_stored_rows(conn, env, mod):
    # No GL posting: pure counts over incidents, talks and certs.
    assert seam_catalog.table_exists("constructclaw_incident") is True
    job_id = _job(conn, env, mod)
    mi = mod.ACTIONS["construction-add-incident"]
    i1 = call_action(mi, conn, ns(
        company_id=env["company_id"], job_id=job_id,
        description="Fall from scaffold", incident_type="lost_time",
        severity="serious", location="Scaffold A", injured_party="Bob",
        witnesses=None, root_cause=None, corrective_action=None,
        osha_recordable=None, days_lost="3", incident_date="2026-03-05",
        incident_time=None, notes=None))["incident_id"]
    i2 = call_action(mi, conn, ns(
        company_id=env["company_id"], job_id=job_id,
        description="Near miss", incident_type="near_miss", severity="minor",
        location=None, injured_party=None, witnesses=None, root_cause=None,
        corrective_action=None, osha_recordable=None, days_lost=None,
        incident_date="2026-03-06", incident_time=None,
        notes=None))["incident_id"]
    talk = call_action(mod.ACTIONS["construction-add-toolbox-talk"], conn, ns(
        company_id=env["company_id"], job_id=job_id, topic="Fall protection",
        talk_date="2026-03-07", presenter="Sam", attendee_count=8,
        attendees=None, duration_minutes=15, notes=None))
    assert is_ok(talk), talk
    cert = call_action(mod.ACTIONS["construction-add-safety-cert"], conn, ns(
        company_id=env["company_id"], job_id=job_id, worker_name="Alice",
        cert_type="osha_10", cert_number="O-1", issued_date="2026-01-01",
        expiry_date="2027-01-01", issuing_authority="OSHA"))
    assert is_ok(cert), cert
    gone = call_action(mod.ACTIONS["construction-add-safety-cert"], conn, ns(
        company_id=env["company_id"], job_id=job_id, worker_name="Zed",
        cert_type="osha_10", cert_number="O-2", issued_date="2025-01-01",
        expiry_date="2025-06-01", issuing_authority="OSHA"))
    assert is_ok(call_action(mod.ACTIONS["construction-expire-safety-cert"],
                             conn,
                             ns(safety_cert_id=gone["safety_cert_id"])))

    incidents = _verify(
        "SELECT id, incident_type, severity, osha_recordable, days_lost,"
        " incident_status FROM constructclaw_incident WHERE company_id = ?",
        (env["company_id"],))
    assert len(incidents) == 2
    by_id = {d["id"]: d for d in incidents}
    assert (by_id[i1]["incident_type"], by_id[i1]["osha_recordable"],
            by_id[i1]["days_lost"]) == ("lost_time", 1, 3)
    assert (by_id[i2]["incident_type"], by_id[i2]["osha_recordable"],
            by_id[i2]["days_lost"]) == ("near_miss", 0, 0)

    tables = ["constructclaw_incident", "constructclaw_toolbox_talk",
              "constructclaw_safety_cert", "audit_log"]
    before = _snap(conn, tables)
    r = call_action(mod.ACTIONS["construction-safety-dashboard"], conn,
                    ns(company_id=env["company_id"]))
    assert is_ok(r), r
    assert r["total_incidents"] == 2
    assert r["open_incidents"] == 2
    assert r["osha_recordable"] == 1
    assert r["total_days_lost"] == 3
    assert r["toolbox_talks_conducted"] == 1
    assert r["expiring_certifications"] == 1
    assert r["by_severity"] == {"serious": 1, "minor": 1}
    assert _snap(conn, tables) == before


def test_safety_dashboard_refuses_without_company(conn, env, mod):
    tables = ["constructclaw_incident", "constructclaw_toolbox_talk",
              "constructclaw_safety_cert", "audit_log"]
    before = _snap(conn, tables)
    r = call_action(mod.ACTIONS["construction-safety-dashboard"], conn,
                    ns(company_id=None))
    assert is_error(r), r
    assert r["message"] == "--company-id is required"
    assert _snap(conn, tables) == before


# ---------------------------------------------------------------------------
# Filter-only lists have no input validation: document the real behaviour.
# ---------------------------------------------------------------------------

def test_filter_only_lists_have_no_refusal_and_write_nothing(conn, env, mod):
    # Seven of the 12 actions take only optional filters, so there is no
    # refusal to test: missing filters return ok (possibly empty) and, like
    # every action here, write nothing. This test pins that real behaviour so
    # a later validation cannot half-write, and proves each route is live.
    # No GL posting on any of these: read-only SELECTs, no ledger legs.
    job_id = _job(conn, env, mod)
    tables = ["constructclaw_daily_material", "constructclaw_pay_application",
              "constructclaw_progress_bill", "constructclaw_safety_cert",
              "constructclaw_schedule_of_values", "constructclaw_submittal",
              "audit_log"]
    before = _snap(conn, tables)
    empty_calls = [
        ("construction-list-material-requisitions",
         ns(company_id=None, job_id=None)),
        ("construction-list-pay-applications",
         ns(subcontract_id=None, company_id=None, pay_app_status=None)),
        ("construction-list-progress-bills",
         ns(company_id=None, job_id=None, bill_status=None)),
        ("construction-list-safety-certs",
         ns(company_id=None, job_id=None, worker_name=None,
            cert_status=None)),
        ("construction-list-schedules-of-values",
         ns(company_id=None, job_id=None)),
        ("construction-list-submittals",
         ns(company_id=None, job_id=None, submittal_status=None, search=None,
            limit=50, offset=0)),
    ]
    for action_name, args in empty_calls:
        r = call_action(mod.ACTIONS[action_name], conn, args)
        assert is_ok(r), (action_name, r)
    assert _snap(conn, tables) == before
    assert job_id
