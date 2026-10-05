"""M441 depth: behavioural evidence for 9 shape-or-routing-only actions.

Prior state (each existing test read before anything below was written):
- `construction-safety-report` had one module test
  (`TestReports.test_safety_report` in `test_safety_controls.py`): it calls
  the action on an empty company and asserts only that the response is ok
  and carries `total_incidents` / `osha_recordable` keys. It never creates
  an incident, so it cannot tell a correct count from a hardcoded zero.
- The other eight actions had NO module test at all. They were covered only
  by box-facing routability contracts in
  `testing/integration/contract/test_constructclaw_contract.py`
  (`test_construction_*_exists`), each of which asserts the action name is
  recognised, not what the action does to the database.

Every test below observes the database through a fresh `get_connection()`
read-back built with PyPika (`erpclaw_lib.query`): the row that should exist
afterwards with exact values, the row that should have changed from what to
what, and what must NOT have changed (the success path asserts the full
snapshot differs only in the tables the action owns plus `audit_log`; the
read-only paths assert the snapshot is identical before and after;
update paths assert it differs only in the tables the action owns).
Catalog questions (does the table exist) go through `erpclaw_lib.seam`.
Money compares exact `Decimal` values as strings, never float, never
approximate, never `round`.

Ledger scope, stated once so no later reader adds a balance assertion that
cannot hold: none of these 9 handlers reaches the general ledger. The four
report actions are pure SELECTs; the four update actions rewrite only their
own vertical table (plus one `audit_log` line each, except
update-estimate-line, which writes none -- see its pinned assertion); the
delivery tracker
would rewrite only its own table if its UPDATE named a real column (see the
BROKEN note in its section). Every per-action section repeats its own
ledger note.

Signal depth per action (stored row in every case; no ledger effect):
- construction-safety-report: stored rows (aggregates recomputed from rows).
- construction-subcontractor-aging: stored rows (per-sub paid/remaining).
- construction-subcontractor-aging-report: stored rows (per-sub + totals).
- construction-track-material-delivery: BROKEN -- documents the real error.
- construction-update-estimate-line: stored row (line + parent total).
- construction-update-rfi: stored row (RFI fields from/to).
- construction-update-subcontract: stored row (money fields from/to).
- construction-update-submittal: stored row (submittal fields from/to).
- construction-wip-report: stored rows (earned/cost/billed recomputed).
"""
import os
import sys

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from decimal import Decimal

import pytest

from construct_helpers import (
    build_env,
    call_action,
    is_error,
    is_ok,
    load_db_query,
    ns,
    seed_company,
    seed_naming_series,
)
from erpclaw_lib.db import db_error_types, get_connection
from erpclaw_lib.query import Q, P, Table, Field, fn
from erpclaw_lib import seam as _seam
from buying_harness import delegate_buying_in_process, seed_supplier


@pytest.fixture(autouse=True)
def _buying_bridge(dconn, monkeypatch):
    """Setup only: approvals post their payable through the buying module."""
    return delegate_buying_in_process(dconn, monkeypatch)


@pytest.fixture
def mod():
    return load_db_query()


@pytest.fixture
def dconn(db_path):
    """Fresh database connection via the library entry point.

    The `db_path` fixture (see conftest.py) creates a per-test database
    with the full core + constructclaw schema; this fixture opens it the
    way production code does, so both the action calls and the read-backs
    below go through `erpclaw_lib.db.get_connection()`.
    """
    conn = get_connection(db_path)
    yield conn
    conn.close()


@pytest.fixture
def denv(dconn):
    return build_env(dconn)


_MISSING_TABLE_EXCS, _DB_ERROR = db_error_types()

SNAPSHOT_TABLES = (
    "company",
    "customer",
    "naming_series",
    "audit_log",
    "constructclaw_job",
    "constructclaw_cost_code",
    "constructclaw_cost_entry",
    "constructclaw_estimate",
    "constructclaw_estimate_line",
    "constructclaw_subcontract",
    "constructclaw_pay_application",
    "constructclaw_rfi",
    "constructclaw_submittal",
    "constructclaw_incident",
    "constructclaw_toolbox_talk",
    "constructclaw_progress_bill",
    "constructclaw_daily_report",
    "constructclaw_daily_material",
)


def _check_catalog(db_path):
    for name in SNAPSHOT_TABLES:
        assert _seam.table_exists(name, db_path), name


def _snapshot(conn):
    snap = {}
    for name in SNAPSHOT_TABLES:
        t = Table(name)
        rows = conn.execute(Q.from_(t).select("*").get_sql()).fetchall()
        snap[name] = sorted(repr(dict(r)) for r in rows)
    return snap


def _changed_tables(before, after):
    return sorted(n for n in SNAPSHOT_TABLES if before[n] != after[n])


def _row(conn, table, row_id):
    t = Table(table)
    row = conn.execute(
        Q.from_(t).select("*").where(t.id == P()).get_sql(), (row_id,)).fetchone()
    return dict(row) if row is not None else None


def _rows_where(conn, table, column, value):
    t = Table(table)
    return [dict(r) for r in conn.execute(
        Q.from_(t).select("*").where(Field(column) == P()).get_sql(),
        (value,)).fetchall()]


def _count(conn, table):
    t = Table(table)
    return conn.execute(Q.from_(t).select(fn.Count("*")).get_sql()).fetchone()[0]


def _audit_rows(conn, action, entity_id):
    t = Table("audit_log")
    return [dict(r) for r in conn.execute(
        Q.from_(t).select("*").where(t.action == P()).get_sql(),
        (action,)).fetchall() if r["entity_id"] == entity_id]


# ---------------------------------------------------------------------------
# Setup helpers (all writes go through the actions under test, never around)
# ---------------------------------------------------------------------------

def _add_job(conn, mod, company_id, name="Depth Job", amount="1000000"):
    r = call_action(mod.ACTIONS["construction-add-job"], conn, ns(
        company_id=company_id, name=name,
        job_type=None, contract_type=None, contract_amount=amount,
        client_name=None, client_id=None, description=None,
        project_manager=None, superintendent=None,
        start_date=None, end_date=None, address=None,
        city=None, state=None, zip_code=None, notes=None))
    assert is_ok(r), r
    return r["job_id"]


def _set_percent(conn, mod, job_id, percent):
    r = call_action(mod.ACTIONS["construction-update-job"], conn, ns(
        job_id=job_id, percent_complete=percent))
    assert is_ok(r), r


def _add_cost_code(conn, mod, company_id, job_id, code, budget):
    r = call_action(mod.ACTIONS["construction-add-cost-code"], conn, ns(
        company_id=company_id, job_id=job_id,
        code=code, description="depth budget", category="labor",
        budget_amount=budget, budget_hours=None))
    assert is_ok(r), r
    return r["cost_code_id"]


def _add_cost(conn, mod, company_id, job_id, amount, category="labor"):
    r = call_action(mod.ACTIONS["construction-add-cost-entry"], conn, ns(
        company_id=company_id, job_id=job_id, cost_code_id=None,
        category=category, description="depth cost", amount=amount,
        quantity=None, unit_cost=None, vendor=None, reference=None,
        hours=None, entry_date=None))
    assert is_ok(r), r
    return r["cost_entry_id"]


def _add_bill(conn, mod, company_id, job_id, completed, retention):
    r = call_action(mod.ACTIONS["construction-add-progress-bill"], conn, ns(
        company_id=company_id, job_id=job_id, sov_id=None,
        total_completed=completed, total_retention=retention,
        period_from=None, period_to=None, notes=None))
    assert is_ok(r), r
    return r["progress_bill_id"]


def _add_estimate(conn, mod, company_id, job_id=None, name="Depth Estimate"):
    r = call_action(mod.ACTIONS["construction-add-estimate"], conn, ns(
        company_id=company_id, job_id=job_id, name=name,
        client_name=None, description=None, due_date=None,
        markup_pct=None, overhead_pct=None, profit_pct=None, notes=None))
    assert is_ok(r), r
    return r["estimate_id"]


def _add_line(conn, mod, company_id, estimate_id, description,
              category="material", quantity=None, unit_cost=None, amount=None):
    r = call_action(mod.ACTIONS["construction-add-estimate-line"], conn, ns(
        company_id=company_id, estimate_id=estimate_id,
        description=description, category=category, quantity=quantity,
        unit=None, unit_cost=unit_cost, amount=amount, notes=None))
    assert is_ok(r), r
    return r["line_id"]


def _add_sub(conn, mod, company_id, job_id, name, amount="250000"):
    supplier_id = seed_supplier(conn, company_id)
    r = call_action(mod.ACTIONS["construction-add-subcontract"], conn, ns(
        company_id=company_id, job_id=job_id, subcontractor_name=name,
        trade="electrical", scope_of_work=None, original_amount=amount,
        retention_pct=None, insurance_expiry=None, license_number=None,
        start_date=None, end_date=None, notes=None,
        supplier_id=supplier_id))
    assert is_ok(r), r
    return r["subcontract_id"]


def _add_pay_app(conn, mod, company_id, subcontract_id, work_completed):
    r = call_action(mod.ACTIONS["construction-add-pay-application"], conn, ns(
        company_id=company_id, subcontract_id=subcontract_id,
        work_completed=work_completed, materials_stored=None,
        period_from=None, period_to=None, notes=None))
    assert is_ok(r), r
    return r["pay_application_id"]


def _approve_pay_app(conn, mod, pay_application_id):
    r = call_action(mod.ACTIONS["construction-approve-pay-application"], conn, ns(
        pay_application_id=pay_application_id))
    assert is_ok(r), r


def _add_rfi(conn, mod, company_id, job_id, subject="Clarify footing depth"):
    r = call_action(mod.ACTIONS["construction-add-rfi"], conn, ns(
        company_id=company_id, job_id=job_id, subject=subject,
        question="What is the footing depth at grid B4?",
        initiated_by="Site Engineer", assigned_to=None, priority=None,
        date_required=None, cost_impact=None, schedule_impact_days=None,
        notes=None))
    assert is_ok(r), r
    return r["rfi_id"]


def _add_submittal(conn, mod, company_id, job_id, title="Steel shop drawings"):
    r = call_action(mod.ACTIONS["construction-add-submittal"], conn, ns(
        company_id=company_id, job_id=job_id, title=title,
        spec_section="03 30 00", description=None, submitted_by=None,
        submitted_to=None, date_required=None, notes=None))
    assert is_ok(r), r
    return r["submittal_id"]


def _add_incident(conn, mod, company_id, job_id, incident_type,
                  severity="minor", days_lost=None):
    r = call_action(mod.ACTIONS["construction-add-incident"], conn, ns(
        company_id=company_id, job_id=job_id, description="depth incident",
        incident_type=incident_type, severity=severity,
        incident_date=None, incident_time=None, location=None,
        injured_party=None, witnesses=None, root_cause=None,
        corrective_action=None, days_lost=days_lost, notes=None))
    assert is_ok(r), r
    return r["incident_id"]


def _add_talk(conn, mod, company_id, job_id, topic):
    r = call_action(mod.ACTIONS["construction-add-toolbox-talk"], conn, ns(
        company_id=company_id, job_id=job_id, topic=topic,
        talk_date=None, presenter=None, attendee_count=None,
        attendees=None, duration_minutes=None, notes=None))
    assert is_ok(r), r
    return r["toolbox_talk_id"]


def _add_daily_material(conn, mod, company_id, job_id,
                        name="Rebar #5", quantity="100", supplier="Acme Steel"):
    dr = call_action(mod.ACTIONS["construction-add-daily-report"], conn, ns(
        company_id=company_id, job_id=job_id, report_date=None,
        superintendent=None, weather=None, temperature_high=None,
        temperature_low=None, work_description=None, delays=None,
        visitors=None, notes=None))
    assert is_ok(dr), dr
    m = call_action(mod.ACTIONS["construction-add-daily-material"], conn, ns(
        company_id=company_id, daily_report_id=dr["daily_report_id"],
        material_name=name, quantity=quantity, unit=None,
        supplier=supplier, delivery_ticket=None))
    assert is_ok(m), m
    return m["daily_material_id"]


# ---------------------------------------------------------------------------
# construction-safety-report -- stored rows (read-only aggregates).
# No ledger effect: pure SELECTs over incident / toolbox tables.
# ---------------------------------------------------------------------------
class TestSafetyReportDepth:
    def test_counts_match_stored_rows_and_read_changes_nothing(
            self, dconn, denv, mod, db_path):
        _check_catalog(db_path)
        cid = denv["company_id"]
        job_id = _add_job(dconn, mod, cid)
        _add_incident(dconn, mod, cid, job_id, "lost_time",
                      severity="serious", days_lost="5")
        _add_incident(dconn, mod, cid, job_id, "near_miss")
        _add_talk(dconn, mod, cid, job_id, "Fall protection")
        _add_talk(dconn, mod, cid, job_id, "Heat stress")

        other_cid = seed_company(dconn, name="Other Co", abbr="OC")
        seed_naming_series(dconn, other_cid)
        other_job = _add_job(dconn, mod, other_cid, name="Other Job")
        _add_incident(dconn, mod, other_cid, other_job, "fatality",
                      severity="fatal", days_lost="9")

        incidents = _rows_where(dconn, "constructclaw_incident", "company_id", cid)
        assert len(incidents) == 2
        assert sum(1 for i in incidents if i["osha_recordable"] == 1) == 1
        assert sum(int(i["days_lost"]) for i in incidents) == 5
        assert len(_rows_where(dconn, "constructclaw_toolbox_talk",
                               "company_id", cid)) == 2

        before = _snapshot(dconn)
        r = call_action(mod.ACTIONS["construction-safety-report"], dconn, ns(
            company_id=cid))
        assert is_ok(r), r
        assert r["total_incidents"] == 2
        assert r["osha_recordable"] == 1
        assert int(r["days_lost"]) == 5
        assert r["toolbox_talks"] == 2
        assert _snapshot(dconn) == before

    def test_refuses_without_company_and_writes_nothing(
            self, dconn, denv, mod):
        before = _snapshot(dconn)
        r = call_action(mod.ACTIONS["construction-safety-report"], dconn, ns(
            company_id=None))
        assert is_error(r)
        assert r["message"] == "--company-id is required"
        assert _snapshot(dconn) == before


# ---------------------------------------------------------------------------
# construction-subcontractor-aging -- stored rows (read-only per-sub math).
# No ledger effect: pure SELECTs over subcontract / pay-application tables.
# ---------------------------------------------------------------------------
class TestSubcontractorAgingDepth:
    def _setup(self, dconn, denv, mod):
        cid = denv["company_id"]
        job_id = _add_job(dconn, mod, cid)
        sub_id = _add_sub(dconn, mod, cid, job_id, "Elite Electrical")
        pa_id = _add_pay_app(dconn, mod, cid, sub_id, "100000")
        _approve_pay_app(dconn, mod, pa_id)
        draft_id = _add_pay_app(dconn, mod, cid, sub_id, "50000")
        cancelled = _add_sub(dconn, mod, cid, job_id, "Gone Builders",
                             amount="75000")
        r = call_action(mod.ACTIONS["construction-update-subcontract"],
                        dconn, ns(subcontract_id=cancelled,
                                  subcontract_status="cancelled"))
        assert is_ok(r), r
        return cid, sub_id, draft_id, cancelled

    def test_paid_and_remaining_match_stored_rows(self, dconn, denv, mod):
        cid, sub_id, draft_id, cancelled = self._setup(dconn, denv, mod)

        pa = _row(dconn, "constructclaw_pay_application",
                  _rows_where(dconn, "constructclaw_pay_application",
                              "subcontract_id", sub_id)[0]["id"])
        assert pa["pay_app_status"] in ("approved", "paid")
        assert Decimal(pa["current_payment_due"]) == Decimal("90000.00")
        assert _row(dconn, "constructclaw_pay_application",
                    draft_id)["pay_app_status"] == "draft"

        before = _snapshot(dconn)
        r = call_action(mod.ACTIONS["construction-subcontractor-aging"],
                        dconn, ns(company_id=cid))
        assert is_ok(r), r
        assert r["total_count"] == 1
        entry = r["subcontractors"][0]
        assert entry["subcontract_id"] == sub_id
        assert entry["contract_amount"] == "250000.00"
        assert entry["paid"] == "90000.00"
        assert entry["remaining"] == "160000.00"
        assert all(e["subcontract_id"] != cancelled
                   for e in r["subcontractors"])
        assert _snapshot(dconn) == before

    def test_refuses_without_company_and_writes_nothing(
            self, dconn, denv, mod):
        before = _snapshot(dconn)
        r = call_action(mod.ACTIONS["construction-subcontractor-aging"],
                        dconn, ns(company_id=None))
        assert is_error(r)
        assert r["message"] == "--company-id is required"
        assert _snapshot(dconn) == before


# ---------------------------------------------------------------------------
# construction-subcontractor-aging-report -- stored rows (per-sub + totals).
# No ledger effect: pure SELECTs; retention is read, not posted.
# ---------------------------------------------------------------------------
class TestSubcontractorAgingReportDepth:
    def test_totals_match_stored_rows_and_draft_is_excluded(
            self, dconn, denv, mod):
        cid = denv["company_id"]
        job_id = _add_job(dconn, mod, cid)
        sub_id = _add_sub(dconn, mod, cid, job_id, "Elite Electrical")
        pa_id = _add_pay_app(dconn, mod, cid, sub_id, "100000")
        _approve_pay_app(dconn, mod, pa_id)
        _add_pay_app(dconn, mod, cid, sub_id, "50000")

        pa = [p for p in _rows_where(dconn, "constructclaw_pay_application",
                                     "subcontract_id", sub_id)
              if p["pay_app_status"] in ("approved", "paid")]
        assert len(pa) == 1
        assert Decimal(pa[0]["current_payment_due"]) == Decimal("90000.00")
        assert Decimal(pa[0]["retention_held"]) == Decimal("10000.00")

        before = _snapshot(dconn)
        r = call_action(
            mod.ACTIONS["construction-subcontractor-aging-report"],
            dconn, ns(company_id=cid))
        assert is_ok(r), r
        assert r["total_count"] == 1
        entry = r["subcontractors"][0]
        assert entry["subcontract_id"] == sub_id
        assert entry["contract_amount"] == "250000.00"
        assert entry["paid"] == "90000.00"
        assert entry["retention_held"] == "10000.00"
        assert entry["remaining"] == "150000.00"
        assert r["total_committed"] == "250000.00"
        assert r["total_paid"] == "90000.00"
        assert r["total_retention"] == "10000.00"
        assert _snapshot(dconn) == before

    def test_refuses_without_company_and_writes_nothing(
            self, dconn, denv, mod):
        before = _snapshot(dconn)
        r = call_action(
            mod.ACTIONS["construction-subcontractor-aging-report"],
            dconn, ns(company_id=None))
        assert is_error(r)
        assert r["message"] == "--company-id is required"
        assert _snapshot(dconn) == before


# ---------------------------------------------------------------------------
# construction-track-material-delivery -- BROKEN, documents real behaviour.
# Intended effect: set status='delivered' (+ticket/supplier/notes) on the
# constructclaw_daily_material row. Real behaviour: the UPDATE names columns
# (`status`, `notes`) the table does not have, so the database raises
# `no such column: status` and nothing is written. NOT FIXED here by task
# rule; this test pins the failure so the fix task has a true signal.
# No ledger effect either way: the handler never reaches ledger tables.
# ---------------------------------------------------------------------------
class TestTrackMaterialDeliveryDepth:
    def test_broken_update_raises_and_writes_nothing(
            self, dconn, denv, mod):
        cid = denv["company_id"]
        job_id = _add_job(dconn, mod, cid)
        mat_id = _add_daily_material(dconn, mod, cid, job_id)
        stored = _row(dconn, "constructclaw_daily_material", mat_id)
        assert stored["material_name"] == "Rebar #5"
        assert Decimal(stored["quantity"]) == Decimal("100")
        assert stored["supplier"] == "Acme Steel"
        assert stored["delivery_ticket"] is None

        before = _snapshot(dconn)
        with pytest.raises(_MISSING_TABLE_EXCS,
                           match="no such column: status"):
            call_action(
                mod.ACTIONS["construction-track-material-delivery"],
                dconn, ns(material_id=mat_id, delivery_ticket="T-7788",
                          supplier="Acme Steel Co", notes="Left at gate B"))
        assert _snapshot(dconn) == before
        after = _row(dconn, "constructclaw_daily_material", mat_id)
        assert after["supplier"] == "Acme Steel"
        assert after["delivery_ticket"] is None

    def test_refuses_unknown_material_and_writes_nothing(
            self, dconn, denv, mod):
        bad_id = "00000000-0000-0000-0000-000000000000"
        before = _snapshot(dconn)
        r = call_action(
            mod.ACTIONS["construction-track-material-delivery"],
            dconn, ns(material_id=bad_id, delivery_ticket=None,
                      supplier=None, notes=None))
        assert is_error(r)
        assert r["message"] == f"Material record {bad_id} not found"
        assert _snapshot(dconn) == before


# ---------------------------------------------------------------------------
# construction-update-estimate-line -- stored row (line + parent total).
# No ledger effect: rewrites the line and the parent estimate total only
# (and, unlike its siblings, no audit_log line -- see the pinned assertion
# in the success test); never touches journal/gl tables.
# ---------------------------------------------------------------------------
class TestUpdateEstimateLineDepth:
    def _setup(self, dconn, denv, mod):
        cid = denv["company_id"]
        est_id = _add_estimate(dconn, mod, cid)
        line_id = _add_line(dconn, mod, cid, est_id, "Concrete",
                            quantity="10", unit_cost="100")
        other_id = _add_line(dconn, mod, cid, est_id, "Rebar",
                             category="material", amount="2000.00")
        assert _row(dconn, "constructclaw_estimate_line",
                    line_id)["amount"] == "1000.00"
        assert _row(dconn, "constructclaw_estimate",
                    est_id)["total_amount"] == "3000.00"
        return est_id, line_id, other_id

    def test_amount_moves_line_and_parent_total(self, dconn, denv, mod):
        est_id, line_id, other_id = self._setup(dconn, denv, mod)
        before = _snapshot(dconn)
        r = call_action(mod.ACTIONS["construction-update-estimate-line"],
                        dconn, ns(line_id=line_id, amount="1500.00",
                                  description=None, quantity=None, unit=None,
                                  unit_cost=None, notes=None, category=None))
        assert is_ok(r), r
        assert r["estimate_total"] == "3500.00"

        line = _row(dconn, "constructclaw_estimate_line", line_id)
        assert Decimal(line["amount"]) == Decimal("1500.00")
        assert line["description"] == "Concrete"
        assert Decimal(line["quantity"]) == Decimal("10")
        other = _row(dconn, "constructclaw_estimate_line", other_id)
        assert Decimal(other["amount"]) == Decimal("2000.00")
        est = _row(dconn, "constructclaw_estimate", est_id)
        assert Decimal(est["total_amount"]) == Decimal("3500.00")
        # Real behaviour, pinned deliberately: unlike its sibling update
        # handlers (update-rfi / update-subcontract / update-submittal, each
        # asserted below to leave one audit_log row), update-estimate-line
        # never calls audit(), so no audit_log row appears. Recorded as a
        # finding in CHANGES.md; not fixed here.
        assert _changed_tables(before, _snapshot(dconn)) == [
            "constructclaw_estimate", "constructclaw_estimate_line"]
        assert len(_audit_rows(dconn, "construction-update-estimate-line",
                               line_id)) == 0

    def test_refuses_bad_category_and_writes_nothing(self, dconn, denv, mod):
        est_id, line_id, _other = self._setup(dconn, denv, mod)
        before = _snapshot(dconn)
        r = call_action(mod.ACTIONS["construction-update-estimate-line"],
                        dconn, ns(line_id=line_id, category="bogus",
                                  description=None, quantity=None, unit=None,
                                  unit_cost=None, amount=None, notes=None))
        assert is_error(r)
        assert r["message"] == "Invalid category: bogus"
        assert _snapshot(dconn) == before
        assert _row(dconn, "constructclaw_estimate_line",
                    line_id)["amount"] == "1000.00"
        assert _row(dconn, "constructclaw_estimate",
                    est_id)["total_amount"] == "3000.00"


# ---------------------------------------------------------------------------
# construction-update-rfi -- stored row (named fields move, rest stay).
# No ledger effect: rewrites the RFI row only, plus one audit_log line.
# ---------------------------------------------------------------------------
class TestUpdateRfiDepth:
    def test_subject_and_priority_move_and_rest_stays(self, dconn, denv, mod):
        cid = denv["company_id"]
        job_id = _add_job(dconn, mod, cid)
        rfi_id = _add_rfi(dconn, mod, cid, job_id)
        stored = _row(dconn, "constructclaw_rfi", rfi_id)
        assert stored["subject"] == "Clarify footing depth"
        assert stored["priority"] == "normal"

        before = _snapshot(dconn)
        r = call_action(mod.ACTIONS["construction-update-rfi"], dconn, ns(
            rfi_id=rfi_id, subject="Revised: footing depth at grid B4",
            priority="high", question=None, initiated_by=None,
            assigned_to=None, date_required=None, cost_impact=None,
            schedule_impact_days=None, notes=None))
        assert is_ok(r), r
        assert sorted(r["updated_fields"]) == ["priority", "subject"]

        after = _row(dconn, "constructclaw_rfi", rfi_id)
        assert after["subject"] == "Revised: footing depth at grid B4"
        assert after["priority"] == "high"
        assert after["question"] == stored["question"]
        assert after["job_id"] == stored["job_id"]
        assert after["initiated_by"] == stored["initiated_by"]
        assert _changed_tables(before, _snapshot(dconn)) == [
            "audit_log", "constructclaw_rfi"]
        assert len(_audit_rows(dconn, "construction-update-rfi",
                               rfi_id)) == 1

    def test_refuses_bad_priority_and_writes_nothing(self, dconn, denv, mod):
        cid = denv["company_id"]
        job_id = _add_job(dconn, mod, cid)
        rfi_id = _add_rfi(dconn, mod, cid, job_id)
        before = _snapshot(dconn)
        r = call_action(mod.ACTIONS["construction-update-rfi"], dconn, ns(
            rfi_id=rfi_id, priority="urgent", subject=None, question=None,
            initiated_by=None, assigned_to=None, date_required=None,
            cost_impact=None, schedule_impact_days=None, notes=None))
        assert is_error(r)
        assert r["message"] == "Invalid priority: urgent"
        assert _snapshot(dconn) == before
        assert _row(dconn, "constructclaw_rfi", rfi_id)["priority"] == "normal"


# ---------------------------------------------------------------------------
# construction-update-subcontract -- stored row (money from/to exact).
# No ledger effect: rewrites the subcontract row only, plus one audit_log
# line; pay applications and the ledger are untouched.
# ---------------------------------------------------------------------------
class TestUpdateSubcontractDepth:
    def test_revised_amount_moves_and_original_stays(self, dconn, denv, mod):
        cid = denv["company_id"]
        job_id = _add_job(dconn, mod, cid)
        sub_id = _add_sub(dconn, mod, cid, job_id, "Elite Electrical")
        stored = _row(dconn, "constructclaw_subcontract", sub_id)
        assert Decimal(stored["original_amount"]) == Decimal("250000")
        assert Decimal(stored["revised_amount"]) == Decimal("250000")
        assert stored["notes"] is None

        before = _snapshot(dconn)
        r = call_action(mod.ACTIONS["construction-update-subcontract"],
                        dconn, ns(subcontract_id=sub_id,
                                  revised_amount="275000",
                                  notes="Increase for overtime",
                                  subcontractor_name=None, trade=None,
                                  scope_of_work=None, original_amount=None,
                                  retention_pct=None, insurance_expiry=None,
                                  license_number=None, start_date=None,
                                  end_date=None, subcontract_status=None))
        assert is_ok(r), r
        assert sorted(r["updated_fields"]) == ["notes", "revised_amount"]

        after = _row(dconn, "constructclaw_subcontract", sub_id)
        assert Decimal(after["revised_amount"]) == Decimal("275000")
        assert after["notes"] == "Increase for overtime"
        assert Decimal(after["original_amount"]) == Decimal("250000")
        assert after["trade"] == stored["trade"]
        assert _changed_tables(before, _snapshot(dconn)) == [
            "audit_log", "constructclaw_subcontract"]
        assert len(_audit_rows(dconn, "construction-update-subcontract",
                               sub_id)) == 1

    def test_refuses_bad_status_and_writes_nothing(self, dconn, denv, mod):
        cid = denv["company_id"]
        job_id = _add_job(dconn, mod, cid)
        sub_id = _add_sub(dconn, mod, cid, job_id, "Elite Electrical")
        before = _snapshot(dconn)
        r = call_action(mod.ACTIONS["construction-update-subcontract"],
                        dconn, ns(subcontract_id=sub_id,
                                  subcontract_status="flying"))
        assert is_error(r)
        assert r["message"] == "Invalid subcontract-status: flying"
        assert _snapshot(dconn) == before
        assert Decimal(_row(dconn, "constructclaw_subcontract",
                            sub_id)["revised_amount"]) == Decimal("250000")


# ---------------------------------------------------------------------------
# construction-update-submittal -- stored row (named fields move, rest stay).
# No ledger effect: rewrites the submittal row only, plus one audit_log line.
# ---------------------------------------------------------------------------
class TestUpdateSubmittalDepth:
    def test_title_and_description_move_and_rest_stays(
            self, dconn, denv, mod):
        cid = denv["company_id"]
        job_id = _add_job(dconn, mod, cid)
        sub_id = _add_submittal(dconn, mod, cid, job_id)
        stored = _row(dconn, "constructclaw_submittal", sub_id)
        assert stored["title"] == "Steel shop drawings"
        assert stored["description"] is None

        before = _snapshot(dconn)
        r = call_action(mod.ACTIONS["construction-update-submittal"],
                        dconn, ns(submittal_id=sub_id,
                                  title="Steel shop drawings - rev 2",
                                  description="Resubmitted with corrections",
                                  spec_section=None, submitted_by=None,
                                  submitted_to=None, date_required=None,
                                  notes=None))
        assert is_ok(r), r
        assert sorted(r["updated_fields"]) == ["description", "title"]

        after = _row(dconn, "constructclaw_submittal", sub_id)
        assert after["title"] == "Steel shop drawings - rev 2"
        assert after["description"] == "Resubmitted with corrections"
        assert after["spec_section"] == stored["spec_section"]
        assert after["job_id"] == stored["job_id"]
        assert _changed_tables(before, _snapshot(dconn)) == [
            "audit_log", "constructclaw_submittal"]
        assert len(_audit_rows(dconn, "construction-update-submittal",
                               sub_id)) == 1

    def test_refuses_unknown_submittal_and_writes_nothing(
            self, dconn, denv, mod):
        bad_id = "00000000-0000-0000-0000-000000000000"
        before = _snapshot(dconn)
        r = call_action(mod.ACTIONS["construction-update-submittal"],
                        dconn, ns(submittal_id=bad_id, title="Ghost",
                                  description=None, spec_section=None,
                                  submitted_by=None, submitted_to=None,
                                  date_required=None, notes=None))
        assert is_error(r)
        assert r["message"] == f"Submittal {bad_id} not found"
        assert _snapshot(dconn) == before


# ---------------------------------------------------------------------------
# construction-wip-report -- stored rows (earned/cost/billed recomputed).
# No ledger effect: pure SELECTs over job / cost-entry / progress-bill
# tables; the report derives earned revenue by arithmetic, not postings.
# ---------------------------------------------------------------------------
class TestWipReportDepth:
    def test_derivation_matches_stored_rows_and_read_changes_nothing(
            self, dconn, denv, mod):
        cid = denv["company_id"]
        job_id = _add_job(dconn, mod, cid)
        _set_percent(dconn, mod, job_id, "25")
        _add_cost_code(dconn, mod, cid, job_id, "01-100", "200000")
        _add_cost_code(dconn, mod, cid, job_id, "02-200", "400000")
        _add_cost(dconn, mod, cid, job_id, "100000")
        _add_cost(dconn, mod, cid, job_id, "50000", category="material")
        bill_id = _add_bill(dconn, mod, cid, job_id, "200000", "20000")
        other_job = _add_job(dconn, mod, cid, name="Other Job",
                             amount="500000")
        other_bill = _add_bill(dconn, mod, cid, other_job, "50000", "5000")
        assert Decimal(_row(dconn, "constructclaw_progress_bill",
                            other_bill)["current_due"]) == Decimal("45000.00")

        job = _row(dconn, "constructclaw_job", job_id)
        assert Decimal(job["contract_amount"]) == Decimal("1000000")
        assert Decimal(job["percent_complete"]) == Decimal("25")
        costs = _rows_where(dconn, "constructclaw_cost_entry", "job_id",
                            job_id)
        assert sum(Decimal(c["amount"]) for c in costs) == Decimal("150000")
        bills = [b for b in _rows_where(dconn, "constructclaw_progress_bill",
                                        "job_id", job_id)
                 if b["bill_status"] != "rejected"]
        assert len(bills) == 1
        assert Decimal(bills[0]["current_due"]) == Decimal("180000.00")

        before = _snapshot(dconn)
        r = call_action(mod.ACTIONS["construction-wip-report"], dconn, ns(
            job_id=job_id))
        assert is_ok(r), r
        assert r["contract_amount"] == "1000000.00"
        assert r["estimated_total_cost"] == "600000.00"
        assert r["percent_complete"] == "25.00"
        assert r["earned_revenue"] == "250000.00"
        assert r["total_cost"] == "150000.00"
        assert r["total_billed"] == "180000.00"
        assert r["over_under_billing"] == "-70000.00"
        assert r["billing_status"] == "underbilled"
        assert _snapshot(dconn) == before

    def test_refuses_unknown_job_and_writes_nothing(self, dconn, denv, mod):
        bad_id = "00000000-0000-0000-0000-000000000000"
        before = _snapshot(dconn)
        r = call_action(mod.ACTIONS["construction-wip-report"], dconn, ns(
            job_id=bad_id))
        assert is_error(r)
        assert r["message"] == f"Job {bad_id} not found"
        assert _snapshot(dconn) == before
