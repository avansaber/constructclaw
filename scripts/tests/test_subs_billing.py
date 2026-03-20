"""L1 tests for ConstructClaw -- Subcontractors & Billing domains.

Covers: subcontracts, subcontract lines, approve subcontract,
        pay applications, lien waivers,
        schedule of values, SOV lines, progress bills, retention.
"""
import pytest
from construct_helpers import call_action, ns, is_ok, is_error, load_db_query, _uuid


@pytest.fixture
def mod():
    return load_db_query()


def _add_job(conn, env, mod, name="Sub/Bill Job", contract_amount="1000000"):
    r = call_action(mod.ACTIONS["construction-add-job"], conn, ns(
        company_id=env["company_id"], name=name,
        job_type=None, contract_type=None, contract_amount=contract_amount,
        client_name=None, client_id=env["customer_id"], description=None,
        project_manager=None, superintendent=None,
        start_date=None, end_date=None, address=None,
        city=None, state=None, zip_code=None, notes=None,
    ))
    assert is_ok(r)
    return r["job_id"]


# ═══════════════════════════════════════════════════════════════════════════
# SUBCONTRACTS
# ═══════════════════════════════════════════════════════════════════════════

class TestSubcontracts:
    def test_add_subcontract(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-subcontract"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            subcontractor_name="Elite Electrical",
            trade="electrical", scope_of_work="Full electrical fit-out",
            original_amount="250000", retention_pct="10",
            insurance_expiry="2027-01-01", license_number="EL-12345",
            start_date="2026-04-01", end_date="2026-12-31",
            notes=None,
        ))
        assert is_ok(r)
        assert r["naming_series"].startswith("CCSUB-")
        assert r["subcontract_status"] == "draft"
        assert r["subcontractor_name"] == "Elite Electrical"

    def test_add_subcontract_missing_name(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-subcontract"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            subcontractor_name=None,
            trade=None, scope_of_work=None,
            original_amount=None, retention_pct=None,
            insurance_expiry=None, license_number=None,
            start_date=None, end_date=None, notes=None,
        ))
        assert is_error(r)

    def test_approve_subcontract(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-subcontract"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            subcontractor_name="Plumbing Pro",
            trade="plumbing", scope_of_work=None,
            original_amount="150000", retention_pct=None,
            insurance_expiry=None, license_number=None,
            start_date=None, end_date=None, notes=None,
        ))
        sub_id = r["subcontract_id"]

        r2 = call_action(mod.ACTIONS["construction-approve-subcontract"], conn, ns(
            subcontract_id=sub_id,
        ))
        assert is_ok(r2)
        assert r2["subcontract_status"] == "approved"

    def test_approve_subcontract_bad_status(self, conn, env, mod):
        """Cannot approve an already-approved subcontract."""
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-subcontract"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            subcontractor_name="Dupe",
            trade=None, scope_of_work=None,
            original_amount="50000", retention_pct=None,
            insurance_expiry=None, license_number=None,
            start_date=None, end_date=None, notes=None,
        ))
        sub_id = r["subcontract_id"]
        call_action(mod.ACTIONS["construction-approve-subcontract"], conn, ns(
            subcontract_id=sub_id,
        ))
        r2 = call_action(mod.ACTIONS["construction-approve-subcontract"], conn, ns(
            subcontract_id=sub_id,
        ))
        assert is_error(r2)

    def test_get_subcontract(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-subcontract"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            subcontractor_name="Getter",
            trade="concrete", scope_of_work=None,
            original_amount="100000", retention_pct=None,
            insurance_expiry=None, license_number=None,
            start_date=None, end_date=None, notes=None,
        ))
        sub_id = r["subcontract_id"]

        r2 = call_action(mod.ACTIONS["construction-get-subcontract"], conn, ns(
            subcontract_id=sub_id,
        ))
        assert is_ok(r2)
        assert r2["subcontractor_name"] == "Getter"
        assert "lines" in r2

    def test_list_subcontracts(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        call_action(mod.ACTIONS["construction-add-subcontract"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            subcontractor_name="Sub 1", trade="electrical", scope_of_work=None,
            original_amount="100000", retention_pct=None,
            insurance_expiry=None, license_number=None,
            start_date=None, end_date=None, notes=None,
        ))
        r = call_action(mod.ACTIONS["construction-list-subcontracts"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            subcontract_status=None, search=None,
            limit=50, offset=0,
        ))
        assert is_ok(r)
        assert r["total_count"] == 1


# ═══════════════════════════════════════════════════════════════════════════
# PAY APPLICATIONS
# ═══════════════════════════════════════════════════════════════════════════

class TestPayApplications:
    def _setup(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-subcontract"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            subcontractor_name="PA Sub", trade="hvac", scope_of_work=None,
            original_amount="200000", retention_pct="10",
            insurance_expiry=None, license_number=None,
            start_date=None, end_date=None, notes=None,
        ))
        return job_id, r["subcontract_id"]

    def test_add_pay_application(self, conn, env, mod):
        job_id, sub_id = self._setup(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-pay-application"], conn, ns(
            company_id=env["company_id"], subcontract_id=sub_id,
            work_completed="50000", materials_stored="5000",
            period_from="2026-03-01", period_to="2026-03-31",
            notes=None,
        ))
        assert is_ok(r)
        d = r
        assert d["application_number"] == 1
        assert d["total_earned"] == "55000.00"
        # retention = 10% of 55000 = 5500
        assert d["retention_held"] == "5500.00"
        # current_due = 55000 - 5500 - 0 (previous) = 49500
        assert d["current_payment_due"] == "49500.00"
        assert d["pay_app_status"] == "draft"

    def test_approve_pay_application(self, conn, env, mod):
        job_id, sub_id = self._setup(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-pay-application"], conn, ns(
            company_id=env["company_id"], subcontract_id=sub_id,
            work_completed="30000", materials_stored="0",
            period_from=None, period_to=None, notes=None,
        ))
        pa_id = r["pay_application_id"]

        r2 = call_action(mod.ACTIONS["construction-approve-pay-application"], conn, ns(
            pay_application_id=pa_id,
        ))
        assert is_ok(r2)
        assert r2["pay_app_status"] == "approved"

    def test_reject_pay_application(self, conn, env, mod):
        job_id, sub_id = self._setup(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-pay-application"], conn, ns(
            company_id=env["company_id"], subcontract_id=sub_id,
            work_completed="20000", materials_stored="0",
            period_from=None, period_to=None, notes=None,
        ))
        pa_id = r["pay_application_id"]

        r2 = call_action(mod.ACTIONS["construction-reject-pay-application"], conn, ns(
            pay_application_id=pa_id, notes="Documentation incomplete",
        ))
        assert is_ok(r2)
        assert r2["pay_app_status"] == "rejected"


# ═══════════════════════════════════════════════════════════════════════════
# LIEN WAIVERS
# ═══════════════════════════════════════════════════════════════════════════

class TestLienWaivers:
    def test_add_lien_waiver(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-subcontract"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            subcontractor_name="Waiver Sub", trade="concrete",
            scope_of_work=None, original_amount="100000",
            retention_pct=None, insurance_expiry=None,
            license_number=None, start_date=None, end_date=None,
            notes=None,
        ))
        sub_id = r["subcontract_id"]

        r2 = call_action(mod.ACTIONS["construction-add-lien-waiver"], conn, ns(
            company_id=env["company_id"], subcontract_id=sub_id,
            pay_application_id=None, waiver_type="conditional_progress",
            amount="25000", through_date="2026-03-31",
            received_date="2026-04-02", notes=None,
        ))
        assert is_ok(r2)
        assert r2["waiver_type"] == "conditional_progress"
        assert r2["waiver_status"] == "pending"

    def test_list_lien_waivers(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-subcontract"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            subcontractor_name="LW Sub", trade=None,
            scope_of_work=None, original_amount="50000",
            retention_pct=None, insurance_expiry=None,
            license_number=None, start_date=None, end_date=None,
            notes=None,
        ))
        sub_id = r["subcontract_id"]
        call_action(mod.ACTIONS["construction-add-lien-waiver"], conn, ns(
            company_id=env["company_id"], subcontract_id=sub_id,
            pay_application_id=None, waiver_type="conditional_progress",
            amount="10000", through_date=None,
            received_date=None, notes=None,
        ))
        r2 = call_action(mod.ACTIONS["construction-list-lien-waivers"], conn, ns(
            subcontract_id=sub_id, company_id=env["company_id"],
        ))
        assert is_ok(r2)
        assert r2["total_count"] == 1


# ═══════════════════════════════════════════════════════════════════════════
# SCHEDULE OF VALUES + PROGRESS BILLING
# ═══════════════════════════════════════════════════════════════════════════

class TestBilling:
    def test_add_schedule_of_values(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-schedule-of-values"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            name="Main SOV", total_contract="1000000", notes=None,
        ))
        assert is_ok(r)
        assert r["naming_series"].startswith("CCSOV-")
        assert r["sov_status"] == "draft"

    def test_add_sov_line(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-schedule-of-values"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            name="SOV with Lines", total_contract="500000", notes=None,
        ))
        sov_id = r["sov_id"]

        r2 = call_action(mod.ACTIONS["construction-add-sov-line"], conn, ns(
            company_id=env["company_id"], sov_id=sov_id,
            description="Foundations", item_number="1",
            scheduled_value="100000", retention_pct="10",
        ))
        assert is_ok(r2)
        assert r2["scheduled_value"] == "100000"

    def test_add_progress_bill(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-progress-bill"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            sov_id=None, total_completed="200000",
            total_retention="20000", period_from="2026-03-01",
            period_to="2026-03-31", notes=None,
        ))
        assert is_ok(r)
        d = r
        assert d["bill_number"] == 1
        assert d["bill_status"] == "draft"
        # current_due = 200000 - 20000 - 0 = 180000
        assert d["current_due"] == "180000.00"

    def test_submit_progress_bill(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-progress-bill"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            sov_id=None, total_completed="100000",
            total_retention="10000", period_from=None,
            period_to=None, notes=None,
        ))
        pb_id = r["progress_bill_id"]

        r2 = call_action(mod.ACTIONS["construction-submit-progress-bill"], conn, ns(
            progress_bill_id=pb_id,
        ))
        assert is_ok(r2)
        assert r2["bill_status"] == "submitted"


# ═══════════════════════════════════════════════════════════════════════════
# RETENTION
# ═══════════════════════════════════════════════════════════════════════════

class TestRetention:
    def test_add_retention(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-retention"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            subcontract_id=None, retention_type="owner",
            amount_held="50000", notes=None,
        ))
        assert is_ok(r)
        assert r["amount_held"] == "50000"
        assert r["retention_status"] == "held"

    def test_release_retention_full(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-retention"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            subcontract_id=None, retention_type="owner",
            amount_held="30000", notes=None,
        ))
        ret_id = r["retention_id"]

        r2 = call_action(mod.ACTIONS["construction-release-retention"], conn, ns(
            retention_id=ret_id, release_amount=None,
        ))
        assert is_ok(r2)
        assert r2["retention_status"] == "released"
        assert r2["new_balance"] == "0.00"
        assert r2["released_amount"] == "30000.00"

    def test_release_retention_partial(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-retention"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            subcontract_id=None, retention_type="owner",
            amount_held="40000", notes=None,
        ))
        ret_id = r["retention_id"]

        r2 = call_action(mod.ACTIONS["construction-release-retention"], conn, ns(
            retention_id=ret_id, release_amount="15000",
        ))
        assert is_ok(r2)
        assert r2["retention_status"] == "partial_release"
        assert r2["new_balance"] == "25000.00"

    def test_release_retention_exceeds_balance(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-retention"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            subcontract_id=None, retention_type="owner",
            amount_held="10000", notes=None,
        ))
        ret_id = r["retention_id"]

        r2 = call_action(mod.ACTIONS["construction-release-retention"], conn, ns(
            retention_id=ret_id, release_amount="20000",
        ))
        assert is_error(r2)

    def test_list_retentions(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        call_action(mod.ACTIONS["construction-add-retention"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            subcontract_id=None, retention_type="owner",
            amount_held="50000", notes=None,
        ))
        r = call_action(mod.ACTIONS["construction-list-retentions"], conn, ns(
            job_id=job_id, company_id=env["company_id"],
            retention_status=None,
        ))
        assert is_ok(r)
        assert r["total_count"] == 1
