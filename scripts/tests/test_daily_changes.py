"""L1 tests for ConstructClaw -- Daily Reports, Change Orders, RFIs & Submittals.

Covers: daily reports, daily labor, daily materials, daily summary,
        PCOs, CCOs, approve-pco, approve-cco, change order impact,
        RFIs, respond/close RFI, submittals, review submittal.
"""
import pytest
from construct_helpers import call_action, ns, is_ok, is_error, load_db_query, _uuid


@pytest.fixture
def mod():
    return load_db_query()


def _add_job(conn, env, mod, name="Daily/Change Job"):
    r = call_action(mod.ACTIONS["construction-add-job"], conn, ns(
        company_id=env["company_id"], name=name,
        job_type=None, contract_type=None, contract_amount="500000",
        client_name=None, client_id=None, description=None,
        project_manager=None, superintendent=None,
        start_date=None, end_date=None, address=None,
        city=None, state=None, zip_code=None, notes=None,
    ))
    assert is_ok(r)
    return r["job_id"]


# ═══════════════════════════════════════════════════════════════════════════
# DAILY REPORTS
# ═══════════════════════════════════════════════════════════════════════════

class TestDailyReports:
    def test_add_daily_report(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-daily-report"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            report_date="2026-03-10", superintendent="John Smith",
            weather="Sunny", temperature_high="75",
            temperature_low="55", work_description="Foundation pour",
            delays=None, visitors=None, notes=None,
        ))
        assert is_ok(r)
        assert r["naming_series"].startswith("CCDR-")
        assert r["report_status"] == "draft"

    def test_update_daily_report(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-daily-report"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            report_date=None, superintendent=None,
            weather=None, temperature_high=None,
            temperature_low=None, work_description=None,
            delays=None, visitors=None, notes=None,
        ))
        dr_id = r["daily_report_id"]

        r2 = call_action(mod.ACTIONS["construction-update-daily-report"], conn, ns(
            daily_report_id=dr_id, report_date=None,
            superintendent=None, weather="Rainy",
            temperature_high=None, temperature_low=None,
            work_description="Rain delay", delays="2 hours rain",
            visitors=None, notes=None,
        ))
        assert is_ok(r2)
        assert "weather" in r2["updated_fields"]
        assert "delays" in r2["updated_fields"]

    def test_submit_daily_report(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-daily-report"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            report_date=None, superintendent=None,
            weather=None, temperature_high=None,
            temperature_low=None, work_description=None,
            delays=None, visitors=None, notes=None,
        ))
        dr_id = r["daily_report_id"]

        r2 = call_action(mod.ACTIONS["construction-submit-daily-report"], conn, ns(
            daily_report_id=dr_id,
        ))
        assert is_ok(r2)
        assert r2["report_status"] == "submitted"

    def test_update_submitted_report_fails(self, conn, env, mod):
        """Cannot update a submitted daily report."""
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-daily-report"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            report_date=None, superintendent=None,
            weather=None, temperature_high=None,
            temperature_low=None, work_description=None,
            delays=None, visitors=None, notes=None,
        ))
        dr_id = r["daily_report_id"]
        call_action(mod.ACTIONS["construction-submit-daily-report"], conn, ns(
            daily_report_id=dr_id,
        ))
        r2 = call_action(mod.ACTIONS["construction-update-daily-report"], conn, ns(
            daily_report_id=dr_id, report_date=None,
            superintendent=None, weather="Snow",
            temperature_high=None, temperature_low=None,
            work_description=None, delays=None,
            visitors=None, notes=None,
        ))
        assert is_error(r2)


class TestDailyLabor:
    def test_add_daily_labor(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-daily-report"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            report_date=None, superintendent=None,
            weather=None, temperature_high=None,
            temperature_low=None, work_description=None,
            delays=None, visitors=None, notes=None,
        ))
        dr_id = r["daily_report_id"]

        r2 = call_action(mod.ACTIONS["construction-add-daily-labor"], conn, ns(
            company_id=env["company_id"], daily_report_id=dr_id,
            trade="carpentry", headcount="8", hours="64",
            description="Framing second floor",
        ))
        assert is_ok(r2)
        assert r2["trade"] == "carpentry"

    def test_list_daily_labor(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-daily-report"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            report_date=None, superintendent=None,
            weather=None, temperature_high=None,
            temperature_low=None, work_description=None,
            delays=None, visitors=None, notes=None,
        ))
        dr_id = r["daily_report_id"]
        call_action(mod.ACTIONS["construction-add-daily-labor"], conn, ns(
            company_id=env["company_id"], daily_report_id=dr_id,
            trade="electrical", headcount="4", hours="32",
            description=None,
        ))
        r2 = call_action(mod.ACTIONS["construction-list-daily-labor"], conn, ns(
            daily_report_id=dr_id,
        ))
        assert is_ok(r2)
        assert r2["total_count"] == 1


class TestDailyMaterial:
    def test_add_daily_material(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-daily-report"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            report_date=None, superintendent=None,
            weather=None, temperature_high=None,
            temperature_low=None, work_description=None,
            delays=None, visitors=None, notes=None,
        ))
        dr_id = r["daily_report_id"]

        r2 = call_action(mod.ACTIONS["construction-add-daily-material"], conn, ns(
            company_id=env["company_id"], daily_report_id=dr_id,
            material_name="Ready-mix concrete",
            quantity="15", unit="cy", supplier="ABC Concrete",
            delivery_ticket="DT-2026-001",
        ))
        assert is_ok(r2)
        assert r2["material_name"] == "Ready-mix concrete"


# ═══════════════════════════════════════════════════════════════════════════
# CHANGE ORDERS (PCOs + CCOs)
# ═══════════════════════════════════════════════════════════════════════════

class TestPCOs:
    def test_add_pco(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-pco"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            title="Unforeseen Rock", description="Rock removal required",
            reason="site_condition", cost_impact="25000",
            time_impact_days="5", requested_by="PM", notes=None,
        ))
        assert is_ok(r)
        assert r["naming_series"].startswith("CCPCO-")
        assert r["pco_status"] == "identified"

    def test_update_pco(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-pco"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            title="PCO Update Test", description=None,
            reason=None, cost_impact="10000",
            time_impact_days=None, requested_by=None, notes=None,
        ))
        pco_id = r["pco_id"]

        r2 = call_action(mod.ACTIONS["construction-update-pco"], conn, ns(
            pco_id=pco_id, title=None, description=None,
            reason=None, cost_impact="15000",
            time_impact_days=None, requested_by=None,
            notes=None, pco_status="pricing",
        ))
        assert is_ok(r2)
        assert "cost_impact" in r2["updated_fields"]
        assert "pco_status" in r2["updated_fields"]

    def test_approve_pco_creates_cco(self, conn, env, mod):
        """Approving a PCO should create a CCO."""
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-pco"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            title="Approve PCO Test", description="Extra work",
            reason="client_request", cost_impact="50000",
            time_impact_days="10", requested_by=None, notes=None,
        ))
        pco_id = r["pco_id"]

        r2 = call_action(mod.ACTIONS["construction-approve-pco"], conn, ns(
            pco_id=pco_id,
        ))
        assert is_ok(r2)
        assert r2["pco_status"] == "approved"
        assert r2["cco_id"]  # CCO was created
        assert r2["cost_change"] == "50000"

    def test_list_pcos(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        call_action(mod.ACTIONS["construction-add-pco"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            title="PCO 1", description=None,
            reason=None, cost_impact="10000",
            time_impact_days=None, requested_by=None, notes=None,
        ))
        r = call_action(mod.ACTIONS["construction-list-pcos"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            pco_status=None, search=None, limit=50, offset=0,
        ))
        assert is_ok(r)
        assert r["total_count"] == 1


class TestCCOs:
    def test_add_cco(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-cco"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            pco_id=None, title="Direct CCO",
            description="Owner-directed change",
            cost_change="75000", time_change_days="15",
            notes=None,
        ))
        assert is_ok(r)
        assert r["cco_status"] == "draft"
        assert r["cost_change"] == "75000"

    def test_approve_cco(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-cco"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            pco_id=None, title="Approvable CCO",
            description=None, cost_change="30000",
            time_change_days=None, notes=None,
        ))
        cco_id = r["cco_id"]

        r2 = call_action(mod.ACTIONS["construction-approve-cco"], conn, ns(
            cco_id=cco_id, approved_by="Owner Rep",
        ))
        assert is_ok(r2)
        assert r2["cco_status"] == "approved"

    def test_change_order_impact(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        # Add and approve a PCO -> CCO
        r = call_action(mod.ACTIONS["construction-add-pco"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            title="Impact PCO", description=None,
            reason=None, cost_impact="20000",
            time_impact_days="3", requested_by=None, notes=None,
        ))
        pco_id = r["pco_id"]
        approve_r = call_action(mod.ACTIONS["construction-approve-pco"], conn, ns(
            pco_id=pco_id,
        ))
        assert is_ok(approve_r)
        cco_id = approve_r["cco_id"]

        # Approve the CCO so it counts toward revised contract
        call_action(mod.ACTIONS["construction-approve-cco"], conn, ns(
            cco_id=cco_id, approved_by="Owner",
        ))

        r2 = call_action(mod.ACTIONS["construction-change-order-impact"], conn, ns(
            job_id=job_id,
        ))
        assert is_ok(r2)
        d = r2
        assert d["original_contract"] == "500000.00"
        assert len(d["pcos"]) == 1
        assert len(d["ccos"]) == 1
        # The approved CCO should affect revised contract
        assert d["revised_contract"] == "520000.00"


# ═══════════════════════════════════════════════════════════════════════════
# RFIs
# ═══════════════════════════════════════════════════════════════════════════

class TestRFIs:
    def test_add_rfi(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-rfi"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            subject="Foundation depth", question="Confirm footer depth per plan sheet S-101?",
            initiated_by="Superintendent", assigned_to="Architect",
            priority="high", date_required="2026-03-20",
            cost_impact=None, schedule_impact_days=None, notes=None,
        ))
        assert is_ok(r)
        assert r["naming_series"].startswith("CCRFI-")
        assert r["rfi_status"] == "open"
        assert r["priority"] == "high"

    def test_add_rfi_missing_question(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-rfi"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            subject="No question", question=None,
            initiated_by=None, assigned_to=None,
            priority=None, date_required=None,
            cost_impact=None, schedule_impact_days=None, notes=None,
        ))
        assert is_error(r)

    def test_respond_to_rfi(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-rfi"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            subject="Tile spec", question="Which tile for bathroom?",
            initiated_by=None, assigned_to=None,
            priority=None, date_required=None,
            cost_impact=None, schedule_impact_days=None, notes=None,
        ))
        rfi_id = r["rfi_id"]

        r2 = call_action(mod.ACTIONS["construction-respond-to-rfi"], conn, ns(
            rfi_id=rfi_id, response="Use 12x24 porcelain per spec section 09 30 00",
        ))
        assert is_ok(r2)
        assert r2["rfi_status"] == "responded"

    def test_close_rfi(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-rfi"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            subject="Close test", question="Can we close?",
            initiated_by=None, assigned_to=None,
            priority=None, date_required=None,
            cost_impact=None, schedule_impact_days=None, notes=None,
        ))
        rfi_id = r["rfi_id"]

        r2 = call_action(mod.ACTIONS["construction-close-rfi"], conn, ns(
            rfi_id=rfi_id,
        ))
        assert is_ok(r2)
        assert r2["rfi_status"] == "closed"

    def test_list_rfis(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        call_action(mod.ACTIONS["construction-add-rfi"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            subject="RFI 1", question="Question 1?",
            initiated_by=None, assigned_to=None,
            priority=None, date_required=None,
            cost_impact=None, schedule_impact_days=None, notes=None,
        ))
        r = call_action(mod.ACTIONS["construction-list-rfis"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            rfi_status=None, priority=None, search=None,
            limit=50, offset=0,
        ))
        assert is_ok(r)
        assert r["total_count"] == 1


# ═══════════════════════════════════════════════════════════════════════════
# SUBMITTALS
# ═══════════════════════════════════════════════════════════════════════════

class TestSubmittals:
    def test_add_submittal(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-submittal"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            title="Structural Steel Shop Drawings",
            spec_section="05 12 00",
            description="W-shape beam details",
            submitted_by="Steel Fab Co",
            submitted_to="Structural Engineer",
            date_required="2026-04-15", notes=None,
        ))
        assert is_ok(r)
        assert r["naming_series"].startswith("CCSUBM-")
        assert r["submittal_status"] == "pending"

    def test_review_submittal_approved(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-submittal"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            title="Review Test", spec_section=None,
            description=None, submitted_by=None, submitted_to=None,
            date_required=None, notes=None,
        ))
        sub_id = r["submittal_id"]

        r2 = call_action(mod.ACTIONS["construction-review-submittal"], conn, ns(
            submittal_id=sub_id, decision="approved",
            review_comments="Looks good", notes=None,
        ))
        assert is_ok(r2)
        assert r2["submittal_status"] == "approved"

    def test_review_submittal_revise_resubmit(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-submittal"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            title="Revise Test", spec_section=None,
            description=None, submitted_by=None, submitted_to=None,
            date_required=None, notes=None,
        ))
        sub_id = r["submittal_id"]

        r2 = call_action(mod.ACTIONS["construction-review-submittal"], conn, ns(
            submittal_id=sub_id, decision="revise_resubmit",
            review_comments="Need connection details", notes=None,
        ))
        assert is_ok(r2)
        assert r2["submittal_status"] == "revise_resubmit"

    def test_review_submittal_invalid_decision(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-submittal"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            title="Bad Decision", spec_section=None,
            description=None, submitted_by=None, submitted_to=None,
            date_required=None, notes=None,
        ))
        sub_id = r["submittal_id"]

        r2 = call_action(mod.ACTIONS["construction-review-submittal"], conn, ns(
            submittal_id=sub_id, decision="bogus",
            review_comments=None, notes=None,
        ))
        assert is_error(r2)
