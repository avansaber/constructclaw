"""L1 tests for ConstructClaw -- Safety, Controls, and Reports domains.

Covers: incidents, toolbox talks, safety certs, OSHA 300, safety dashboard,
        earned value, EV metrics, schedule variance, cost forecast,
        project health dashboard, executive summary, reports.
"""
import pytest
from construct_helpers import call_action, ns, is_ok, is_error, load_db_query, _uuid


@pytest.fixture
def mod():
    return load_db_query()


def _add_job(conn, env, mod, name="Safety/Controls Job", contract_amount="1000000"):
    r = call_action(mod.ACTIONS["construction-add-job"], conn, ns(
        company_id=env["company_id"], name=name,
        job_type=None, contract_type=None, contract_amount=contract_amount,
        client_name=None, client_id=None, description=None,
        project_manager=None, superintendent=None,
        start_date=None, end_date=None, address=None,
        city=None, state=None, zip_code=None, notes=None,
    ))
    assert is_ok(r)
    return r["job_id"]


# ═══════════════════════════════════════════════════════════════════════════
# INCIDENTS
# ═══════════════════════════════════════════════════════════════════════════

class TestIncidents:
    def test_add_incident(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-incident"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            description="Worker tripped on debris",
            incident_type="first_aid", severity="minor",
            location="Building A, Floor 2",
            injured_party="John Doe", witnesses="Jane Smith",
            root_cause="Housekeeping", corrective_action="Cleanup protocol",
            osha_recordable=None, days_lost=None,
            incident_date="2026-03-10", incident_time="10:30",
            notes=None,
        ))
        assert is_ok(r)
        d = r
        assert d["naming_series"].startswith("CCINC-")
        assert d["incident_type"] == "first_aid"
        assert d["severity"] == "minor"
        assert d["osha_recordable"] == 0  # first_aid is not OSHA recordable
        assert d["incident_status"] == "open"

    def test_add_incident_osha_recordable(self, conn, env, mod):
        """Recordable incidents are auto-flagged as osha_recordable=1."""
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-incident"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            description="Worker fell from scaffold",
            incident_type="lost_time", severity="serious",
            location="Scaffold A", injured_party="Bob Builder",
            witnesses=None, root_cause=None, corrective_action=None,
            osha_recordable=None, days_lost="5",
            incident_date=None, incident_time=None, notes=None,
        ))
        assert is_ok(r)
        assert r["osha_recordable"] == 1

    def test_update_incident(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-incident"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            description="Update test",
            incident_type="near_miss", severity="minor",
            location=None, injured_party=None, witnesses=None,
            root_cause=None, corrective_action=None,
            osha_recordable=None, days_lost=None,
            incident_date=None, incident_time=None, notes=None,
        ))
        inc_id = r["incident_id"]

        r2 = call_action(mod.ACTIONS["construction-update-incident"], conn, ns(
            incident_id=inc_id, incident_date=None, incident_time=None,
            location="Updated Location", description=None,
            injured_party=None, witnesses=None,
            root_cause="Lack of barricade", corrective_action="Install barricade",
            notes=None, incident_type=None, severity=None,
            days_lost=None, osha_recordable=None,
        ))
        assert is_ok(r2)
        assert "location" in r2["updated_fields"]
        assert "root_cause" in r2["updated_fields"]

    def test_close_incident(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-incident"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            description="Close me",
            incident_type="near_miss", severity="minor",
            location=None, injured_party=None, witnesses=None,
            root_cause=None, corrective_action=None,
            osha_recordable=None, days_lost=None,
            incident_date=None, incident_time=None, notes=None,
        ))
        inc_id = r["incident_id"]

        r2 = call_action(mod.ACTIONS["construction-close-incident"], conn, ns(
            incident_id=inc_id,
        ))
        assert is_ok(r2)
        assert r2["incident_status"] == "closed"

    def test_close_already_closed(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-incident"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            description="Double close",
            incident_type="near_miss", severity="minor",
            location=None, injured_party=None, witnesses=None,
            root_cause=None, corrective_action=None,
            osha_recordable=None, days_lost=None,
            incident_date=None, incident_time=None, notes=None,
        ))
        inc_id = r["incident_id"]
        call_action(mod.ACTIONS["construction-close-incident"], conn, ns(
            incident_id=inc_id,
        ))
        r2 = call_action(mod.ACTIONS["construction-close-incident"], conn, ns(
            incident_id=inc_id,
        ))
        assert is_error(r2)

    def test_list_incidents(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        call_action(mod.ACTIONS["construction-add-incident"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            description="Incident 1",
            incident_type="near_miss", severity="minor",
            location=None, injured_party=None, witnesses=None,
            root_cause=None, corrective_action=None,
            osha_recordable=None, days_lost=None,
            incident_date=None, incident_time=None, notes=None,
        ))
        r = call_action(mod.ACTIONS["construction-list-incidents"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            incident_type=None, incident_status=None,
            search=None, limit=50, offset=0,
        ))
        assert is_ok(r)
        assert r["total_count"] == 1


# ═══════════════════════════════════════════════════════════════════════════
# TOOLBOX TALKS
# ═══════════════════════════════════════════════════════════════════════════

class TestToolboxTalks:
    def test_add_toolbox_talk(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-toolbox-talk"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            topic="Fall Protection Refresher",
            talk_date="2026-03-10", presenter="Safety Manager",
            attendee_count="25", attendees="Crew A, Crew B",
            duration_minutes="30", notes=None,
        ))
        assert is_ok(r)
        assert r["topic"] == "Fall Protection Refresher"

    def test_list_toolbox_talks(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        call_action(mod.ACTIONS["construction-add-toolbox-talk"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            topic="Scaffolding Safety", talk_date=None,
            presenter=None, attendee_count=None,
            attendees=None, duration_minutes=None, notes=None,
        ))
        r = call_action(mod.ACTIONS["construction-list-toolbox-talks"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
        ))
        assert is_ok(r)
        assert r["total_count"] == 1


# ═══════════════════════════════════════════════════════════════════════════
# SAFETY CERTS
# ═══════════════════════════════════════════════════════════════════════════

class TestSafetyCerts:
    def test_add_safety_cert(self, conn, env, mod):
        r = call_action(mod.ACTIONS["construction-add-safety-cert"], conn, ns(
            company_id=env["company_id"], job_id=None,
            worker_name="Mike Johnson",
            cert_type="OSHA 30-Hour", cert_number="OS30-12345",
            issued_date="2025-06-15", expiry_date="2029-06-15",
            issuing_authority="OSHA",
        ))
        assert is_ok(r)
        assert r["cert_type"] == "OSHA 30-Hour"
        assert r["cert_status"] == "active"

    def test_expire_safety_cert(self, conn, env, mod):
        r = call_action(mod.ACTIONS["construction-add-safety-cert"], conn, ns(
            company_id=env["company_id"], job_id=None,
            worker_name="Expiring Worker",
            cert_type="First Aid", cert_number=None,
            issued_date=None, expiry_date=None,
            issuing_authority=None,
        ))
        sc_id = r["safety_cert_id"]

        r2 = call_action(mod.ACTIONS["construction-expire-safety-cert"], conn, ns(
            safety_cert_id=sc_id,
        ))
        assert is_ok(r2)
        assert r2["cert_status"] == "expired"

    def test_expire_already_expired(self, conn, env, mod):
        r = call_action(mod.ACTIONS["construction-add-safety-cert"], conn, ns(
            company_id=env["company_id"], job_id=None,
            worker_name="Already Expired",
            cert_type="CPR", cert_number=None,
            issued_date=None, expiry_date=None,
            issuing_authority=None,
        ))
        sc_id = r["safety_cert_id"]
        call_action(mod.ACTIONS["construction-expire-safety-cert"], conn, ns(
            safety_cert_id=sc_id,
        ))
        r2 = call_action(mod.ACTIONS["construction-expire-safety-cert"], conn, ns(
            safety_cert_id=sc_id,
        ))
        assert is_error(r2)


# ═══════════════════════════════════════════════════════════════════════════
# OSHA 300 SUMMARY + SAFETY DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════

class TestSafetyReports:
    def test_osha_300_summary(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        # Add a recordable incident
        call_action(mod.ACTIONS["construction-add-incident"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            description="Recordable test",
            incident_type="recordable", severity="moderate",
            location=None, injured_party="Worker A", witnesses=None,
            root_cause=None, corrective_action=None,
            osha_recordable=None, days_lost="3",
            incident_date="2026-03-05", incident_time=None, notes=None,
        ))
        # Add a non-recordable
        call_action(mod.ACTIONS["construction-add-incident"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            description="Near miss",
            incident_type="near_miss", severity="minor",
            location=None, injured_party=None, witnesses=None,
            root_cause=None, corrective_action=None,
            osha_recordable=None, days_lost=None,
            incident_date="2026-03-06", incident_time=None, notes=None,
        ))
        r = call_action(mod.ACTIONS["construction-osha-300-summary"], conn, ns(
            company_id=env["company_id"], job_id=None,
            start_date=None, end_date=None,
        ))
        assert is_ok(r)
        d = r
        assert d["total_recordable_incidents"] == 1
        assert d["total_days_lost"] == 3

    def test_safety_dashboard(self, conn, env, mod):
        r = call_action(mod.ACTIONS["construction-safety-dashboard"], conn, ns(
            company_id=env["company_id"],
        ))
        assert is_ok(r)
        d = r
        assert "total_incidents" in d
        assert "open_incidents" in d
        assert "toolbox_talks_conducted" in d


# ═══════════════════════════════════════════════════════════════════════════
# EARNED VALUE + PROJECT CONTROLS
# ═══════════════════════════════════════════════════════════════════════════

class TestEarnedValue:
    def test_add_earned_value(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-earned-value"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            period_date="2026-03-31",
            planned_value="300000", earned_value="280000",
            actual_cost="270000", budget_at_completion="1000000",
            notes=None,
        ))
        assert is_ok(r)
        assert r["earned_value_id"]
        assert r["job_id"] == job_id

    def test_calculate_ev_metrics(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        call_action(mod.ACTIONS["construction-add-earned-value"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            period_date="2026-03-31",
            planned_value="400000", earned_value="360000",
            actual_cost="380000", budget_at_completion="1000000",
            notes=None,
        ))
        r = call_action(mod.ACTIONS["construction-calculate-ev-metrics"], conn, ns(
            job_id=job_id,
        ))
        assert is_ok(r)
        d = r
        # SV = EV - PV = 360000 - 400000 = -40000
        assert d["schedule_variance"] == "-40000.00"
        # CV = EV - AC = 360000 - 380000 = -20000
        assert d["cost_variance"] == "-20000.00"
        # SPI = EV/PV = 360000/400000 = 0.90
        assert d["spi"] == "0.90"
        # CPI = EV/AC = 360000/380000 = 0.95 (rounded)
        assert d["cpi"] == "0.95"
        assert d["schedule_health"] == "behind"
        assert d["cost_health"] == "over_budget"

    def test_calculate_ev_metrics_no_data(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-calculate-ev-metrics"], conn, ns(
            job_id=job_id,
        ))
        assert is_error(r)


class TestProjectControls:
    def test_cost_forecast(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-cost-forecast"], conn, ns(
            job_id=job_id,
        ))
        assert is_ok(r)
        d = r
        assert d["contract_amount"] == "1000000.00"
        assert d["actual_cost"] == "0.00"
        assert d["total_committed"] == "0.00"

    def test_project_health_dashboard(self, conn, env, mod):
        _add_job(conn, env, mod, name="Active Job")
        r = call_action(mod.ACTIONS["construction-project-health-dashboard"], conn, ns(
            company_id=env["company_id"],
        ))
        assert is_ok(r)
        d = r
        assert d["total_jobs"] == 1
        assert "open_rfis" in d
        assert "open_safety_incidents" in d

    def test_schedule_variance_report(self, conn, env, mod):
        """Schedule variance report only includes active/on_hold jobs."""
        r = call_action(mod.ACTIONS["construction-schedule-variance-report"], conn, ns(
            company_id=env["company_id"],
        ))
        assert is_ok(r)
        # No active jobs yet (default status is planning)
        assert r["total_count"] == 0

    def test_resource_utilization(self, conn, env, mod):
        r = call_action(mod.ACTIONS["construction-resource-utilization"], conn, ns(
            company_id=env["company_id"],
        ))
        assert is_ok(r)
        assert "daily_report_labor_hours" in r
        assert "by_trade" in r

    def test_module_status(self, conn, env, mod):
        r = call_action(mod.ACTIONS["status"], conn, ns(
            company_id=env["company_id"],
        ))
        assert is_ok(r)
        assert r["skill"] == "constructclaw"
        assert r["total_tables"] == 21


# ═══════════════════════════════════════════════════════════════════════════
# REPORTS
# ═══════════════════════════════════════════════════════════════════════════

class TestReports:
    def test_executive_summary(self, conn, env, mod):
        _add_job(conn, env, mod, name="Exec Summary Job")
        r = call_action(mod.ACTIONS["construction-executive-summary"], conn, ns(
            company_id=env["company_id"],
        ))
        assert is_ok(r)
        d = r
        assert "jobs_by_status" in d
        assert "total_contract_value" in d
        assert "overall_margin_pct" in d

    def test_portfolio_overview(self, conn, env, mod):
        _add_job(conn, env, mod, name="Portfolio Job", contract_amount="500000")
        r = call_action(mod.ACTIONS["construction-portfolio-overview"], conn, ns(
            company_id=env["company_id"],
        ))
        assert is_ok(r)
        d = r
        assert d["total_count"] == 1
        assert d["portfolio"][0]["contract_amount"] == "500000.00"

    def test_report_status(self, conn, env, mod):
        r = call_action(mod.ACTIONS["construction-report-status"], conn, ns())
        assert is_ok(r)
        assert r["skill"] == "constructclaw"

    def test_safety_report(self, conn, env, mod):
        r = call_action(mod.ACTIONS["construction-safety-report"], conn, ns(
            company_id=env["company_id"],
        ))
        assert is_ok(r)
        assert "total_incidents" in r
        assert "osha_recordable" in r

    def test_job_cost_report(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-job-cost-report"], conn, ns(
            job_id=job_id,
        ))
        assert is_ok(r)
        d = r
        assert d["original_contract"] == "1000000.00"
        assert d["total_cost"] == "0.00"
        assert "by_category" in d

    def test_wip_report_all(self, conn, env, mod):
        """WIP report-all only includes active/on_hold/substantially_complete jobs."""
        r = call_action(mod.ACTIONS["construction-wip-report-all"], conn, ns(
            company_id=env["company_id"],
        ))
        assert is_ok(r)
        # No active jobs yet
        assert r["total_count"] == 0
