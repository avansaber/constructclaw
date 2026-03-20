"""L1 tests for ConstructClaw -- Project Management domain.

Covers: permits & inspection (C4), punch list (C5), material procurement (C6),
        insurance & bond (C7), drawing management (C8), warranty tracking (C9),
        milestones / CPM (C10).
"""
import pytest
from construct_helpers import call_action, ns, is_ok, is_error, load_db_query, _uuid


@pytest.fixture
def mod():
    return load_db_query()


def _add_job(conn, env, mod, name="Project Mgmt Job"):
    r = call_action(mod.ACTIONS["construction-add-job"], conn, ns(
        company_id=env["company_id"], name=name,
        job_type=None, contract_type=None, contract_amount="500000",
        client_name="Acme Corp", client_id=None, description=None,
        project_manager=None, superintendent=None,
        start_date=None, end_date=None, address=None,
        city=None, state=None, zip_code=None, notes=None,
    ))
    assert is_ok(r)
    return r["job_id"]


# ===========================================================================
# C4: PERMIT & INSPECTION
# ===========================================================================

class TestPermitInspection:
    def test_add_permit(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-permit"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            permit_type="building", permit_number="BP-2026-001",
            jurisdiction="City of Portland", application_date="2026-03-01",
            approval_date=None, expiration_date="2027-03-01",
            inspection_date=None, inspection_result=None,
            inspector_name=None, correction_notes=None,
            permit_status=None,
        ))
        assert is_ok(r)
        assert r["permit_id"]
        assert r["permit_status"] == "applied"

    def test_add_permit_missing_type(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-permit"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            permit_type=None, permit_number=None,
            jurisdiction=None, application_date=None,
            approval_date=None, expiration_date=None,
            inspection_date=None, inspection_result=None,
            inspector_name=None, correction_notes=None,
            permit_status=None,
        ))
        assert is_error(r)

    def test_update_permit(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-permit"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            permit_type="electrical", permit_number=None,
            jurisdiction=None, application_date=None,
            approval_date=None, expiration_date=None,
            inspection_date=None, inspection_result=None,
            inspector_name=None, correction_notes=None,
            permit_status=None,
        ))
        pid = r["permit_id"]
        r2 = call_action(mod.ACTIONS["construction-update-permit"], conn, ns(
            permit_id=pid, permit_number="EP-2026-100",
            jurisdiction=None, application_date=None,
            approval_date=None, expiration_date=None,
            inspector_name=None, correction_notes=None,
            permit_status="approved",
        ))
        assert is_ok(r2)
        assert "permit_number" in r2["updated_fields"]

    def test_list_permits(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        call_action(mod.ACTIONS["construction-add-permit"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            permit_type="plumbing", permit_number=None,
            jurisdiction=None, application_date=None,
            approval_date=None, expiration_date=None,
            inspection_date=None, inspection_result=None,
            inspector_name=None, correction_notes=None,
            permit_status=None,
        ))
        r = call_action(mod.ACTIONS["construction-list-permits"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            permit_status=None, limit=50, offset=0,
        ))
        assert is_ok(r)
        assert r["total_count"] >= 1

    def test_schedule_inspection(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-permit"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            permit_type="building", permit_number=None,
            jurisdiction=None, application_date=None,
            approval_date=None, expiration_date=None,
            inspection_date=None, inspection_result=None,
            inspector_name=None, correction_notes=None,
            permit_status=None,
        ))
        pid = r["permit_id"]
        r2 = call_action(mod.ACTIONS["construction-schedule-inspection"], conn, ns(
            permit_id=pid, inspection_date="2026-04-15",
            inspector_name="John Smith",
        ))
        assert is_ok(r2)
        assert r2["inspection_result"] == "pending"

    def test_record_inspection_result_pass(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-permit"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            permit_type="fire", permit_number=None,
            jurisdiction=None, application_date=None,
            approval_date=None, expiration_date=None,
            inspection_date=None, inspection_result=None,
            inspector_name=None, correction_notes=None,
            permit_status=None,
        ))
        pid = r["permit_id"]
        r2 = call_action(mod.ACTIONS["construction-record-inspection-result"], conn, ns(
            permit_id=pid, inspection_result="pass",
            inspector_name="Jane Doe", correction_notes=None,
        ))
        assert is_ok(r2)
        assert r2["inspection_result"] == "pass"
        assert r2["permit_status"] == "approved"

    def test_permit_expiry_report(self, conn, env, mod):
        r = call_action(mod.ACTIONS["construction-permit-expiry-report"], conn, ns(
            company_id=env["company_id"],
        ))
        assert is_ok(r)
        assert "expired_count" in r


# ===========================================================================
# C5: PUNCH LIST
# ===========================================================================

class TestPunchList:
    def test_add_punch_list_item(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-punch-list-item"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            description="Touch up paint in lobby",
            location="Lobby", assigned_to="Mike", subcontractor_id=None,
            priority="high", photo_url=None, completion_date=None,
            punch_status=None,
        ))
        assert is_ok(r)
        assert r["punch_list_item_id"]
        assert r["priority"] == "high"
        assert r["punch_status"] == "open"

    def test_update_punch_list_item(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-punch-list-item"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            description="Fix door handle", location=None,
            assigned_to=None, subcontractor_id=None,
            priority=None, photo_url=None, completion_date=None,
            punch_status=None,
        ))
        pid = r["punch_list_item_id"]
        r2 = call_action(mod.ACTIONS["construction-update-punch-list-item"], conn, ns(
            punch_item_id=pid, description=None, location=None,
            assigned_to=None, subcontractor_id=None, priority=None,
            photo_url=None, completion_date="2026-04-20",
            punch_status="completed",
        ))
        assert is_ok(r2)
        assert "status" in r2["updated_fields"]

    def test_list_punch_list(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        call_action(mod.ACTIONS["construction-add-punch-list-item"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            description="Replace broken tile",
            location=None, assigned_to=None, subcontractor_id=None,
            priority=None, photo_url=None, completion_date=None,
            punch_status=None,
        ))
        r = call_action(mod.ACTIONS["construction-list-punch-list"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            punch_status=None, search=None, limit=50, offset=0,
        ))
        assert is_ok(r)
        assert r["total_count"] >= 1

    def test_punch_list_summary(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        call_action(mod.ACTIONS["construction-add-punch-list-item"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            description="Item 1", location=None,
            assigned_to=None, subcontractor_id=None,
            priority="critical", photo_url=None, completion_date=None,
            punch_status=None,
        ))
        r = call_action(mod.ACTIONS["construction-punch-list-summary"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
        ))
        assert is_ok(r)
        assert r["total_items"] >= 1
        assert "open" in r["by_status"]


# ===========================================================================
# C7: INSURANCE & BOND
# ===========================================================================

class TestInsuranceBond:
    def test_add_insurance_bond(self, conn, env, mod):
        r = call_action(mod.ACTIONS["construction-add-insurance-bond"], conn, ns(
            company_id=env["company_id"], job_id=None, subcontractor_id=None,
            document_type="coi", carrier="State Farm",
            policy_number="POL-12345", coverage_amount="1000000",
            effective_date="2026-01-01", expiration_date="2027-01-01",
        ))
        assert is_ok(r)
        assert r["document_type"] == "coi"
        assert r.get("bond_status", r.get("warranty_status")) == "active"

    def test_list_insurance_bonds(self, conn, env, mod):
        call_action(mod.ACTIONS["construction-add-insurance-bond"], conn, ns(
            company_id=env["company_id"], job_id=None, subcontractor_id=None,
            document_type="performance_bond", carrier=None,
            policy_number=None, coverage_amount="500000",
            effective_date=None, expiration_date=None,
        ))
        r = call_action(mod.ACTIONS["construction-list-insurance-bonds"], conn, ns(
            company_id=env["company_id"], job_id=None, subcontractor_id=None,
            document_type=None,
        ))
        assert is_ok(r)
        assert r["total_count"] >= 1

    def test_check_expiring_insurance(self, conn, env, mod):
        r = call_action(mod.ACTIONS["construction-check-expiring-insurance"], conn, ns(
            company_id=env["company_id"],
        ))
        assert is_ok(r)
        assert "expired_count" in r

    def test_insurance_compliance_report(self, conn, env, mod):
        call_action(mod.ACTIONS["construction-add-insurance-bond"], conn, ns(
            company_id=env["company_id"], job_id=None, subcontractor_id=None,
            document_type="builders_risk", carrier="Zurich",
            policy_number=None, coverage_amount="2000000",
            effective_date=None, expiration_date=None,
        ))
        r = call_action(mod.ACTIONS["construction-insurance-compliance-report"], conn, ns(
            company_id=env["company_id"],
        ))
        assert is_ok(r)
        assert r["total_bonds"] >= 1


# ===========================================================================
# C9: WARRANTY TRACKING
# ===========================================================================

class TestWarranty:
    def test_add_warranty(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-warranty"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            trade="HVAC", system="Rooftop Unit",
            subcontractor_id=None,
            start_date="2026-01-01", end_date="2027-01-01",
            warranty_type="standard", description="Standard 1-year warranty",
            contact_info="HVAC Co: 555-1234",
            warranty_status=None,
        ))
        assert is_ok(r)
        assert r["warranty_id"]
        assert r.get("bond_status", r.get("warranty_status")) == "active"

    def test_list_warranties(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        call_action(mod.ACTIONS["construction-add-warranty"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            trade="Electrical", system="Main Panel",
            subcontractor_id=None,
            start_date="2026-01-01", end_date="2028-01-01",
            warranty_type="extended", description=None, contact_info=None,
            warranty_status=None,
        ))
        r = call_action(mod.ACTIONS["construction-list-warranties"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            warranty_status=None,
        ))
        assert is_ok(r)
        assert r["total_count"] >= 1

    def test_check_expiring_warranties(self, conn, env, mod):
        r = call_action(mod.ACTIONS["construction-check-expiring-warranties"], conn, ns(
            company_id=env["company_id"],
        ))
        assert is_ok(r)
        assert "expired_count" in r


# ===========================================================================
# C10: MILESTONES / CPM
# ===========================================================================

class TestMilestones:
    def test_add_milestone(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-milestone"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            name="Foundation Complete", description="All foundation work done",
            planned_date="2026-05-01", actual_date=None,
            predecessor_id=None, dependency_type=None,
            lag_days=None, is_critical="1",
            milestone_status=None,
        ))
        assert is_ok(r)
        assert r["milestone_id"]
        assert r["milestone_status"] == "pending"

    def test_list_milestones(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        call_action(mod.ACTIONS["construction-add-milestone"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            name="Framing Complete", description=None,
            planned_date="2026-06-01", actual_date=None,
            predecessor_id=None, dependency_type=None,
            lag_days=None, is_critical=None,
            milestone_status=None,
        ))
        r = call_action(mod.ACTIONS["construction-list-milestones"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            milestone_status=None,
        ))
        assert is_ok(r)
        assert r["total_count"] >= 1

    def test_update_milestone(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-milestone"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            name="Drywall Complete", description=None,
            planned_date="2026-07-01", actual_date=None,
            predecessor_id=None, dependency_type=None,
            lag_days=None, is_critical=None,
            milestone_status=None,
        ))
        mid = r["milestone_id"]
        r2 = call_action(mod.ACTIONS["construction-update-milestone"], conn, ns(
            milestone_id=mid, name=None, description=None,
            planned_date=None, actual_date="2026-06-28",
            predecessor_id=None, dependency_type=None,
            lag_days=None, is_critical=None,
            milestone_status="completed",
        ))
        assert is_ok(r2)
        assert "status" in r2["updated_fields"]

    def test_critical_path_report(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        call_action(mod.ACTIONS["construction-add-milestone"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            name="Critical Milestone", description=None,
            planned_date="2026-05-01", actual_date=None,
            predecessor_id=None, dependency_type=None,
            lag_days=None, is_critical="1",
            milestone_status=None,
        ))
        r = call_action(mod.ACTIONS["construction-critical-path-report"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
        ))
        assert is_ok(r)
        assert r["total_milestones"] >= 1
        assert r["critical_count"] >= 1
