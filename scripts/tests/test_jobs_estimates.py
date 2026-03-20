"""L1 tests for ConstructClaw -- Jobs & Estimates domains.

Covers: add/update/get/list jobs, cost codes, cost entries, commitments,
        job cost summary, add/update/get/list estimates, estimate lines,
        submit estimate, add/list bids, award bid, compare bids, estimate summary.
"""
import json
import pytest
from construct_helpers import call_action, ns, is_ok, is_error, load_db_query, _uuid


@pytest.fixture
def mod():
    return load_db_query()


# ═══════════════════════════════════════════════════════════════════════════
# JOBS
# ═══════════════════════════════════════════════════════════════════════════

class TestAddJob:
    def test_add_job_success(self, conn, env, mod):
        r = call_action(mod.ACTIONS["construction-add-job"], conn, ns(
            company_id=env["company_id"],
            name="Highway Bridge Project",
            job_type="infrastructure",
            contract_type="lump_sum",
            contract_amount="5000000",
            client_name="State DOT",
            description="Bridge reconstruction",
            project_manager=None, superintendent=None,
            client_id=None, start_date="2026-01-15",
            end_date="2027-06-30", address=None, city=None,
            state=None, zip_code=None, notes=None,
        ))
        assert is_ok(r)
        assert r["job_id"]
        assert r["naming_series"].startswith("CCJOB-")
        assert r["name"] == "Highway Bridge Project"
        assert r["job_status"] == "planning"
        assert r["job_type"] == "infrastructure"

    def test_add_job_missing_company(self, conn, env, mod):
        r = call_action(mod.ACTIONS["construction-add-job"], conn, ns(
            company_id=None, name="Test",
            job_type=None, contract_type=None, contract_amount=None,
            client_name=None, client_id=None, description=None,
            project_manager=None, superintendent=None,
            start_date=None, end_date=None, address=None,
            city=None, state=None, zip_code=None, notes=None,
        ))
        assert is_error(r)

    def test_add_job_missing_name(self, conn, env, mod):
        r = call_action(mod.ACTIONS["construction-add-job"], conn, ns(
            company_id=env["company_id"], name=None,
            job_type=None, contract_type=None, contract_amount=None,
            client_name=None, client_id=None, description=None,
            project_manager=None, superintendent=None,
            start_date=None, end_date=None, address=None,
            city=None, state=None, zip_code=None, notes=None,
        ))
        assert is_error(r)

    def test_add_job_invalid_job_type(self, conn, env, mod):
        r = call_action(mod.ACTIONS["construction-add-job"], conn, ns(
            company_id=env["company_id"], name="Test",
            job_type="bogus", contract_type=None, contract_amount=None,
            client_name=None, client_id=None, description=None,
            project_manager=None, superintendent=None,
            start_date=None, end_date=None, address=None,
            city=None, state=None, zip_code=None, notes=None,
        ))
        assert is_error(r)

    def test_add_job_defaults(self, conn, env, mod):
        """Default job_type=general, contract_type=lump_sum."""
        r = call_action(mod.ACTIONS["construction-add-job"], conn, ns(
            company_id=env["company_id"], name="Simple Job",
            job_type=None, contract_type=None, contract_amount=None,
            client_name=None, client_id=None, description=None,
            project_manager=None, superintendent=None,
            start_date=None, end_date=None, address=None,
            city=None, state=None, zip_code=None, notes=None,
        ))
        assert is_ok(r)
        assert r["job_type"] == "general"


class TestUpdateJob:
    def test_update_job_success(self, conn, env, mod):
        r = call_action(mod.ACTIONS["construction-add-job"], conn, ns(
            company_id=env["company_id"], name="Before",
            job_type=None, contract_type=None, contract_amount=None,
            client_name=None, client_id=None, description=None,
            project_manager=None, superintendent=None,
            start_date=None, end_date=None, address=None,
            city=None, state=None, zip_code=None, notes=None,
        ))
        assert is_ok(r)
        job_id = r["job_id"]

        r2 = call_action(mod.ACTIONS["construction-update-job"], conn, ns(
            job_id=job_id, name="After", description=None,
            client_name=None, client_id=None,
            project_manager=None, superintendent=None,
            contract_amount=None, start_date=None, end_date=None,
            actual_start_date=None, actual_end_date=None,
            address=None, city=None, state=None, zip_code=None,
            percent_complete=None, notes=None,
            job_type=None, contract_type=None, job_status=None,
        ))
        assert is_ok(r2)
        assert "name" in r2["updated_fields"]

    def test_update_job_not_found(self, conn, env, mod):
        r = call_action(mod.ACTIONS["construction-update-job"], conn, ns(
            job_id=_uuid(), name="X", description=None,
            client_name=None, client_id=None,
            project_manager=None, superintendent=None,
            contract_amount=None, start_date=None, end_date=None,
            actual_start_date=None, actual_end_date=None,
            address=None, city=None, state=None, zip_code=None,
            percent_complete=None, notes=None,
            job_type=None, contract_type=None, job_status=None,
        ))
        assert is_error(r)


class TestGetJob:
    def test_get_job_success(self, conn, env, mod):
        r = call_action(mod.ACTIONS["construction-add-job"], conn, ns(
            company_id=env["company_id"], name="Get Test",
            job_type=None, contract_type=None, contract_amount="100000",
            client_name=None, client_id=None, description=None,
            project_manager=None, superintendent=None,
            start_date=None, end_date=None, address=None,
            city=None, state=None, zip_code=None, notes=None,
        ))
        job_id = r["job_id"]

        r2 = call_action(mod.ACTIONS["construction-get-job"], conn, ns(
            job_id=job_id,
        ))
        assert is_ok(r2)
        assert r2["name"] == "Get Test"
        assert r2["contract_amount"] == "100000"


class TestListJobs:
    def test_list_jobs_empty(self, conn, env, mod):
        r = call_action(mod.ACTIONS["construction-list-jobs"], conn, ns(
            company_id=env["company_id"], job_status=None,
            job_type=None, search=None, limit=50, offset=0,
        ))
        assert is_ok(r)
        assert r["total_count"] == 0
        assert r["jobs"] == []

    def test_list_jobs_returns_created(self, conn, env, mod):
        call_action(mod.ACTIONS["construction-add-job"], conn, ns(
            company_id=env["company_id"], name="Job One",
            job_type=None, contract_type=None, contract_amount=None,
            client_name=None, client_id=None, description=None,
            project_manager=None, superintendent=None,
            start_date=None, end_date=None, address=None,
            city=None, state=None, zip_code=None, notes=None,
        ))
        r = call_action(mod.ACTIONS["construction-list-jobs"], conn, ns(
            company_id=env["company_id"], job_status=None,
            job_type=None, search=None, limit=50, offset=0,
        ))
        assert is_ok(r)
        assert r["total_count"] == 1


# ═══════════════════════════════════════════════════════════════════════════
# COST CODES
# ═══════════════════════════════════════════════════════════════════════════

class TestCostCodes:
    def _add_job(self, conn, env, mod):
        r = call_action(mod.ACTIONS["construction-add-job"], conn, ns(
            company_id=env["company_id"], name="CC Job",
            job_type=None, contract_type=None, contract_amount="500000",
            client_name=None, client_id=None, description=None,
            project_manager=None, superintendent=None,
            start_date=None, end_date=None, address=None,
            city=None, state=None, zip_code=None, notes=None,
        ))
        return r["job_id"]

    def test_add_cost_code(self, conn, env, mod):
        job_id = self._add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-cost-code"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            code="01-100", description="General Labor",
            category="labor", budget_amount="50000", budget_hours="500",
        ))
        assert is_ok(r)
        assert r["code"] == "01-100"
        assert r["category"] == "labor"

    def test_add_cost_code_duplicate(self, conn, env, mod):
        job_id = self._add_job(conn, env, mod)
        call_action(mod.ACTIONS["construction-add-cost-code"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            code="01-100", description="Labor",
            category="labor", budget_amount="50000", budget_hours=None,
        ))
        r2 = call_action(mod.ACTIONS["construction-add-cost-code"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            code="01-100", description="Dupe",
            category="labor", budget_amount="10000", budget_hours=None,
        ))
        assert is_error(r2)

    def test_list_cost_codes(self, conn, env, mod):
        job_id = self._add_job(conn, env, mod)
        call_action(mod.ACTIONS["construction-add-cost-code"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            code="01-100", description="Labor",
            category="labor", budget_amount="50000", budget_hours=None,
        ))
        call_action(mod.ACTIONS["construction-add-cost-code"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            code="02-200", description="Materials",
            category="material", budget_amount="30000", budget_hours=None,
        ))
        r = call_action(mod.ACTIONS["construction-list-cost-codes"], conn, ns(
            job_id=job_id, company_id=env["company_id"], category=None,
        ))
        assert is_ok(r)
        assert r["total_count"] == 2


# ═══════════════════════════════════════════════════════════════════════════
# COST ENTRIES
# ═══════════════════════════════════════════════════════════════════════════

class TestCostEntries:
    def _add_job(self, conn, env, mod):
        r = call_action(mod.ACTIONS["construction-add-job"], conn, ns(
            company_id=env["company_id"], name="CE Job",
            job_type=None, contract_type=None, contract_amount="500000",
            client_name=None, client_id=None, description=None,
            project_manager=None, superintendent=None,
            start_date=None, end_date=None, address=None,
            city=None, state=None, zip_code=None, notes=None,
        ))
        return r["job_id"]

    def test_add_cost_entry(self, conn, env, mod):
        job_id = self._add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-cost-entry"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            cost_code_id=None, entry_date="2026-03-01",
            category="material", description="Rebar delivery",
            vendor="Steel Supply Co", reference="INV-001",
            quantity="500", unit_cost="1.50", amount=None,
            hours=None,
        ))
        assert is_ok(r)
        assert r["amount"] == "750.00"  # 500 * 1.50 auto-calculated
        assert r["category"] == "material"

    def test_list_cost_entries(self, conn, env, mod):
        job_id = self._add_job(conn, env, mod)
        call_action(mod.ACTIONS["construction-add-cost-entry"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            cost_code_id=None, entry_date=None,
            category="labor", description="Crew labor",
            vendor=None, reference=None,
            quantity=None, unit_cost=None, amount="5000",
            hours="80",
        ))
        r = call_action(mod.ACTIONS["construction-list-cost-entries"], conn, ns(
            job_id=job_id, company_id=env["company_id"],
            cost_code_id=None, category=None,
            limit=50, offset=0,
        ))
        assert is_ok(r)
        assert r["total_count"] == 1


# ═══════════════════════════════════════════════════════════════════════════
# COMMITMENTS
# ═══════════════════════════════════════════════════════════════════════════

class TestCommitments:
    def _add_job(self, conn, env, mod):
        r = call_action(mod.ACTIONS["construction-add-job"], conn, ns(
            company_id=env["company_id"], name="Commit Job",
            job_type=None, contract_type=None, contract_amount="500000",
            client_name=None, client_id=None, description=None,
            project_manager=None, superintendent=None,
            start_date=None, end_date=None, address=None,
            city=None, state=None, zip_code=None, notes=None,
        ))
        return r["job_id"]

    def test_add_commitment(self, conn, env, mod):
        job_id = self._add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-commitment"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            cost_code_id=None, commitment_type="purchase_order",
            vendor="Lumber Yard", description="Framing lumber",
            original_amount="25000",
        ))
        assert is_ok(r)
        assert r["original_amount"] == "25000"
        assert r["commitment_status"] == "draft"

    def test_update_commitment(self, conn, env, mod):
        job_id = self._add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-commitment"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            cost_code_id=None, commitment_type=None,
            vendor=None, description=None, original_amount="10000",
        ))
        cm_id = r["commitment_id"]

        r2 = call_action(mod.ACTIONS["construction-update-commitment"], conn, ns(
            commitment_id=cm_id, vendor="New Vendor",
            description=None, original_amount=None, revised_amount=None,
            invoiced_amount=None, paid_amount=None, commitment_status="approved",
        ))
        assert is_ok(r2)
        assert "vendor" in r2["updated_fields"]
        assert "commitment_status" in r2["updated_fields"]


# ═══════════════════════════════════════════════════════════════════════════
# JOB COST SUMMARY
# ═══════════════════════════════════════════════════════════════════════════

class TestJobCostSummary:
    def test_job_cost_summary(self, conn, env, mod):
        r = call_action(mod.ACTIONS["construction-add-job"], conn, ns(
            company_id=env["company_id"], name="Summary Job",
            job_type=None, contract_type=None, contract_amount="100000",
            client_name=None, client_id=None, description=None,
            project_manager=None, superintendent=None,
            start_date=None, end_date=None, address=None,
            city=None, state=None, zip_code=None, notes=None,
        ))
        job_id = r["job_id"]

        # Add cost code + entry
        call_action(mod.ACTIONS["construction-add-cost-code"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            code="01-100", description="Labor",
            category="labor", budget_amount="50000", budget_hours=None,
        ))
        r3 = call_action(mod.ACTIONS["construction-job-cost-summary"], conn, ns(
            job_id=job_id,
        ))
        assert is_ok(r3)
        assert r3["total_budget"] == "50000.00"


# ═══════════════════════════════════════════════════════════════════════════
# ESTIMATES
# ═══════════════════════════════════════════════════════════════════════════

class TestEstimates:
    def test_add_estimate(self, conn, env, mod):
        r = call_action(mod.ACTIONS["construction-add-estimate"], conn, ns(
            company_id=env["company_id"], name="Office Renovation Estimate",
            job_id=None, client_name="ABC Corp",
            description="Full office renovation", due_date="2026-04-01",
            markup_pct="15", overhead_pct="10", profit_pct="8",
            notes=None,
        ))
        assert is_ok(r)
        assert r["naming_series"].startswith("CCEST-")
        assert r["estimate_status"] == "draft"

    def test_get_estimate_with_lines(self, conn, env, mod):
        r = call_action(mod.ACTIONS["construction-add-estimate"], conn, ns(
            company_id=env["company_id"], name="Line Test",
            job_id=None, client_name=None,
            description=None, due_date=None,
            markup_pct=None, overhead_pct=None, profit_pct=None,
            notes=None,
        ))
        est_id = r["estimate_id"]

        call_action(mod.ACTIONS["construction-add-estimate-line"], conn, ns(
            company_id=env["company_id"], estimate_id=est_id,
            description="Demolition", category="labor",
            quantity="40", unit_cost="75", amount=None,
            unit=None, notes=None,
        ))
        r2 = call_action(mod.ACTIONS["construction-get-estimate"], conn, ns(
            estimate_id=est_id,
        ))
        assert is_ok(r2)
        assert len(r2["lines"]) == 1
        assert r2["lines"][0]["amount"] == "3000.00"

    def test_update_estimate(self, conn, env, mod):
        r = call_action(mod.ACTIONS["construction-add-estimate"], conn, ns(
            company_id=env["company_id"], name="Updatable",
            job_id=None, client_name=None,
            description=None, due_date=None,
            markup_pct=None, overhead_pct=None, profit_pct=None,
            notes=None,
        ))
        est_id = r["estimate_id"]

        r2 = call_action(mod.ACTIONS["construction-update-estimate"], conn, ns(
            estimate_id=est_id, name="Updated Name",
            client_name=None, description=None, due_date=None,
            markup_pct=None, overhead_pct=None, profit_pct=None,
            notes=None, total_amount=None, estimate_status=None,
        ))
        assert is_ok(r2)
        assert "name" in r2["updated_fields"]

    def test_submit_estimate(self, conn, env, mod):
        r = call_action(mod.ACTIONS["construction-add-estimate"], conn, ns(
            company_id=env["company_id"], name="Submittable",
            job_id=None, client_name=None,
            description=None, due_date=None,
            markup_pct=None, overhead_pct=None, profit_pct=None,
            notes=None,
        ))
        est_id = r["estimate_id"]

        r2 = call_action(mod.ACTIONS["construction-submit-estimate"], conn, ns(
            estimate_id=est_id,
        ))
        assert is_ok(r2)
        assert r2["estimate_status"] == "submitted"

    def test_submit_estimate_already_submitted(self, conn, env, mod):
        r = call_action(mod.ACTIONS["construction-add-estimate"], conn, ns(
            company_id=env["company_id"], name="Double Submit",
            job_id=None, client_name=None,
            description=None, due_date=None,
            markup_pct=None, overhead_pct=None, profit_pct=None,
            notes=None,
        ))
        est_id = r["estimate_id"]
        call_action(mod.ACTIONS["construction-submit-estimate"], conn, ns(
            estimate_id=est_id,
        ))
        r2 = call_action(mod.ACTIONS["construction-submit-estimate"], conn, ns(
            estimate_id=est_id,
        ))
        assert is_error(r2)


class TestEstimateLines:
    def _add_estimate(self, conn, env, mod):
        r = call_action(mod.ACTIONS["construction-add-estimate"], conn, ns(
            company_id=env["company_id"], name="EL Test",
            job_id=None, client_name=None,
            description=None, due_date=None,
            markup_pct=None, overhead_pct=None, profit_pct=None,
            notes=None,
        ))
        return r["estimate_id"]

    def test_add_estimate_line_auto_amount(self, conn, env, mod):
        est_id = self._add_estimate(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-estimate-line"], conn, ns(
            company_id=env["company_id"], estimate_id=est_id,
            description="Framing labor", category="labor",
            quantity="100", unit_cost="45.00", amount=None,
            unit="hr", notes=None,
        ))
        assert is_ok(r)
        assert r["amount"] == "4500.00"
        assert r["line_number"] == 1

    def test_list_estimate_lines(self, conn, env, mod):
        est_id = self._add_estimate(conn, env, mod)
        call_action(mod.ACTIONS["construction-add-estimate-line"], conn, ns(
            company_id=env["company_id"], estimate_id=est_id,
            description="Item 1", category="labor",
            quantity="10", unit_cost="50", amount=None,
            unit=None, notes=None,
        ))
        call_action(mod.ACTIONS["construction-add-estimate-line"], conn, ns(
            company_id=env["company_id"], estimate_id=est_id,
            description="Item 2", category="material",
            quantity="20", unit_cost="25", amount=None,
            unit=None, notes=None,
        ))
        r = call_action(mod.ACTIONS["construction-list-estimate-lines"], conn, ns(
            estimate_id=est_id,
        ))
        assert is_ok(r)
        assert r["total_count"] == 2
        assert r["lines"][0]["line_number"] == 1
        assert r["lines"][1]["line_number"] == 2


class TestEstimateSummary:
    def test_estimate_summary_with_markup(self, conn, env, mod):
        r = call_action(mod.ACTIONS["construction-add-estimate"], conn, ns(
            company_id=env["company_id"], name="Markup Test",
            job_id=None, client_name=None,
            description=None, due_date=None,
            markup_pct="10", overhead_pct="5", profit_pct="15",
            notes=None,
        ))
        est_id = r["estimate_id"]

        # Add a line: 100 qty * $10 = $1000
        call_action(mod.ACTIONS["construction-add-estimate-line"], conn, ns(
            company_id=env["company_id"], estimate_id=est_id,
            description="Basic work", category="labor",
            quantity="100", unit_cost="10", amount=None,
            unit=None, notes=None,
        ))

        r2 = call_action(mod.ACTIONS["construction-estimate-summary"], conn, ns(
            estimate_id=est_id,
        ))
        assert is_ok(r2)
        d = r2
        assert d["base_cost"] == "1000.00"
        assert d["overhead_amount"] == "50.00"   # 5% of 1000
        assert d["markup_amount"] == "100.00"    # 10% of 1000
        # subtotal = 1000 + 50 + 100 = 1150
        # profit = 15% of 1150 = 172.50
        assert d["profit_amount"] == "172.50"
        # grand_total = 1150 + 172.50 = 1322.50
        assert d["grand_total"] == "1322.50"


# ═══════════════════════════════════════════════════════════════════════════
# BIDS
# ═══════════════════════════════════════════════════════════════════════════

class TestBids:
    def test_add_bid(self, conn, env, mod):
        r = call_action(mod.ACTIONS["construction-add-bid"], conn, ns(
            company_id=env["company_id"],
            bidder_name="Alpha Plumbing",
            estimate_id=None, job_id=None,
            bid_amount="125000",
            scope_description="Full plumbing package",
            exclusions="Fire suppression",
            notes=None,
        ))
        assert is_ok(r)
        assert r["naming_series"].startswith("CCBID-")
        assert r["bid_status"] == "submitted"

    def test_add_bid_missing_bidder(self, conn, env, mod):
        r = call_action(mod.ACTIONS["construction-add-bid"], conn, ns(
            company_id=env["company_id"],
            bidder_name=None,
            estimate_id=None, job_id=None,
            bid_amount=None, scope_description=None,
            exclusions=None, notes=None,
        ))
        assert is_error(r)

    def test_award_bid(self, conn, env, mod):
        r = call_action(mod.ACTIONS["construction-add-bid"], conn, ns(
            company_id=env["company_id"],
            bidder_name="Beta Electric",
            estimate_id=None, job_id=None,
            bid_amount="50000",
            scope_description=None, exclusions=None, notes=None,
        ))
        bid_id = r["bid_id"]

        r2 = call_action(mod.ACTIONS["construction-award-bid"], conn, ns(
            bid_id=bid_id,
        ))
        assert is_ok(r2)
        assert r2["bid_status"] == "awarded"

    def test_compare_bids(self, conn, env, mod):
        # Add a job so we can link bids
        jr = call_action(mod.ACTIONS["construction-add-job"], conn, ns(
            company_id=env["company_id"], name="Bid Comparison Job",
            job_type=None, contract_type=None, contract_amount=None,
            client_name=None, client_id=None, description=None,
            project_manager=None, superintendent=None,
            start_date=None, end_date=None, address=None,
            city=None, state=None, zip_code=None, notes=None,
        ))
        job_id = jr["job_id"]

        call_action(mod.ACTIONS["construction-add-bid"], conn, ns(
            company_id=env["company_id"], bidder_name="Low Bidder",
            estimate_id=None, job_id=job_id, bid_amount="100000",
            scope_description=None, exclusions=None, notes=None,
        ))
        call_action(mod.ACTIONS["construction-add-bid"], conn, ns(
            company_id=env["company_id"], bidder_name="High Bidder",
            estimate_id=None, job_id=job_id, bid_amount="150000",
            scope_description=None, exclusions=None, notes=None,
        ))

        r = call_action(mod.ACTIONS["construction-compare-bids"], conn, ns(
            estimate_id=None, job_id=job_id,
        ))
        assert is_ok(r)
        assert r["total_count"] == 2
        assert r["lowest_bid"] == "100000.00"
        assert r["highest_bid"] == "150000.00"
        # First bid should have 0 spread
        assert r["bids"][0]["spread_from_low"] == "0.00"
