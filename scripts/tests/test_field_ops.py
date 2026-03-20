"""L1 tests for ConstructClaw -- Field Operations domain.

Covers: equipment scheduling (C1), certified payroll / prevailing wage (C2),
        labor time tracking (C3).
"""
import pytest
from construct_helpers import call_action, ns, is_ok, is_error, load_db_query, _uuid


@pytest.fixture
def mod():
    return load_db_query()


def _add_job(conn, env, mod, name="Field Ops Job", contract_amount="1000000"):
    r = call_action(mod.ACTIONS["construction-add-job"], conn, ns(
        company_id=env["company_id"], name=name,
        job_type=None, contract_type=None, contract_amount=contract_amount,
        client_name="Acme Corp", client_id=None, description=None,
        project_manager=None, superintendent=None,
        start_date=None, end_date=None, address=None,
        city=None, state=None, zip_code=None, notes=None,
    ))
    assert is_ok(r)
    return r["job_id"]


# ===========================================================================
# C1: EQUIPMENT SCHEDULING
# ===========================================================================

class TestEquipmentAssignment:
    def test_assign_equipment(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-assign-equipment"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            equipment_name="CAT 320 Excavator",
            equipment_type="excavator",
            start_date="2026-04-01", end_date="2026-04-30",
            daily_rate="1500", mobilization_cost="3000",
            demobilization_cost="2000", actual_hours=None, notes=None,
        ))
        assert is_ok(r)
        assert r["assignment_id"]
        assert r["equipment_name"] == "CAT 320 Excavator"
        assert r["assignment_status"] == "scheduled"

    def test_assign_equipment_missing_name(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-assign-equipment"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            equipment_name=None, equipment_type=None,
            start_date="2026-04-01", end_date=None,
            daily_rate=None, mobilization_cost=None,
            demobilization_cost=None, actual_hours=None, notes=None,
        ))
        assert is_error(r)

    def test_release_equipment(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-assign-equipment"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            equipment_name="Crane 50T",
            equipment_type="crane",
            start_date="2026-04-01", end_date=None,
            daily_rate="2500", mobilization_cost="5000",
            demobilization_cost="4000", actual_hours=None, notes=None,
        ))
        ea_id = r["assignment_id"]

        r2 = call_action(mod.ACTIONS["construction-release-equipment"], conn, ns(
            assignment_id=ea_id, end_date="2026-04-15", actual_hours="120",
        ))
        assert is_ok(r2)
        assert r2["assignment_status"] == "completed"

    def test_release_already_completed(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-assign-equipment"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            equipment_name="Loader", equipment_type="loader",
            start_date="2026-04-01", end_date=None,
            daily_rate="800", mobilization_cost=None,
            demobilization_cost=None, actual_hours=None, notes=None,
        ))
        ea_id = r["assignment_id"]
        call_action(mod.ACTIONS["construction-release-equipment"], conn, ns(
            assignment_id=ea_id, end_date=None, actual_hours=None,
        ))
        r2 = call_action(mod.ACTIONS["construction-release-equipment"], conn, ns(
            assignment_id=ea_id, end_date=None, actual_hours=None,
        ))
        assert is_error(r2)

    def test_update_equipment_assignment(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-assign-equipment"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            equipment_name="Boom Lift", equipment_type="aerial",
            start_date="2026-04-01", end_date=None,
            daily_rate="400", mobilization_cost=None,
            demobilization_cost=None, actual_hours=None, notes=None,
        ))
        ea_id = r["assignment_id"]

        r2 = call_action(mod.ACTIONS["construction-update-equipment-assignment"], conn, ns(
            assignment_id=ea_id,
            equipment_name=None, equipment_type=None,
            start_date=None, end_date=None,
            daily_rate="500", mobilization_cost=None,
            demobilization_cost=None, actual_hours=None,
            equipment_status=None, notes="Rate changed",
        ))
        assert is_ok(r2)
        assert "daily_rate" in r2["updated_fields"]
        assert "notes" in r2["updated_fields"]

    def test_list_equipment_assignments(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        call_action(mod.ACTIONS["construction-assign-equipment"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            equipment_name="Bulldozer D6", equipment_type="dozer",
            start_date="2026-04-01", end_date=None,
            daily_rate="1200", mobilization_cost=None,
            demobilization_cost=None, actual_hours=None, notes=None,
        ))
        call_action(mod.ACTIONS["construction-assign-equipment"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            equipment_name="Compactor", equipment_type="compaction",
            start_date="2026-04-05", end_date=None,
            daily_rate="600", mobilization_cost=None,
            demobilization_cost=None, actual_hours=None, notes=None,
        ))
        r = call_action(mod.ACTIONS["construction-list-equipment-assignments"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            equipment_status=None, search=None, limit=50, offset=0,
        ))
        assert is_ok(r)
        assert r["total_count"] == 2

    def test_equipment_utilization_report(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        call_action(mod.ACTIONS["construction-assign-equipment"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            equipment_name="Excavator", equipment_type="excavator",
            start_date="2026-04-01", end_date="2026-04-10",
            daily_rate="1500", mobilization_cost="3000",
            demobilization_cost="2000", actual_hours="80", notes=None,
        ))
        r = call_action(mod.ACTIONS["construction-equipment-utilization-report"], conn, ns(
            company_id=env["company_id"], job_id=None,
        ))
        assert is_ok(r)
        assert r["total_assignments"] == 1
        assert r["total_daily_rate_sum"] == "1500.00"
        assert r["total_mobilization_cost"] == "3000.00"
        assert r["total_actual_hours"] == "80.00"

    def test_equipment_conflict_check_no_conflict(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        call_action(mod.ACTIONS["construction-assign-equipment"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            equipment_name="Crane 100T", equipment_type="crane",
            start_date="2026-04-01", end_date="2026-04-15",
            daily_rate="3000", mobilization_cost=None,
            demobilization_cost=None, actual_hours=None, notes=None,
        ))
        # Check for a non-overlapping period
        r = call_action(mod.ACTIONS["construction-equipment-conflict-check"], conn, ns(
            company_id=env["company_id"],
            equipment_name="Crane 100T",
            start_date="2026-04-20", end_date="2026-04-30",
        ))
        assert is_ok(r)
        assert r["has_conflict"] is False
        assert r["conflict_count"] == 0

    def test_equipment_conflict_check_with_conflict(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        call_action(mod.ACTIONS["construction-assign-equipment"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            equipment_name="Crane 100T", equipment_type="crane",
            start_date="2026-04-01", end_date="2026-04-15",
            daily_rate="3000", mobilization_cost=None,
            demobilization_cost=None, actual_hours=None, notes=None,
        ))
        # Check for overlapping period
        r = call_action(mod.ACTIONS["construction-equipment-conflict-check"], conn, ns(
            company_id=env["company_id"],
            equipment_name="Crane 100T",
            start_date="2026-04-10", end_date="2026-04-20",
        ))
        assert is_ok(r)
        assert r["has_conflict"] is True
        assert r["conflict_count"] == 1


# ===========================================================================
# C2: CERTIFIED PAYROLL / PREVAILING WAGE
# ===========================================================================

class TestPrevailingWage:
    def test_add_prevailing_wage_rate(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-prevailing-wage-rate"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            trade="Electrician", classification="Journeyman",
            basic_rate="45.50", fringe_rate="12.75", total_rate="58.25",
            overtime_rate="68.25",
            wage_determination_number="WD-2026-0042",
            effective_date="2026-01-01",
        ))
        assert is_ok(r)
        assert r["wage_rate_id"]
        assert r["trade"] == "Electrician"
        assert r["classification"] == "Journeyman"
        assert r["total_rate"] == "58.25"
        assert r["wage_status"] == "active"

    def test_add_prevailing_wage_rate_missing_fields(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-prevailing-wage-rate"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            trade=None, classification=None,
            basic_rate=None, fringe_rate=None, total_rate=None,
            overtime_rate=None, wage_determination_number=None,
            effective_date=None,
        ))
        assert is_error(r)

    def test_list_prevailing_wage_rates(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        call_action(mod.ACTIONS["construction-add-prevailing-wage-rate"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            trade="Plumber", classification="Apprentice",
            basic_rate="28.00", fringe_rate="8.50", total_rate="36.50",
            overtime_rate=None, wage_determination_number=None,
            effective_date=None,
        ))
        call_action(mod.ACTIONS["construction-add-prevailing-wage-rate"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            trade="Plumber", classification="Journeyman",
            basic_rate="42.00", fringe_rate="12.00", total_rate="54.00",
            overtime_rate=None, wage_determination_number=None,
            effective_date=None,
        ))
        r = call_action(mod.ACTIONS["construction-list-prevailing-wage-rates"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            trade=None, wage_status=None,
        ))
        assert is_ok(r)
        assert r["total_count"] == 2


class TestCertifiedPayroll:
    def test_add_certified_payroll_entry(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-certified-payroll-entry"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            week_ending="2026-04-05",
            employee_name="John Smith", employee_id="EMP-001",
            trade="Electrician", classification="Journeyman",
            mon_hours="8", tue_hours="8", wed_hours="8",
            thu_hours="8", fri_hours="8", sat_hours="4", sun_hours="0",
            overtime_hours="4",
            hourly_rate="45.50", gross_pay="2275.00",
            fica="174.04", federal_tax="341.25", state_tax="113.75",
            other_deductions="50.00", net_pay="1595.96",
            fringe_paid="573.75", fringe_method="cash",
        ))
        assert is_ok(r)
        assert r["payroll_entry_id"]
        assert r["employee_name"] == "John Smith"
        assert r["total_hours"] == "44"  # 8+8+8+8+8+4+0
        assert r["gross_pay"] == "2275.00"
        assert r["net_pay"] == "1595.96"

    def test_add_certified_payroll_entry_missing_fields(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-certified-payroll-entry"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            week_ending=None, employee_name=None, employee_id=None,
            trade=None, classification=None,
            mon_hours=None, tue_hours=None, wed_hours=None,
            thu_hours=None, fri_hours=None, sat_hours=None, sun_hours=None,
            overtime_hours=None, hourly_rate=None, gross_pay=None,
            fica=None, federal_tax=None, state_tax=None,
            other_deductions=None, net_pay=None,
            fringe_paid=None, fringe_method=None,
        ))
        assert is_error(r)

    def test_list_certified_payroll(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        call_action(mod.ACTIONS["construction-add-certified-payroll-entry"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            week_ending="2026-04-05",
            employee_name="Alice Johnson", employee_id=None,
            trade="Laborer", classification="General",
            mon_hours="8", tue_hours="8", wed_hours="8",
            thu_hours="8", fri_hours="8", sat_hours="0", sun_hours="0",
            overtime_hours="0",
            hourly_rate="22.00", gross_pay="880.00",
            fica="67.32", federal_tax="132.00", state_tax="44.00",
            other_deductions="0", net_pay="636.68",
            fringe_paid="0", fringe_method="cash",
        ))
        r = call_action(mod.ACTIONS["construction-list-certified-payroll"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            week_ending=None,
        ))
        assert is_ok(r)
        assert r["total_count"] == 1

    def test_generate_wh347(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        # Add two employees for the same week
        call_action(mod.ACTIONS["construction-add-certified-payroll-entry"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            week_ending="2026-04-12",
            employee_name="Bob Wilson", employee_id=None,
            trade="Carpenter", classification="Journeyman",
            mon_hours="8", tue_hours="8", wed_hours="8",
            thu_hours="8", fri_hours="8", sat_hours="0", sun_hours="0",
            overtime_hours="0",
            hourly_rate="38.00", gross_pay="1520.00",
            fica="116.28", federal_tax="228.00", state_tax="76.00",
            other_deductions="0", net_pay="1099.72",
            fringe_paid="300.00", fringe_method="cash",
        ))
        call_action(mod.ACTIONS["construction-add-certified-payroll-entry"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            week_ending="2026-04-12",
            employee_name="Carol Davis", employee_id=None,
            trade="Ironworker", classification="Journeyman",
            mon_hours="8", tue_hours="8", wed_hours="8",
            thu_hours="8", fri_hours="8", sat_hours="0", sun_hours="0",
            overtime_hours="0",
            hourly_rate="42.00", gross_pay="1680.00",
            fica="128.52", federal_tax="252.00", state_tax="84.00",
            other_deductions="0", net_pay="1215.48",
            fringe_paid="350.00", fringe_method="plan",
        ))
        r = call_action(mod.ACTIONS["construction-generate-wh347"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            week_ending="2026-04-12",
        ))
        assert is_ok(r)
        assert r["report"] == "WH-347 Certified Payroll"
        assert r["entry_count"] == 2
        assert r["totals"]["total_gross_pay"] == "3200.00"
        assert r["totals"]["total_net_pay"] == "2315.20"
        assert r["totals"]["total_fringe_paid"] == "650.00"

    def test_certified_payroll_summary(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        # Week 1
        call_action(mod.ACTIONS["construction-add-certified-payroll-entry"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            week_ending="2026-04-05",
            employee_name="Dan Brown", employee_id=None,
            trade="Laborer", classification="General",
            mon_hours="8", tue_hours="8", wed_hours="8",
            thu_hours="8", fri_hours="8", sat_hours="0", sun_hours="0",
            overtime_hours="0",
            hourly_rate="22.00", gross_pay="880.00",
            fica="67.32", federal_tax="132.00", state_tax="44.00",
            other_deductions="0", net_pay="636.68",
            fringe_paid="0", fringe_method="cash",
        ))
        # Week 2
        call_action(mod.ACTIONS["construction-add-certified-payroll-entry"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            week_ending="2026-04-12",
            employee_name="Dan Brown", employee_id=None,
            trade="Laborer", classification="General",
            mon_hours="8", tue_hours="8", wed_hours="8",
            thu_hours="8", fri_hours="8", sat_hours="4", sun_hours="0",
            overtime_hours="4",
            hourly_rate="22.00", gross_pay="1012.00",
            fica="77.42", federal_tax="151.80", state_tax="50.60",
            other_deductions="0", net_pay="732.18",
            fringe_paid="0", fringe_method="cash",
        ))
        r = call_action(mod.ACTIONS["construction-certified-payroll-summary"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
        ))
        assert is_ok(r)
        assert r["total_weeks"] == 2
        assert r["grand_totals"]["total_gross_pay"] == "1892.00"


# ===========================================================================
# C3: LABOR TIME TRACKING
# ===========================================================================

class TestTimeEntry:
    def test_add_time_entry(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-time-entry"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            cost_code_id=None,
            employee_name="Mike Worker", employee_id="EMP-100",
            trade="Carpenter", work_date="2026-04-01",
            regular_hours="8", overtime_hours="2", double_time_hours="0",
            hourly_rate="38.00", description="Framing work",
        ))
        assert is_ok(r)
        assert r["time_entry_id"]
        assert r["employee_name"] == "Mike Worker"
        assert r["total_hours"] == "10"  # 8 + 2 + 0
        # Cost = (8 * 38) + (2 * 38 * 1.5) + (0 * 38 * 2) = 304 + 114 = 418
        assert r["total_cost"] == "418.00"
        assert r["time_status"] == "draft"

    def test_add_time_entry_with_double_time(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-time-entry"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            cost_code_id=None,
            employee_name="Sunday Worker", employee_id=None,
            trade="Laborer", work_date="2026-04-06",
            regular_hours="0", overtime_hours="0", double_time_hours="8",
            hourly_rate="22.00", description="Emergency Sunday work",
        ))
        assert is_ok(r)
        assert r["total_hours"] == "8"
        # Cost = 0 + 0 + (8 * 22 * 2) = 352
        assert r["total_cost"] == "352.00"

    def test_add_time_entry_missing_fields(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-time-entry"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            cost_code_id=None,
            employee_name=None, employee_id=None,
            trade=None, work_date=None,
            regular_hours=None, overtime_hours=None, double_time_hours=None,
            hourly_rate=None, description=None,
        ))
        assert is_error(r)

    def test_list_time_entries(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        call_action(mod.ACTIONS["construction-add-time-entry"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            cost_code_id=None,
            employee_name="Worker A", employee_id=None,
            trade="Plumber", work_date="2026-04-01",
            regular_hours="8", overtime_hours="0", double_time_hours="0",
            hourly_rate="42.00", description=None,
        ))
        call_action(mod.ACTIONS["construction-add-time-entry"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            cost_code_id=None,
            employee_name="Worker B", employee_id=None,
            trade="Electrician", work_date="2026-04-01",
            regular_hours="8", overtime_hours="1", double_time_hours="0",
            hourly_rate="45.00", description=None,
        ))
        r = call_action(mod.ACTIONS["construction-list-time-entries"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            employee_name=None, time_status=None,
            search=None, limit=50, offset=0,
        ))
        assert is_ok(r)
        assert r["total_count"] == 2

    def test_approve_time_entry(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-time-entry"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            cost_code_id=None,
            employee_name="Approval Worker", employee_id=None,
            trade="Laborer", work_date="2026-04-01",
            regular_hours="8", overtime_hours="0", double_time_hours="0",
            hourly_rate="22.00", description=None,
        ))
        te_id = r["time_entry_id"]

        r2 = call_action(mod.ACTIONS["construction-approve-time-entry"], conn, ns(
            time_entry_id=te_id, approved_by="Supervisor Joe",
        ))
        assert is_ok(r2)
        assert r2["time_status"] == "approved"

    def test_approve_already_approved(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-time-entry"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            cost_code_id=None,
            employee_name="Double Approve", employee_id=None,
            trade="Laborer", work_date="2026-04-01",
            regular_hours="8", overtime_hours="0", double_time_hours="0",
            hourly_rate="22.00", description=None,
        ))
        te_id = r["time_entry_id"]
        call_action(mod.ACTIONS["construction-approve-time-entry"], conn, ns(
            time_entry_id=te_id, approved_by=None,
        ))
        r2 = call_action(mod.ACTIONS["construction-approve-time-entry"], conn, ns(
            time_entry_id=te_id, approved_by=None,
        ))
        assert is_error(r2)

    def test_reject_time_entry(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-time-entry"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            cost_code_id=None,
            employee_name="Reject Worker", employee_id=None,
            trade="Laborer", work_date="2026-04-01",
            regular_hours="8", overtime_hours="0", double_time_hours="0",
            hourly_rate="22.00", description=None,
        ))
        te_id = r["time_entry_id"]

        r2 = call_action(mod.ACTIONS["construction-reject-time-entry"], conn, ns(
            time_entry_id=te_id, notes="Hours seem incorrect",
        ))
        assert is_ok(r2)
        assert r2["time_status"] == "rejected"

    def test_time_entry_summary(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        # Add multiple entries for same employee
        call_action(mod.ACTIONS["construction-add-time-entry"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            cost_code_id=None,
            employee_name="Summary Worker", employee_id=None,
            trade="Carpenter", work_date="2026-04-01",
            regular_hours="8", overtime_hours="0", double_time_hours="0",
            hourly_rate="38.00", description=None,
        ))
        call_action(mod.ACTIONS["construction-add-time-entry"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            cost_code_id=None,
            employee_name="Summary Worker", employee_id=None,
            trade="Carpenter", work_date="2026-04-02",
            regular_hours="8", overtime_hours="2", double_time_hours="0",
            hourly_rate="38.00", description=None,
        ))
        r = call_action(mod.ACTIONS["construction-time-entry-summary"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
        ))
        assert is_ok(r)
        assert r["employee_count"] == 1
        # Day 1: 8h = 304.00, Day 2: 8*38 + 2*38*1.5 = 304 + 114 = 418
        assert r["grand_total_hours"] == "18.00"
        assert r["grand_total_cost"] == "722.00"

    def test_labor_cost_report(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        call_action(mod.ACTIONS["construction-add-time-entry"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            cost_code_id=None,
            employee_name="Carpenter A", employee_id=None,
            trade="Carpenter", work_date="2026-04-01",
            regular_hours="8", overtime_hours="0", double_time_hours="0",
            hourly_rate="38.00", description=None,
        ))
        call_action(mod.ACTIONS["construction-add-time-entry"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            cost_code_id=None,
            employee_name="Electrician A", employee_id=None,
            trade="Electrician", work_date="2026-04-01",
            regular_hours="8", overtime_hours="0", double_time_hours="0",
            hourly_rate="45.00", description=None,
        ))
        r = call_action(mod.ACTIONS["construction-labor-cost-report"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            start_date=None, end_date=None,
        ))
        assert is_ok(r)
        assert len(r["by_trade"]) == 2
        assert len(r["by_date"]) == 1
        # Carpenter: 8 * 38 = 304, Electrician: 8 * 45 = 360 => total = 664
        assert r["grand_total_cost"] == "664.00"
        assert r["grand_total_hours"] == "16.00"

    def test_labor_cost_report_with_date_filter(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        call_action(mod.ACTIONS["construction-add-time-entry"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            cost_code_id=None,
            employee_name="Filtered Worker", employee_id=None,
            trade="Laborer", work_date="2026-04-01",
            regular_hours="8", overtime_hours="0", double_time_hours="0",
            hourly_rate="22.00", description=None,
        ))
        call_action(mod.ACTIONS["construction-add-time-entry"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            cost_code_id=None,
            employee_name="Filtered Worker", employee_id=None,
            trade="Laborer", work_date="2026-04-15",
            regular_hours="8", overtime_hours="0", double_time_hours="0",
            hourly_rate="22.00", description=None,
        ))
        # Filter to only April 1-10
        r = call_action(mod.ACTIONS["construction-labor-cost-report"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            start_date="2026-04-01", end_date="2026-04-10",
        ))
        assert is_ok(r)
        assert r["grand_total_hours"] == "8.00"
        assert r["grand_total_cost"] == "176.00"
