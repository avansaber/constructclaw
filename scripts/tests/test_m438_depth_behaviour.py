"""M438 depth: behavioural evidence for the 12 shape/routing-only actions.

Each action below already had a test that proved the wrong thing (response
shape or routability via the contract suite). Each test here proves the
database effect instead: what row exists afterwards with which exact values,
what changed from what to what, and what did not change. Money is TEXT:
exact string comparisons, Decimal for arithmetic, never float, never round().

Per-action depth signal (acceptance item 3):
  stored-row effect (a row is written, then verified by re-read):
    - construction-add-subcontract-line .... STORED ROW (subcontract_line)
    - construction-batch-add-cost-codes .... STORED ROWS (cost_code + 1 audit)
  stored-row read (read-only; response values verified against re-read rows,
  plus proof the call wrote nothing):
    - construction-billing-summary ......... STORED-ROW READ (aggregates)
    - construction-daily-summary ........... STORED-ROW READ (aggregates)
    - construction-executive-summary ....... STORED-ROW READ (aggregates)
    - construction-get-cco ................. STORED-ROW READ (cco row)
    - construction-get-daily-report ........ STORED-ROW READ (report+labor+material)
    - construction-get-incident ............ STORED-ROW READ (incident row)
    - construction-get-pay-application ..... STORED-ROW READ (pay_application row)
    - construction-get-pco ................. STORED-ROW READ (pco row)
  broken (raises before writing; test pins the real behaviour + no write):
    - construction-add-drawing ............. BROKEN (OperationalError, §BROKEN)
    - construction-create-material-requisition  BROKEN (OperationalError, §BROKEN)

Ledger note: NONE of these 12 actions posts to the general ledger on its
success path (the writers touch constructclaw tables only; the getters and
summaries are reads), so no success test below asserts new ledger legs.
Every success test pins the gl_entry count unchanged so a later reader does
not add a both-legs assertion that cannot hold.

Refusal rule: every action that validates input gets one refusal case proving
the refusal happens, the message names the real problem, and every
module-owned table the action could touch (plus gl_entry and audit_log) is
byte-identical afterwards. construction-daily-summary validates only --job-id
(an unknown job is leniency, documented with an ok-zeros assertion, not a
refusal); construction-executive-summary likewise validates only --company-id.

Existing tests read first (deepen, don't duplicate shallowly):
  test_pay_application_billing_behaviour.py (get-pay-application,
    billing-summary, batch-add-cost-codes -- already behavioural; the tests
    here add distinct angles: line-level/aggregate re-reads with ledger pins),
  test_safety_controls.py::TestReports::test_executive_summary (shape-only:
    asserts three keys exist -- deepened here to exact aggregates),
  test_daily_changes.py (add-daily-report/add-pco/add-cco/add-incident setup
    patterns reused for seeding; none of the 12 actions themselves is
    behaviourally covered there),
  testing/integration/contract/test_constructclaw_contract.py (routability
    only for all 12 -- the "can be reached" half that this file completes).
"""
import json
from decimal import Decimal
from sqlite3 import OperationalError

import pytest

from construct_helpers import call_action, is_error, is_ok, ns, load_db_query


@pytest.fixture
def mod():
    return load_db_query()


_SNAPSHOT_TABLES = (
    "constructclaw_job",
    "constructclaw_cost_code",
    "constructclaw_cost_entry",
    "constructclaw_subcontract",
    "constructclaw_subcontract_line",
    "constructclaw_pay_application",
    "constructclaw_progress_bill",
    "constructclaw_daily_report",
    "constructclaw_daily_labor",
    "constructclaw_daily_material",
    "constructclaw_pco",
    "constructclaw_cco",
    "constructclaw_incident",
    "gl_entry",
    "audit_log",
)


def _snapshot(conn):
    """Byte-level dump of every table these actions could plausibly touch."""
    snap = {}
    for table in _SNAPSHOT_TABLES:
        snap[table] = [tuple(r) for r in conn.execute(
            "SELECT * FROM %s ORDER BY id" % table).fetchall()]
    return snap


def _gl_count(conn):
    return conn.execute("SELECT COUNT(*) FROM gl_entry").fetchone()[0]


# ── seed helpers (through the owning module's own actions) ─────────────────

def _add_job(conn, env, mod, name="M438 Depth Job", contract_amount="200000.00"):
    r = call_action(mod.ACTIONS["construction-add-job"], conn, ns(
        company_id=env["company_id"], name=name,
        job_type=None, contract_type=None, contract_amount=contract_amount,
        client_name=None, client_id=env["customer_id"], description=None,
        project_manager=None, superintendent=None,
        start_date="2026-01-05", end_date="2026-12-18", address=None,
        city=None, state=None, zip_code=None, notes=None))
    assert is_ok(r), r
    return r["job_id"]


def _add_sub(conn, env, mod, job_id, amount="100000.00", retention_pct="10"):
    r = call_action(mod.ACTIONS["construction-add-subcontract"], conn, ns(
        company_id=env["company_id"], job_id=job_id,
        subcontractor_name="M438 Mechanical", trade="hvac", scope_of_work=None,
        original_amount=amount, retention_pct=retention_pct,
        insurance_expiry=None, license_number=None,
        start_date="2026-01-12", end_date="2026-11-30", notes=None))
    assert is_ok(r), r
    return r["subcontract_id"]


def _add_report(conn, env, mod, job_id, report_date="2026-03-10"):
    r = call_action(mod.ACTIONS["construction-add-daily-report"], conn, ns(
        company_id=env["company_id"], job_id=job_id,
        report_date=report_date, superintendent="M438 Super",
        weather="Sunny", temperature_high="75", temperature_low="55",
        work_description="M438 foundation pour",
        delays=None, visitors=None, notes=None))
    assert is_ok(r), r
    return r["daily_report_id"]


def _add_pco(conn, env, mod, job_id, title="M438 Rock",
             cost_impact="25000.00", time_impact_days="5"):
    r = call_action(mod.ACTIONS["construction-add-pco"], conn, ns(
        company_id=env["company_id"], job_id=job_id,
        title=title, description="M438 rock removal",
        reason="site_condition", cost_impact=cost_impact,
        time_impact_days=time_impact_days, requested_by="M438 PM",
        notes=None))
    assert is_ok(r), r
    return r["pco_id"]


def _add_cco(conn, env, mod, job_id, pco_id, title="M438 CCO",
             cost_change="30000.00", time_change_days="3"):
    r = call_action(mod.ACTIONS["construction-add-cco"], conn, ns(
        company_id=env["company_id"], job_id=job_id, pco_id=pco_id,
        title=title, description="M438 owner-directed change",
        cost_change=cost_change, time_change_days=time_change_days,
        notes=None))
    assert is_ok(r), r
    return r["cco_id"]


def _add_incident(conn, env, mod, job_id):
    r = call_action(mod.ACTIONS["construction-add-incident"], conn, ns(
        company_id=env["company_id"], job_id=job_id,
        description="M438 worker tripped on debris",
        incident_type="first_aid", severity="minor",
        location="M438 Building A", injured_party="M438 Doe",
        witnesses=None, root_cause=None, corrective_action=None,
        osha_recordable=None, days_lost=None,
        incident_date="2026-03-10", incident_time="10:30", notes=None))
    assert is_ok(r), r
    return r["incident_id"]


def _add_pay_app(conn, env, mod, sub_id, work_completed,
                 materials_stored="0",
                 period_from="2026-03-01", period_to="2026-03-31"):
    r = call_action(mod.ACTIONS["construction-add-pay-application"], conn, ns(
        company_id=env["company_id"], subcontract_id=sub_id,
        work_completed=work_completed, materials_stored=materials_stored,
        period_from=period_from, period_to=period_to, notes=None))
    assert is_ok(r), r
    return r["pay_application_id"]


def _add_bill(conn, env, mod, job_id, completed, retention,
              period_from="2026-03-01", period_to="2026-03-31"):
    r = call_action(mod.ACTIONS["construction-add-progress-bill"], conn, ns(
        company_id=env["company_id"], job_id=job_id, sov_id=None,
        total_completed=completed, total_retention=retention,
        period_from=period_from, period_to=period_to, notes=None))
    assert is_ok(r), r
    return r["progress_bill_id"]


# ── construction-add-subcontract-line: STORED ROW ───────────────────────────

class TestAddSubcontractLineDepth:
    def test_line_writes_exact_row_with_derived_amount(self, conn, env, mod):
        # This action does NOT reach the ledger and writes no audit row: it
        # appends one constructclaw_subcontract_line row. Both the audit_log
        # and gl_entry counts are pinned unchanged.
        job_id = _add_job(conn, env, mod)
        sub_id = _add_sub(conn, env, mod, job_id)
        gl_before = _gl_count(conn)
        audit_before = len(_snapshot(conn)["audit_log"])

        r = call_action(mod.ACTIONS["construction-add-subcontract-line"], conn, ns(
            company_id=env["company_id"], subcontract_id=sub_id,
            description="M438 ductwork", quantity="10", unit="lot",
            unit_cost="1500.00", amount=None))
        assert is_ok(r), r
        # 10 x 1500.00 derives 15000.00 (half-up to the cent).
        assert r["line_number"] == 1
        assert r["amount"] == "15000.00"

        row = conn.execute(
            "SELECT subcontract_id, line_number, description, quantity, "
            "unit, unit_cost, amount, company_id "
            "FROM constructclaw_subcontract_line WHERE id = ?",
            (r["line_id"],)).fetchone()
        assert row is not None, "the added line must exist"
        assert tuple(row) == (sub_id, 1, "M438 ductwork", "10", "lot",
                              "1500.00", "15000.00", env["company_id"])

        # An explicit amount wins over quantity x unit_cost (2 x 100.00
        # would derive 200.00; the caller-supplied 250.00 is stored).
        r2 = call_action(mod.ACTIONS["construction-add-subcontract-line"], conn, ns(
            company_id=env["company_id"], subcontract_id=sub_id,
            description="M438 explicit", quantity="2", unit="ea",
            unit_cost="100.00", amount="250.00"))
        assert is_ok(r2), r2
        assert r2["line_number"] == 2
        assert r2["amount"] == "250.00"
        stored = [tuple(x) for x in conn.execute(
            "SELECT line_number, amount FROM constructclaw_subcontract_line "
            "WHERE subcontract_id = ? ORDER BY line_number",
            (sub_id,)).fetchall()]
        assert stored == [(1, "15000.00"), (2, "250.00")]

        assert _gl_count(conn) == gl_before
        assert len(_snapshot(conn)["audit_log"]) == audit_before

    def test_line_refusals_are_truthful_and_write_nothing(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        sub_id = _add_sub(conn, env, mod, job_id)
        add = mod.ACTIONS["construction-add-subcontract-line"]
        before = _snapshot(conn)

        r = call_action(add, conn, ns(
            company_id=env["company_id"], subcontract_id=sub_id,
            description=None, quantity="1", unit="ea",
            unit_cost="1.00", amount=None))
        assert is_error(r)
        assert r["message"] == "--description is required"

        r = call_action(add, conn, ns(
            company_id=env["company_id"], subcontract_id="no-such-sub",
            description="M438 ghost", quantity="1", unit="ea",
            unit_cost="1.00", amount=None))
        assert is_error(r)
        assert r["message"] == "Subcontract no-such-sub not found"

        r = call_action(add, conn, ns(
            company_id=None, subcontract_id=sub_id,
            description="M438 ghost", quantity="1", unit="ea",
            unit_cost="1.00", amount=None))
        assert is_error(r)
        assert r["message"] == "--company-id is required"

        assert _snapshot(conn) == before, "a refused line must half-write nothing"


# ── construction-batch-add-cost-codes: STORED ROWS ──────────────────────────

class TestBatchAddCostCodesDepth:
    def test_batch_writes_exact_rows_and_single_audit(self, conn, env, mod):
        # This action does NOT reach the ledger: it writes cost_code rows
        # plus exactly one audit row. gl_entry is pinned unchanged.
        job_id = _add_job(conn, env, mod)
        gl_before = _gl_count(conn)

        r = call_action(mod.ACTIONS["construction-batch-add-cost-codes"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            codes_json=json.dumps([
                {"code": "03-300", "description": "M438 concrete",
                 "category": "subcontract", "budget_amount": "48250.75"},
                {"code": "01-100", "description": "M438 supervision",
                 "budget_amount": "12000.00", "budget_hours": "320"},
            ])))
        assert is_ok(r), r
        assert r["created_count"] == 2

        stored = [tuple(x) for x in conn.execute(
            "SELECT code, description, category, budget_amount, "
            "budget_hours, is_active, company_id "
            "FROM constructclaw_cost_code WHERE job_id = ? ORDER BY code",
            (job_id,)).fetchall()]
        assert stored == [
            ("01-100", "M438 supervision", "labor", "12000.00", "320", 1,
             env["company_id"]),
            ("03-300", "M438 concrete", "subcontract", "48250.75", "0", 1,
             env["company_id"]),
        ]
        audits = [tuple(x) for x in conn.execute(
            "SELECT entity_type, new_values FROM audit_log "
            "WHERE action = ? AND entity_id = ?",
            ("construction-batch-add-cost-codes", job_id)).fetchall()]
        assert len(audits) == 1
        assert audits[0][0] == "constructclaw_cost_code"
        assert json.loads(audits[0][1]) == {"count": 2}

        assert _gl_count(conn) == gl_before

    def test_batch_refusal_midway_writes_nothing(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        before = _snapshot(conn)

        r = call_action(mod.ACTIONS["construction-batch-add-cost-codes"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            codes_json=json.dumps([
                {"code": "01-100", "description": "M438 ok",
                 "budget_amount": "500.00"},
                {"code": "02-200", "description": "M438 bogus",
                 "category": "bogus"},
            ])))
        assert is_error(r)
        assert r["message"] == "Invalid category 'bogus' for cost code 02-200"
        assert _snapshot(conn) == before, "a refused batch must roll back"


# ── construction-billing-summary: STORED-ROW READ ───────────────────────────

class TestBillingSummaryDepth:
    def test_summary_totals_match_stored_bills_exactly(self, conn, env, mod):
        # Read-only: aggregates the stored progress-bill rows. Rejected bills
        # are excluded; retention reported is the latest bill's. gl_entry is
        # pinned unchanged and the tables byte-identical after the call.
        job_id = _add_job(conn, env, mod, contract_amount="100000.00")
        _add_bill(conn, env, mod, job_id, "50000.00", "5000.00",
                  "2026-03-01", "2026-03-31")
        _add_bill(conn, env, mod, job_id, "80000.00", "8000.00",
                  "2026-04-01", "2026-04-30")
        # No action moves a progress bill to rejected; seed the status, as
        # the pre-existing behavioural suite does for paid/rejected.
        rejected = _add_bill(conn, env, mod, job_id, "99999.00", "9999.00",
                             "2026-05-01", "2026-05-31")
        conn.execute("UPDATE constructclaw_progress_bill SET bill_status = ? "
                     "WHERE id = ?", ("rejected", rejected))
        conn.commit()
        before = _snapshot(conn)
        gl_before = _gl_count(conn)

        r = call_action(mod.ACTIONS["construction-billing-summary"], conn, ns(
            job_id=job_id))
        assert is_ok(r), r
        # Bill 1 due 45000.00; bill 2 nets previous bills: 80000 - 8000 - 45000
        # = 27000.00. Rejected bill excluded: billed 72000.00, retention is
        # the latest surviving bill's 8000.00, remaining 20000.00.
        assert (r["contract_amount"], r["total_billed"], r["total_retention"],
                r["total_paid"], r["remaining_to_bill"],
                r["bill_count"]) == (
            "100000.00", "72000.00", "8000.00", "0.00", "20000.00", 2)
        assert [b["bill_number"] for b in r["bill_history"]] == [1, 2]
        assert r["bill_history"][1]["current_due"] == "27000.00"
        # Cross-check against the stored rows, not just the envelope.
        dues = [x[0] for x in conn.execute(
            "SELECT current_due FROM constructclaw_progress_bill "
            "WHERE job_id = ? AND bill_status != 'rejected' "
            "ORDER BY bill_number", (job_id,)).fetchall()]
        assert dues == ["45000.00", "27000.00"]
        assert str(sum(Decimal(d) for d in dues)) == "72000.00"

        assert _snapshot(conn) == before, "a summary must write nothing"
        assert _gl_count(conn) == gl_before

    def test_summary_refusals_are_truthful_and_write_nothing(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        before = _snapshot(conn)

        r = call_action(mod.ACTIONS["construction-billing-summary"], conn, ns(
            job_id="no-such-job"))
        assert is_error(r)
        assert r["message"] == "Job no-such-job not found"

        r = call_action(mod.ACTIONS["construction-billing-summary"], conn, ns(
            job_id=None))
        assert is_error(r)
        assert r["message"] == "--job-id is required"

        assert job_id is not None
        assert _snapshot(conn) == before


# ── construction-create-material-requisition: BROKEN ────────────────────────

class TestCreateMaterialRequisitionDepth:
    # BROKEN -- documents the real behaviour; production deliberately
    # unchanged. The handler INSERTs columns (job_id, unit_cost, notes,
    # status) that constructclaw_daily_material does not have, so every
    # success-path call raises OperationalError before writing anything.
    # Expected: a requisition row with status 'requisition'. Actual: no row,
    # no audit row, database byte-identical.
    def test_success_path_raises_and_writes_nothing(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        before = _snapshot(conn)

        with pytest.raises(OperationalError, match="no column named job_id"):
            call_action(
                mod.ACTIONS["construction-create-material-requisition"], conn, ns(
                    company_id=env["company_id"], job_id=job_id,
                    material_name="M438 rebar", quantity="200", unit="ea",
                    unit_cost="12.50", supplier="M438 Steel", notes="urgent"))

        after = _snapshot(conn)
        assert after == before, "the failed INSERT must leave no trace"
        assert after["constructclaw_daily_material"] == []
        assert conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE action = ?",
            ("construction-create-material-requisition",)).fetchone()[0] == 0
        assert _gl_count(conn) == 0

    def test_requisition_refusals_happen_before_the_broken_write(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        create = mod.ACTIONS["construction-create-material-requisition"]
        before = _snapshot(conn)

        r = call_action(create, conn, ns(
            company_id=env["company_id"], job_id=job_id,
            material_name=None, quantity="200"))
        assert is_error(r)
        assert r["message"] == "--material-name is required"

        r = call_action(create, conn, ns(
            company_id=env["company_id"], job_id=job_id,
            material_name="M438 rebar", quantity=None))
        assert is_error(r)
        assert r["message"] == "--quantity is required"

        r = call_action(create, conn, ns(
            company_id=env["company_id"], job_id="no-such-job",
            material_name="M438 rebar", quantity="200"))
        assert is_error(r)
        assert r["message"] == "Job no-such-job not found"

        assert _snapshot(conn) == before


# ── construction-add-drawing: BROKEN ────────────────────────────────────────

class TestAddDrawingDepth:
    # BROKEN -- documents the real behaviour; production deliberately
    # unchanged. Same root cause as the requisition action: the handler
    # INSERTs columns (job_id, unit_cost, notes, status) that
    # constructclaw_daily_material does not have, so every success-path call
    # raises OperationalError before writing anything. Expected: a drawing
    # row with status 'drawing'. Actual: no row, no audit, DB byte-identical.
    def test_success_path_raises_and_writes_nothing(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        before = _snapshot(conn)

        with pytest.raises(OperationalError, match="no column named job_id"):
            call_action(mod.ACTIONS["construction-add-drawing"], conn, ns(
                company_id=env["company_id"], job_id=job_id,
                name="M438 A-101", spec_section="03 30 00",
                discipline="Structural", sheet_number="A-101",
                description="M438 foundation plan"))

        after = _snapshot(conn)
        assert after == before, "the failed INSERT must leave no trace"
        assert after["constructclaw_daily_material"] == []
        assert conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE action = ?",
            ("construction-add-drawing",)).fetchone()[0] == 0
        assert _gl_count(conn) == 0

    def test_drawing_refusals_happen_before_the_broken_write(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        add = mod.ACTIONS["construction-add-drawing"]
        before = _snapshot(conn)

        r = call_action(add, conn, ns(
            company_id=env["company_id"], job_id=job_id, name=None))
        assert is_error(r)
        assert r["message"] == "--name is required"

        r = call_action(add, conn, ns(
            company_id=None, job_id=job_id, name="M438 A-101"))
        assert is_error(r)
        assert r["message"] == "--company-id is required"

        r = call_action(add, conn, ns(
            company_id=env["company_id"], job_id=None, name="M438 A-101"))
        assert is_error(r)
        assert r["message"] == "--job-id is required"

        assert _snapshot(conn) == before


# ── construction-daily-summary: STORED-ROW READ ─────────────────────────────

class TestDailySummaryDepth:
    def test_summary_aggregates_match_stored_rows_exactly(self, conn, env, mod):
        # Read-only: aggregates stored daily reports, labor and material
        # rows. The second report is empty, proving empty reports count but
        # contribute nothing. Tables byte-identical after the call.
        job_id = _add_job(conn, env, mod)
        dr_id = _add_report(conn, env, mod, job_id, "2026-03-10")
        call_action(mod.ACTIONS["construction-add-daily-labor"], conn, ns(
            company_id=env["company_id"], daily_report_id=dr_id,
            trade="carpentry", headcount="8", hours="64",
            description="M438 framing"))
        call_action(mod.ACTIONS["construction-add-daily-material"], conn, ns(
            company_id=env["company_id"], daily_report_id=dr_id,
            material_name="M438 ready-mix", quantity="15", unit="cy",
            supplier="M438 Concrete", delivery_ticket="M438-DT-1"))
        _add_report(conn, env, mod, job_id, "2026-03-11")
        before = _snapshot(conn)

        r = call_action(mod.ACTIONS["construction-daily-summary"], conn, ns(
            job_id=job_id))
        assert is_ok(r), r
        assert (r["total_reports"], r["total_labor_hours"],
                r["total_headcount"],
                r["total_material_deliveries"]) == (2, "64.00", 8, 1)
        # Cross-check against the stored rows, not just the envelope.
        assert conn.execute(
            "SELECT COUNT(*) FROM constructclaw_daily_report "
            "WHERE job_id = ?", (job_id,)).fetchone()[0] == 2
        assert conn.execute(
            "SELECT hours, headcount FROM constructclaw_daily_labor "
            "WHERE daily_report_id = ?", (dr_id,)).fetchone()[0:2] == (
            "64", 8)

        assert _snapshot(conn) == before, "a summary must write nothing"

    def test_summary_refusal_is_truthful_and_writes_nothing(self, conn, env, mod):
        _add_job(conn, env, mod)
        before = _snapshot(conn)

        r = call_action(mod.ACTIONS["construction-daily-summary"], conn, ns(
            job_id=None))
        assert is_error(r)
        assert r["message"] == "--job-id is required"

        # Leniency worth pinning: an unknown job is NOT a refusal -- it
        # returns an ok zero summary. A later reader must not "fix" this
        # into an error without a production change.
        r = call_action(mod.ACTIONS["construction-daily-summary"], conn, ns(
            job_id="no-such-job"))
        assert is_ok(r), r
        assert (r["total_reports"], r["total_labor_hours"],
                r["total_headcount"],
                r["total_material_deliveries"]) == (0, "0.00", 0, 0)

        assert _snapshot(conn) == before


# ── construction-executive-summary: STORED-ROW READ ─────────────────────────

class TestExecutiveSummaryDepth:
    def test_summary_figures_match_stored_rows_exactly(self, conn, env, mod):
        # Read-only: aggregates jobs, cost entries, progress bills, PCOs and
        # incidents. This deepens TestReports::test_executive_summary, which
        # asserts only that three keys exist. Tables byte-identical after.
        job_id = _add_job(conn, env, mod, contract_amount="200000.00")
        cc = call_action(mod.ACTIONS["construction-add-cost-code"], conn, ns(
            company_id=env["company_id"], job_id=job_id, code="01-100",
            description="M438 labor", category="labor",
            budget_amount="50000.00", budget_hours="100"))
        assert is_ok(cc), cc
        ce = call_action(mod.ACTIONS["construction-add-cost-entry"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            cost_code_id=cc["cost_code_id"], description="M438 week 1",
            entry_date="2026-03-07", quantity="40", unit_cost="125.00",
            amount=None, vendor=None, invoice_number=None, notes=None))
        assert is_ok(ce), ce
        assert ce["amount"] == "5000.00"
        _add_bill(conn, env, mod, job_id, "50000.00", "5000.00")
        _add_pco(conn, env, mod, job_id)
        _add_incident(conn, env, mod, job_id)
        before = _snapshot(conn)

        r = call_action(mod.ACTIONS["construction-executive-summary"], conn, ns(
            company_id=env["company_id"]))
        assert is_ok(r), r
        assert r["jobs_by_status"] == {"planning": 1}
        assert r["total_contract_value"] == "200000.00"
        assert r["total_cost_to_date"] == "5000.00"
        # (200000 - 5000) / 200000 * 100 = 97.50, half-up to the cent.
        assert r["overall_margin_pct"] == "97.50"
        assert r["total_billed"] == "45000.00"
        assert r["open_rfis"] == 0
        assert r["pending_change_orders"] == 1
        assert r["open_safety_incidents"] == 1
        # Cross-check against the stored rows, not just the envelope.
        assert conn.execute(
            "SELECT contract_amount FROM constructclaw_job WHERE id = ?",
            (job_id,)).fetchone()[0] == "200000.00"
        assert conn.execute(
            "SELECT amount FROM constructclaw_cost_entry WHERE id = ?",
            (ce["cost_entry_id"],)).fetchone()[0] == "5000.00"

        assert _snapshot(conn) == before, "a summary must write nothing"

    def test_summary_refusal_is_truthful_and_writes_nothing(self, conn, env, mod):
        _add_job(conn, env, mod)
        before = _snapshot(conn)

        r = call_action(mod.ACTIONS["construction-executive-summary"], conn, ns(
            company_id=None))
        assert is_error(r)
        assert r["message"] == "--company-id is required"

        assert _snapshot(conn) == before


# ── construction-get-cco: STORED-ROW READ ───────────────────────────────────

class TestGetCcoDepth:
    def test_get_returns_the_stored_cco_figures(self, conn, env, mod):
        # Read-only: the response must equal the stored row. Tables
        # byte-identical after the call.
        job_id = _add_job(conn, env, mod)
        pco_id = _add_pco(conn, env, mod, job_id)
        cco_id = _add_cco(conn, env, mod, job_id, pco_id)
        before = _snapshot(conn)

        r = call_action(mod.ACTIONS["construction-get-cco"], conn, ns(
            cco_id=cco_id))
        assert is_ok(r), r
        row = conn.execute(
            "SELECT id, job_id, pco_id, title, description, cost_change, "
            "time_change_days, cco_status, company_id "
            "FROM constructclaw_cco WHERE id = ?", (cco_id,)).fetchone()
        assert tuple(row) == (cco_id, job_id, pco_id, "M438 CCO",
                              "M438 owner-directed change", "30000.00", 3,
                              "draft", env["company_id"])
        assert (r["title"], r["cost_change"], r["time_change_days"],
                r["cco_status"], r["pco_id"]) == (
            "M438 CCO", "30000.00", 3, "draft", pco_id)
        assert r["id"] == cco_id

        assert _snapshot(conn) == before, "a get must write nothing"

    def test_get_cco_refusals_are_truthful_and_write_nothing(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        _add_cco(conn, env, mod, job_id, _add_pco(conn, env, mod, job_id))
        before = _snapshot(conn)

        r = call_action(mod.ACTIONS["construction-get-cco"], conn, ns(
            cco_id="no-such-cco"))
        assert is_error(r)
        assert r["message"] == "CCO no-such-cco not found"

        r = call_action(mod.ACTIONS["construction-get-cco"], conn, ns(
            cco_id=None))
        assert is_error(r)
        assert r["message"] == "--cco-id is required"

        assert _snapshot(conn) == before


# ── construction-get-daily-report: STORED-ROW READ ──────────────────────────

class TestGetDailyReportDepth:
    def test_get_returns_stored_header_plus_entries(self, conn, env, mod):
        # Read-only: header must equal the stored report row; the attached
        # labor/material entries must equal their stored rows. Tables
        # byte-identical after the call.
        job_id = _add_job(conn, env, mod)
        dr_id = _add_report(conn, env, mod, job_id, "2026-03-10")
        call_action(mod.ACTIONS["construction-add-daily-labor"], conn, ns(
            company_id=env["company_id"], daily_report_id=dr_id,
            trade="carpentry", headcount="8", hours="64",
            description="M438 framing"))
        call_action(mod.ACTIONS["construction-add-daily-material"], conn, ns(
            company_id=env["company_id"], daily_report_id=dr_id,
            material_name="M438 ready-mix", quantity="15", unit="cy",
            supplier="M438 Concrete", delivery_ticket="M438-DT-1"))
        before = _snapshot(conn)

        r = call_action(mod.ACTIONS["construction-get-daily-report"], conn, ns(
            daily_report_id=dr_id))
        assert is_ok(r), r
        row = conn.execute(
            "SELECT job_id, report_date, superintendent, weather, "
            "work_description, report_status "
            "FROM constructclaw_daily_report WHERE id = ?",
            (dr_id,)).fetchone()
        assert tuple(row) == (job_id, "2026-03-10", "M438 Super", "Sunny",
                              "M438 foundation pour", "draft")
        assert (r["job_id"], r["report_date"], r["superintendent"],
                r["report_status"]) == (
            job_id, "2026-03-10", "M438 Super", "draft")
        assert len(r["labor_entries"]) == 1
        assert (r["labor_entries"][0]["trade"],
                r["labor_entries"][0]["hours"],
                r["labor_entries"][0]["headcount"]) == (
            "carpentry", "64", 8)
        assert len(r["material_entries"]) == 1
        assert (r["material_entries"][0]["material_name"],
                r["material_entries"][0]["quantity"],
                r["material_entries"][0]["supplier"]) == (
            "M438 ready-mix", "15", "M438 Concrete")

        assert _snapshot(conn) == before, "a get must write nothing"

    def test_get_daily_report_refusals_write_nothing(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        _add_report(conn, env, mod, job_id)
        before = _snapshot(conn)

        r = call_action(mod.ACTIONS["construction-get-daily-report"], conn, ns(
            daily_report_id="no-such-report"))
        assert is_error(r)
        assert r["message"] == "Daily report no-such-report not found"

        r = call_action(mod.ACTIONS["construction-get-daily-report"], conn, ns(
            daily_report_id=None))
        assert is_error(r)
        assert r["message"] == "--daily-report-id is required"

        assert _snapshot(conn) == before


# ── construction-get-incident: STORED-ROW READ ──────────────────────────────

class TestGetIncidentDepth:
    def test_get_returns_the_stored_incident_figures(self, conn, env, mod):
        # Read-only: the response must equal the stored row. Tables
        # byte-identical after the call.
        job_id = _add_job(conn, env, mod)
        inc_id = _add_incident(conn, env, mod, job_id)
        before = _snapshot(conn)

        r = call_action(mod.ACTIONS["construction-get-incident"], conn, ns(
            incident_id=inc_id))
        assert is_ok(r), r
        row = conn.execute(
            "SELECT job_id, incident_date, incident_type, severity, "
            "location, description, osha_recordable, days_lost, "
            "incident_status, company_id "
            "FROM constructclaw_incident WHERE id = ?", (inc_id,)).fetchone()
        assert tuple(row) == (job_id, "2026-03-10", "first_aid", "minor",
                              "M438 Building A",
                              "M438 worker tripped on debris", 0, 0, "open",
                              env["company_id"])
        assert (r["incident_type"], r["severity"], r["osha_recordable"],
                r["incident_status"]) == ("first_aid", "minor", 0, "open")
        assert r["id"] == inc_id

        assert _snapshot(conn) == before, "a get must write nothing"

    def test_get_incident_refusals_are_truthful_and_write_nothing(
            self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        _add_incident(conn, env, mod, job_id)
        before = _snapshot(conn)

        r = call_action(mod.ACTIONS["construction-get-incident"], conn, ns(
            incident_id="no-such-incident"))
        assert is_error(r)
        assert r["message"] == "Incident no-such-incident not found"

        r = call_action(mod.ACTIONS["construction-get-incident"], conn, ns(
            incident_id=None))
        assert is_error(r)
        assert r["message"] == "--incident-id is required"

        assert _snapshot(conn) == before


# ── construction-get-pay-application: STORED-ROW READ ───────────────────────

class TestGetPayApplicationDepth:
    def test_get_returns_the_stored_pay_figures(self, conn, env, mod):
        # Read-only: the response must equal the stored row, money legs
        # exact. Tables byte-identical after the call.
        job_id = _add_job(conn, env, mod)
        sub_id = _add_sub(conn, env, mod, job_id)
        pa_id = _add_pay_app(conn, env, mod, sub_id, "20000.00", "1500.00")
        before = _snapshot(conn)

        r = call_action(mod.ACTIONS["construction-get-pay-application"], conn, ns(
            pay_application_id=pa_id))
        assert is_ok(r), r
        row = conn.execute(
            "SELECT subcontract_id, application_number, period_from, "
            "period_to, work_completed, materials_stored, total_earned, "
            "retention_held, previous_payments, current_payment_due, "
            "pay_app_status, company_id "
            "FROM constructclaw_pay_application WHERE id = ?",
            (pa_id,)).fetchone()
        assert tuple(row) == (sub_id, 1, "2026-03-01", "2026-03-31",
                              "20000.00", "1500.00", "21500.00", "2150.00",
                              "0.00", "19350.00", "draft", env["company_id"])
        assert (r["total_earned"], r["retention_held"],
                r["previous_payments"], r["current_payment_due"]) == (
            "21500.00", "2150.00", "0.00", "19350.00")
        assert r["id"] == pa_id

        assert _snapshot(conn) == before, "a get must write nothing"

    def test_get_pay_application_refusals_write_nothing(
            self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        sub_id = _add_sub(conn, env, mod, job_id)
        _add_pay_app(conn, env, mod, sub_id, "20000.00", "1500.00")
        before = _snapshot(conn)

        r = call_action(mod.ACTIONS["construction-get-pay-application"], conn, ns(
            pay_application_id="no-such-app"))
        assert is_error(r)
        assert r["message"] == "Pay application no-such-app not found"

        r = call_action(mod.ACTIONS["construction-get-pay-application"], conn, ns(
            pay_application_id=None))
        assert is_error(r)
        assert r["message"] == "--pay-application-id is required"

        assert _snapshot(conn) == before


# ── construction-get-pco: STORED-ROW READ ───────────────────────────────────

class TestGetPcoDepth:
    def test_get_returns_the_stored_pco_figures(self, conn, env, mod):
        # Read-only: the response must equal the stored row, money exact.
        # Tables byte-identical after the call.
        job_id = _add_job(conn, env, mod)
        pco_id = _add_pco(conn, env, mod, job_id)
        before = _snapshot(conn)

        r = call_action(mod.ACTIONS["construction-get-pco"], conn, ns(
            pco_id=pco_id))
        assert is_ok(r), r
        row = conn.execute(
            "SELECT job_id, title, description, reason, cost_impact, "
            "time_impact_days, requested_by, pco_status, company_id "
            "FROM constructclaw_pco WHERE id = ?", (pco_id,)).fetchone()
        assert tuple(row) == (job_id, "M438 Rock", "M438 rock removal",
                              "site_condition", "25000.00", 5, "M438 PM",
                              "identified", env["company_id"])
        assert (r["title"], r["cost_impact"], r["time_impact_days"],
                r["pco_status"]) == ("M438 Rock", "25000.00", 5, "identified")
        assert r["id"] == pco_id

        assert _snapshot(conn) == before, "a get must write nothing"

    def test_get_pco_refusals_are_truthful_and_write_nothing(
            self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        _add_pco(conn, env, mod, job_id)
        before = _snapshot(conn)

        r = call_action(mod.ACTIONS["construction-get-pco"], conn, ns(
            pco_id="no-such-pco"))
        assert is_error(r)
        assert r["message"] == "PCO no-such-pco not found"

        r = call_action(mod.ACTIONS["construction-get-pco"], conn, ns(
            pco_id=None))
        assert is_error(r)
        assert r["message"] == "--pco-id is required"

        assert _snapshot(conn) == before
