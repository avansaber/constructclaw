"""L1 depth tests for ConstructClaw -- read-only gets, lists and job reports.

Covers the twelve actions that previously had only routability coverage:
  construction-get-rfi, construction-get-schedule-of-values,
  construction-job-profitability, construction-job-status-report,
  construction-list-bids, construction-list-ccos, construction-list-commitments,
  construction-list-daily-materials, construction-list-daily-reports,
  construction-list-drawings, construction-list-earned-values,
  construction-list-estimates.

Each test seeds through the owning module's own write actions, calls the read
action, and pins the response against rows read back from the database with
exact string comparisons (money is TEXT; expectations are built with Decimal,
never float, never round). Every action also has a refusal/read-only case
proving the database is byte-identical afterwards.

No handler here posts to the general ledger: these twelve actions are pure
reads (SELECT only, no audit rows), so there are no debit/credit legs to assert
and none is asserted below. A later reader must not add ledger assertions here.
"""
import sqlite3
from decimal import Decimal, ROUND_HALF_UP

import pytest
from construct_helpers import (
    call_action, is_error, is_ok, load_db_query, ns,
    seed_company, seed_naming_series,
)


@pytest.fixture
def mod():
    return load_db_query()


SNAPSHOT_TABLES = (
    "constructclaw_job",
    "constructclaw_rfi",
    "constructclaw_schedule_of_values",
    "constructclaw_sov_line",
    "constructclaw_estimate",
    "constructclaw_bid",
    "constructclaw_cco",
    "constructclaw_commitment",
    "constructclaw_daily_report",
    "constructclaw_daily_material",
    "constructclaw_earned_value",
    "constructclaw_cost_entry",
    "constructclaw_progress_bill",
    "audit_log",
)


def _snapshot(conn):
    """Byte-level picture of every table these reads could touch."""
    snap = {}
    for table in SNAPSHOT_TABLES:
        snap[table] = [tuple(r) for r in conn.execute(
            "SELECT * FROM %s ORDER BY id" % table).fetchall()]
    return snap


# ── seed helpers (all write through the owning module's own actions) ────────

def _job(conn, env, mod, name="Depth Job", amount="100000.00"):
    r = call_action(mod.ACTIONS["construction-add-job"], conn, ns(
        company_id=env["company_id"], name=name,
        job_type=None, contract_type=None, contract_amount=amount,
        client_name=None, client_id=None, description=None,
        project_manager=None, superintendent=None,
        start_date=None, end_date=None, address=None,
        city=None, state=None, zip_code=None, notes=None))
    assert is_ok(r), r
    return r["job_id"]


def _rfi(conn, env, mod, job_id):
    r = call_action(mod.ACTIONS["construction-add-rfi"], conn, ns(
        company_id=env["company_id"], job_id=job_id,
        subject="Clarify footing depth", question="What is the footing depth at grid B?",
        initiated_by=None, assigned_to=None, priority="high",
        date_required="2026-05-01", cost_impact="250.00",
        schedule_impact_days=None, notes=None))
    assert is_ok(r), r
    return r["rfi_id"]


def _sov(conn, env, mod, job_id, name="Site Works SOV", total="100000.00"):
    r = call_action(mod.ACTIONS["construction-add-schedule-of-values"], conn, ns(
        company_id=env["company_id"], job_id=job_id, name=name,
        total_contract=total, notes=None))
    assert is_ok(r), r
    return r["sov_id"]


def _sov_line(conn, env, mod, sov_id, item="1", desc="Mobilization",
              value="10000.00", retention="10"):
    r = call_action(mod.ACTIONS["construction-add-sov-line"], conn, ns(
        company_id=env["company_id"], sov_id=sov_id, item_number=item,
        description=desc, scheduled_value=value, retention_pct=retention))
    assert is_ok(r), r
    return r["sov_line_id"]


def _rfi_row(conn, rfi_id):
    return conn.execute(
        "SELECT job_id, subject, question, priority, cost_impact, "
        "schedule_impact_days, rfi_status, company_id "
        "FROM constructclaw_rfi WHERE id = ?", (rfi_id,)).fetchone()


# ═══════════════════════════════════════════════════════════════════════════
# construction-get-rfi (stored-row assertion)
# ═══════════════════════════════════════════════════════════════════════════

def test_get_rfi_returns_the_stored_row(conn, env, mod):
    job_id = _job(conn, env, mod)
    rfi_id = _rfi(conn, env, mod, job_id)
    before = _snapshot(conn)

    r = call_action(mod.ACTIONS["construction-get-rfi"], conn, ns(rfi_id=rfi_id))
    assert is_ok(r), r
    assert (r["subject"], r["question"], r["priority"], r["cost_impact"],
            r["rfi_status"], r["job_id"], r["company_id"]) == (
        "Clarify footing depth", "What is the footing depth at grid B?",
        "high", "250.00", "open", job_id, env["company_id"])
    assert r["date_required"] == "2026-05-01"
    assert tuple(_rfi_row(conn, rfi_id)) == (
        job_id, "Clarify footing depth", "What is the footing depth at grid B?",
        "high", "250.00", 0, "open", env["company_id"])
    # A get writes nothing, not even an audit row.
    assert _snapshot(conn) == before


def test_get_rfi_refusals_leave_the_database_untouched(conn, env, mod):
    job_id = _job(conn, env, mod)
    rfi_id = _rfi(conn, env, mod, job_id)
    before = _snapshot(conn)
    get = mod.ACTIONS["construction-get-rfi"]

    r = call_action(get, conn, ns(rfi_id=None))
    assert is_error(r)
    assert r["message"] == "--rfi-id is required"

    r = call_action(get, conn, ns(rfi_id="no-such-rfi"))
    assert is_error(r)
    assert r["message"] == "RFI no-such-rfi not found"

    assert tuple(_rfi_row(conn, rfi_id)) == (
        job_id, "Clarify footing depth", "What is the footing depth at grid B?",
        "high", "250.00", 0, "open", env["company_id"])
    assert _snapshot(conn) == before


# ═══════════════════════════════════════════════════════════════════════════
# construction-get-schedule-of-values (stored-row assertion)
# ═══════════════════════════════════════════════════════════════════════════

def test_get_schedule_of_values_returns_header_and_lines(conn, env, mod):
    job_id = _job(conn, env, mod)
    sov_id = _sov(conn, env, mod, job_id)
    line_a = _sov_line(conn, env, mod, sov_id, "1", "Mobilization", "10000.00", "10")
    line_b = _sov_line(conn, env, mod, sov_id, "2", "Earthworks", "25000.50", "5")
    bare_id = _sov(conn, env, mod, job_id, name="Bare SOV")
    before = _snapshot(conn)

    r = call_action(mod.ACTIONS["construction-get-schedule-of-values"], conn,
                    ns(sov_id=sov_id))
    assert is_ok(r), r
    assert (r["job_id"], r["name"], r["total_contract"], r["revised_contract"],
            r["sov_status"], r["company_id"]) == (
        job_id, "Site Works SOV", "100000.00", "100000.00",
        "draft", env["company_id"])
    assert [(l["id"], l["item_number"], l["description"], l["scheduled_value"],
             l["balance_to_finish"], l["retention_pct"]) for l in r["lines"]] == [
        (line_a, "1", "Mobilization", "10000.00", "10000.00", "10"),
        (line_b, "2", "Earthworks", "25000.50", "25000.50", "5"),
    ]
    assert [tuple(x) for x in conn.execute(
        "SELECT id, item_number, description, scheduled_value, "
        "balance_to_finish, retention_pct FROM constructclaw_sov_line "
        "WHERE sov_id = ? ORDER BY item_number", (sov_id,)).fetchall()] == [
        (line_a, "1", "Mobilization", "10000.00", "10000.00", "10"),
        (line_b, "2", "Earthworks", "25000.50", "25000.50", "5"),
    ]
    assert tuple(conn.execute(
        "SELECT job_id, name, total_contract, revised_contract, sov_status "
        "FROM constructclaw_schedule_of_values WHERE id = ?",
        (sov_id,)).fetchone()) == (
        job_id, "Site Works SOV", "100000.00", "100000.00", "draft")

    # An SOV with no lines reports an empty line list, not an error.
    r = call_action(mod.ACTIONS["construction-get-schedule-of-values"], conn,
                    ns(sov_id=bare_id))
    assert is_ok(r), r
    assert r["lines"] == []
    assert _snapshot(conn) == before


def test_get_schedule_of_values_refusals_write_nothing(conn, env, mod):
    job_id = _job(conn, env, mod)
    sov_id = _sov(conn, env, mod, job_id)
    _sov_line(conn, env, mod, sov_id)
    before = _snapshot(conn)
    get = mod.ACTIONS["construction-get-schedule-of-values"]

    r = call_action(get, conn, ns(sov_id=None))
    assert is_error(r)
    assert r["message"] == "--sov-id is required"

    r = call_action(get, conn, ns(sov_id="no-such-sov"))
    assert is_error(r)
    assert r["message"] == "Schedule of values no-such-sov not found"

    assert _snapshot(conn) == before


# ═══════════════════════════════════════════════════════════════════════════
# construction-job-profitability (computed-over-stored-rows assertion)
# ═══════════════════════════════════════════════════════════════════════════

def _cost_entry(conn, env, mod, job_id, amount, category="material"):
    r = call_action(mod.ACTIONS["construction-add-cost-entry"], conn, ns(
        company_id=env["company_id"], job_id=job_id, cost_code_id=None,
        entry_date="2026-04-15", category=category, description="Depth cost",
        vendor=None, reference=None, quantity="0", unit_cost="0",
        amount=amount, hours="0"))
    assert is_ok(r), r
    return r["cost_entry_id"]


def _cco(conn, env, mod, job_id, title, cost):
    r = call_action(mod.ACTIONS["construction-add-cco"], conn, ns(
        company_id=env["company_id"], job_id=job_id, pco_id=None,
        title=title, description=None, cost_change=cost,
        time_change_days=None, notes=None))
    assert is_ok(r), r
    return r["cco_id"]


def _progress_bill(conn, env, mod, job_id, completed, retention,
                   period_from="2026-04-01", period_to="2026-04-30"):
    r = call_action(mod.ACTIONS["construction-add-progress-bill"], conn, ns(
        company_id=env["company_id"], job_id=job_id, sov_id=None,
        total_completed=completed, total_retention=retention,
        period_from=period_from, period_to=period_to, notes=None))
    assert is_ok(r), r
    return r["progress_bill_id"]


def test_job_profitability_foots_costs_change_orders_and_bills(conn, env, mod):
    job_id = _job(conn, env, mod, amount="100000.00")
    _cost_entry(conn, env, mod, job_id, "12000.50")
    _cost_entry(conn, env, mod, job_id, "3250.25", category="labor")
    approved = _cco(conn, env, mod, job_id, "Extra footing", "5000.00")
    assert is_ok(call_action(mod.ACTIONS["construction-approve-cco"], conn,
                             ns(cco_id=approved, approved_by="Owner")))
    draft = _cco(conn, env, mod, job_id, "Unapproved extra", "9999.99")
    bill = _progress_bill(conn, env, mod, job_id, "20000.00", "2000.00")
    rejected = _progress_bill(conn, env, mod, job_id, "30000.00", "3000.00",
                              "2026-05-01", "2026-05-31")
    # No action moves a progress bill to rejected; seed the status directly,
    # the same way the billing behaviour suite does.
    conn.execute("UPDATE constructclaw_progress_bill SET bill_status = ? "
                 "WHERE id = ?", ("rejected", rejected))
    conn.commit()
    before = _snapshot(conn)

    assert tuple(conn.execute(
        "SELECT current_due FROM constructclaw_progress_bill WHERE id = ?",
        (bill,)).fetchone()) == ("18000.00",)

    r = call_action(mod.ACTIONS["construction-job-profitability"], conn,
                    ns(job_id=job_id))
    assert is_ok(r), r
    gross = Decimal("105000.00") - Decimal("15250.75")
    margin = (gross / Decimal("105000.00") * Decimal("100")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)
    assert (r["job_name"], r["original_contract"], r["change_orders"],
            r["revised_contract"], r["total_cost"], r["gross_profit"],
            r["margin_pct"], r["total_billed"]) == (
        "Depth Job", "100000.00", "5000.00", "105000.00", "15250.75",
        str(gross), str(margin), "18000.00")
    assert str(margin) == "85.48"
    # The draft CCO and the rejected bill are excluded from the footing.
    assert tuple(conn.execute(
        "SELECT cco_status, cost_change FROM constructclaw_cco WHERE id = ?",
        (draft,)).fetchone()) == ("draft", "9999.99")
    assert _snapshot(conn) == before


def test_job_profitability_refusals_write_nothing(conn, env, mod):
    job_id = _job(conn, env, mod)
    _cost_entry(conn, env, mod, job_id, "100.00")
    before = _snapshot(conn)
    action = mod.ACTIONS["construction-job-profitability"]

    r = call_action(action, conn, ns(job_id=None))
    assert is_error(r)
    assert r["message"] == "--job-id is required"

    r = call_action(action, conn, ns(job_id="no-such-job"))
    assert is_error(r)
    assert r["message"] == "Job no-such-job not found"

    assert _snapshot(conn) == before


# ═══════════════════════════════════════════════════════════════════════════
# construction-job-status-report (computed-over-stored-rows assertion)
# ═══════════════════════════════════════════════════════════════════════════

def test_job_status_report_costs_each_job_and_scopes_by_company(conn, env, mod):
    job_a = _job(conn, env, mod, name="Alpha Tower", amount="100000.00")
    _cost_entry(conn, env, mod, job_a, "12000.50")
    _cost_entry(conn, env, mod, job_a, "3250.25", category="labor")
    job_b = _job(conn, env, mod, name="Beta Shed", amount="50000.00")

    other_company = seed_company(conn)
    seed_naming_series(conn, other_company)
    other_job = call_action(mod.ACTIONS["construction-add-job"], conn, ns(
        company_id=other_company, name="Other Co Job",
        job_type=None, contract_type=None, contract_amount="70000.00",
        client_name=None, client_id=None, description=None,
        project_manager=None, superintendent=None,
        start_date=None, end_date=None, address=None,
        city=None, state=None, zip_code=None, notes=None))
    assert is_ok(other_job), other_job
    before = _snapshot(conn)

    r = call_action(mod.ACTIONS["construction-job-status-report"], conn,
                    ns(company_id=env["company_id"]))
    assert is_ok(r), r
    assert r["total_count"] == 2
    assert r["company_id"] == env["company_id"]
    by_id = {j["job_id"]: j for j in r["jobs"]}
    assert set(by_id) == {job_a, job_b}
    assert (by_id[job_a]["name"], by_id[job_a]["contract_amount"],
            by_id[job_a]["total_cost"], by_id[job_a]["job_status"]) == (
        "Alpha Tower", "100000.00", "15250.75", "planning")
    assert (by_id[job_b]["name"], by_id[job_b]["contract_amount"],
            by_id[job_b]["total_cost"]) == ("Beta Shed", "50000.00", "0.00")
    # Costs read back from the ledger of cost entries agree with the report.
    cost_check = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(CAST(amount AS NUMERIC)), 0) "
        "FROM constructclaw_cost_entry WHERE job_id = ?",
        (job_a,)).fetchone()
    assert cost_check[0] == 2
    assert Decimal(str(cost_check[1])) == Decimal("15250.75")
    # The other company's job is out of scope.
    assert other_job["job_id"] not in by_id

    r = call_action(mod.ACTIONS["construction-job-status-report"], conn,
                    ns(company_id=other_company))
    assert is_ok(r), r
    assert [j["job_id"] for j in r["jobs"]] == [other_job["job_id"]]
    assert _snapshot(conn) == before


def test_job_status_report_refusal_writes_nothing(conn, env, mod):
    _job(conn, env, mod)
    before = _snapshot(conn)

    r = call_action(mod.ACTIONS["construction-job-status-report"], conn,
                    ns(company_id=None))
    assert is_error(r)
    assert r["message"] == "--company-id is required"

    # An unknown company is in scope of the query but owns no jobs.
    r = call_action(mod.ACTIONS["construction-job-status-report"], conn,
                    ns(company_id="no-such-company"))
    assert is_ok(r), r
    assert (r["total_count"], r["jobs"]) == (0, [])
    assert _snapshot(conn) == before


# ═══════════════════════════════════════════════════════════════════════════
# construction-list-bids (stored-row assertion)
# ═══════════════════════════════════════════════════════════════════════════

def _estimate(conn, env, mod, job_id, name="Depth Estimate"):
    r = call_action(mod.ACTIONS["construction-add-estimate"], conn, ns(
        company_id=env["company_id"], job_id=job_id, name=name,
        client_name=None, description=None, due_date=None,
        markup_pct=None, overhead_pct=None, profit_pct=None, notes=None))
    assert is_ok(r), r
    return r["estimate_id"]


def _bid(conn, env, mod, estimate_id, job_id, bidder, amount):
    r = call_action(mod.ACTIONS["construction-add-bid"], conn, ns(
        company_id=env["company_id"], estimate_id=estimate_id, job_id=job_id,
        bidder_name=bidder, bid_amount=amount, scope_description=None,
        exclusions=None, notes=None))
    assert is_ok(r), r
    return r["bid_id"]


def _bid_rows(conn, where, params):
    return [tuple(r) for r in conn.execute(
        "SELECT id, estimate_id, job_id, bidder_name, bid_amount, bid_status, "
        "company_id FROM constructclaw_bid " + where + " ORDER BY bidder_name",
        params).fetchall()]


def test_list_bids_returns_stored_amounts_and_filters(conn, env, mod):
    job_id = _job(conn, env, mod)
    est_id = _estimate(conn, env, mod, job_id)
    bid_a = _bid(conn, env, mod, est_id, job_id, "Alpha Builders", "50000.00")
    bid_b = _bid(conn, env, mod, est_id, job_id, "Beta Contracting", "47500.50")
    other_est = _estimate(conn, env, mod, job_id, name="Other Estimate")
    other_bid = _bid(conn, env, mod, other_est, job_id, "Gamma Works", "51000.00")
    assert is_ok(call_action(mod.ACTIONS["construction-award-bid"], conn,
                             ns(bid_id=bid_b)))
    before = _snapshot(conn)
    lst = mod.ACTIONS["construction-list-bids"]

    r = call_action(lst, conn, ns(company_id=env["company_id"],
                                  estimate_id=None, job_id=None, bid_status=None))
    assert is_ok(r), r
    assert r["total_count"] == 3
    assert {(b["id"], b["bidder_name"], b["bid_amount"], b["bid_status"])
            for b in r["bids"]} == {
        (bid_a, "Alpha Builders", "50000.00", "submitted"),
        (bid_b, "Beta Contracting", "47500.50", "awarded"),
        (other_bid, "Gamma Works", "51000.00", "submitted"),
    }
    assert _bid_rows(conn, "WHERE company_id = ?", (env["company_id"],)) == [
        (bid_a, est_id, job_id, "Alpha Builders", "50000.00", "submitted",
         env["company_id"]),
        (bid_b, est_id, job_id, "Beta Contracting", "47500.50", "awarded",
         env["company_id"]),
        (other_bid, other_est, job_id, "Gamma Works", "51000.00", "submitted",
         env["company_id"]),
    ]

    r = call_action(lst, conn, ns(company_id=None, estimate_id=est_id,
                                  job_id=None, bid_status=None))
    assert is_ok(r), r
    assert {b["id"] for b in r["bids"]} == {bid_a, bid_b}

    r = call_action(lst, conn, ns(company_id=None, estimate_id=None,
                                  job_id=None, bid_status="awarded"))
    assert is_ok(r), r
    assert [(b["id"], b["bid_amount"]) for b in r["bids"]] == [(bid_b, "47500.50")]

    r = call_action(lst, conn, ns(company_id=None, estimate_id=None,
                                  job_id=None, bid_status="rejected"))
    assert is_ok(r), r
    assert (r["total_count"], r["bids"]) == (0, [])
    # A list is a pure read: no rows, no audit entries.
    assert _snapshot(conn) == before


def test_list_bids_empty_scope_reads_nothing_and_writes_nothing(conn, env, mod):
    before = _snapshot(conn)
    r = call_action(mod.ACTIONS["construction-list-bids"], conn, ns(
        company_id=env["company_id"], estimate_id="no-such-estimate",
        job_id=None, bid_status=None))
    assert is_ok(r), r
    assert (r["total_count"], r["bids"]) == (0, [])
    assert _snapshot(conn) == before


# ═══════════════════════════════════════════════════════════════════════════
# construction-list-ccos (stored-row assertion)
# ═══════════════════════════════════════════════════════════════════════════

def test_list_ccos_returns_stored_changes_and_filters(conn, env, mod):
    job_id = _job(conn, env, mod)
    cco_a = _cco(conn, env, mod, job_id, "Extra footing", "5000.00")
    cco_b = _cco(conn, env, mod, job_id, "Credit for omission", "-750.25")
    assert is_ok(call_action(mod.ACTIONS["construction-approve-cco"], conn,
                             ns(cco_id=cco_a, approved_by="Owner")))
    other_job = _job(conn, env, mod, name="Other Job")
    other_cco = _cco(conn, env, mod, other_job, "Other change", "100.00")
    before = _snapshot(conn)
    lst = mod.ACTIONS["construction-list-ccos"]

    r = call_action(lst, conn, ns(company_id=env["company_id"], job_id=None,
                                  cco_status=None))
    assert is_ok(r), r
    assert r["total_count"] == 3
    assert {(c["id"], c["title"], c["cost_change"], c["cco_status"])
            for c in r["ccos"]} == {
        (cco_a, "Extra footing", "5000.00", "approved"),
        (cco_b, "Credit for omission", "-750.25", "draft"),
        (other_cco, "Other change", "100.00", "draft"),
    }
    assert [tuple(x) for x in conn.execute(
        "SELECT id, title, cost_change, cco_status FROM constructclaw_cco "
        "WHERE company_id = ? ORDER BY title", (env["company_id"],)).fetchall()] == [
        (cco_b, "Credit for omission", "-750.25", "draft"),
        (cco_a, "Extra footing", "5000.00", "approved"),
        (other_cco, "Other change", "100.00", "draft"),
    ]

    r = call_action(lst, conn, ns(company_id=None, job_id=job_id,
                                  cco_status="approved"))
    assert is_ok(r), r
    assert [(c["id"], c["cost_change"]) for c in r["ccos"]] == [(cco_a, "5000.00")]

    r = call_action(lst, conn, ns(company_id=None, job_id=job_id,
                                  cco_status="rejected"))
    assert is_ok(r), r
    assert (r["total_count"], r["ccos"]) == (0, [])
    assert _snapshot(conn) == before


def test_list_ccos_empty_scope_reads_nothing_and_writes_nothing(conn, env, mod):
    _job(conn, env, mod)
    before = _snapshot(conn)
    r = call_action(mod.ACTIONS["construction-list-ccos"], conn, ns(
        company_id=env["company_id"], job_id="no-such-job", cco_status=None))
    assert is_ok(r), r
    assert (r["total_count"], r["ccos"]) == (0, [])
    assert _snapshot(conn) == before


# ═══════════════════════════════════════════════════════════════════════════
# construction-list-commitments (stored-row assertion)
# ═══════════════════════════════════════════════════════════════════════════

def _commitment(conn, env, mod, job_id, vendor, amount):
    r = call_action(mod.ACTIONS["construction-add-commitment"], conn, ns(
        company_id=env["company_id"], job_id=job_id, cost_code_id=None,
        commitment_type=None, vendor=vendor, description="Depth supply",
        original_amount=amount))
    assert is_ok(r), r
    return r["commitment_id"]


def test_list_commitments_returns_stored_amounts_and_filters(conn, env, mod):
    job_id = _job(conn, env, mod)
    cm_a = _commitment(conn, env, mod, job_id, "Acme Steel", "12000.00")
    cm_b = _commitment(conn, env, mod, job_id, "Beta Lumber", "3500.75")
    other_job = _job(conn, env, mod, name="Other Job")
    other_cm = _commitment(conn, env, mod, other_job, "Gamma Glass", "900.00")
    before = _snapshot(conn)
    lst = mod.ACTIONS["construction-list-commitments"]

    r = call_action(lst, conn, ns(job_id=job_id, company_id=None,
                                  commitment_status=None, limit=50, offset=0))
    assert is_ok(r), r
    assert (r["total_count"], r["limit"], r["offset"]) == (2, 50, 0)
    assert {(c["id"], c["vendor"], c["original_amount"], c["revised_amount"],
             c["commitment_status"]) for c in r["commitments"]} == {
        (cm_a, "Acme Steel", "12000.00", "12000.00", "draft"),
        (cm_b, "Beta Lumber", "3500.75", "3500.75", "draft"),
    }
    assert [tuple(x) for x in conn.execute(
        "SELECT id, vendor, original_amount, revised_amount, commitment_status "
        "FROM constructclaw_commitment WHERE job_id = ? ORDER BY vendor",
        (job_id,)).fetchall()] == [
        (cm_a, "Acme Steel", "12000.00", "12000.00", "draft"),
        (cm_b, "Beta Lumber", "3500.75", "3500.75", "draft"),
    ]

    r = call_action(lst, conn, ns(job_id=None, company_id=env["company_id"],
                                  commitment_status="approved",
                                  limit=50, offset=0))
    assert is_ok(r), r
    assert (r["total_count"], r["commitments"]) == (0, [])

    r = call_action(lst, conn, ns(job_id=other_job, company_id=None,
                                  commitment_status=None, limit=50, offset=0))
    assert is_ok(r), r
    assert [(c["id"], c["original_amount"]) for c in r["commitments"]] == [
        (other_cm, "900.00")]
    assert _snapshot(conn) == before


def test_list_commitments_empty_scope_reads_nothing_and_writes_nothing(
        conn, env, mod):
    job_id = _job(conn, env, mod)
    _commitment(conn, env, mod, job_id, "Acme Steel", "12000.00")
    before = _snapshot(conn)
    r = call_action(mod.ACTIONS["construction-list-commitments"], conn, ns(
        job_id="no-such-job", company_id=None, commitment_status=None,
        limit=50, offset=0))
    assert is_ok(r), r
    assert (r["total_count"], r["commitments"]) == (0, [])
    assert _snapshot(conn) == before


# ═══════════════════════════════════════════════════════════════════════════
# construction-list-daily-materials (stored-row assertion)
# ═══════════════════════════════════════════════════════════════════════════

def _daily_report(conn, env, mod, job_id, date="2026-04-01",
                  superintendent="Sam Foreman", work="Poured footing"):
    r = call_action(mod.ACTIONS["construction-add-daily-report"], conn, ns(
        company_id=env["company_id"], job_id=job_id, report_date=date,
        superintendent=superintendent, weather=None, temperature_high=None,
        temperature_low=None, work_description=work, delays=None,
        visitors=None, notes=None))
    assert is_ok(r), r
    return r["daily_report_id"]


def _daily_material(conn, env, mod, report_id, name, qty, unit, supplier,
                    ticket):
    r = call_action(mod.ACTIONS["construction-add-daily-material"], conn, ns(
        company_id=env["company_id"], daily_report_id=report_id,
        material_name=name, quantity=qty, unit=unit, supplier=supplier,
        delivery_ticket=ticket))
    assert is_ok(r), r
    return r["daily_material_id"]


def test_list_daily_materials_returns_stored_deliveries(conn, env, mod):
    job_id = _job(conn, env, mod)
    report = _daily_report(conn, env, mod, job_id)
    mat_a = _daily_material(conn, env, mod, report, "Concrete", "10", "cy",
                            "Acme Supply", "T-101")
    mat_b = _daily_material(conn, env, mod, report, "Rebar", "500", "kg",
                            "Beta Steel", "T-102")
    other_report = _daily_report(conn, env, mod, job_id, date="2026-04-02")
    other_mat = _daily_material(conn, env, mod, other_report, "Sand", "4",
                                "ton", "Gamma Pit", "T-201")
    before = _snapshot(conn)

    r = call_action(mod.ACTIONS["construction-list-daily-materials"], conn,
                    ns(daily_report_id=report))
    assert is_ok(r), r
    assert r["total_count"] == 2
    assert {(m["id"], m["material_name"], m["quantity"], m["unit"],
             m["supplier"], m["delivery_ticket"]) for m in r["daily_materials"]} == {
        (mat_a, "Concrete", "10", "cy", "Acme Supply", "T-101"),
        (mat_b, "Rebar", "500", "kg", "Beta Steel", "T-102"),
    }
    assert [tuple(x) for x in conn.execute(
        "SELECT id, material_name, quantity, unit, supplier, delivery_ticket "
        "FROM constructclaw_daily_material WHERE daily_report_id = ? "
        "ORDER BY material_name", (report,)).fetchall()] == [
        (mat_a, "Concrete", "10", "cy", "Acme Supply", "T-101"),
        (mat_b, "Rebar", "500", "kg", "Beta Steel", "T-102"),
    ]
    # Materials booked to the other report are out of scope.
    assert other_mat not in {m["id"] for m in r["daily_materials"]}
    assert _snapshot(conn) == before


def test_list_daily_materials_refusals_write_nothing(conn, env, mod):
    job_id = _job(conn, env, mod)
    report = _daily_report(conn, env, mod, job_id)
    mat = _daily_material(conn, env, mod, report, "Concrete", "10", "cy",
                          "Acme Supply", "T-101")
    before = _snapshot(conn)
    lst = mod.ACTIONS["construction-list-daily-materials"]

    r = call_action(lst, conn, ns(daily_report_id=None))
    assert is_error(r)
    assert r["message"] == "--daily-report-id is required"

    # An unknown report is not an error: it simply has no deliveries.
    r = call_action(lst, conn, ns(daily_report_id="no-such-report"))
    assert is_ok(r), r
    assert (r["total_count"], r["daily_materials"]) == (0, [])

    assert tuple(conn.execute(
        "SELECT material_name, quantity FROM constructclaw_daily_material "
        "WHERE id = ?", (mat,)).fetchone()) == ("Concrete", "10")
    assert _snapshot(conn) == before


# ═══════════════════════════════════════════════════════════════════════════
# construction-list-daily-reports (stored-row assertion)
# ═══════════════════════════════════════════════════════════════════════════

def test_list_daily_reports_returns_stored_reports_and_filters(conn, env, mod):
    job_id = _job(conn, env, mod)
    rep_a = _daily_report(conn, env, mod, job_id, "2026-04-01", "Sam Foreman",
                          "Poured footing")
    rep_b = _daily_report(conn, env, mod, job_id, "2026-04-03", "Jo Lead",
                          "Set formwork")
    assert is_ok(call_action(mod.ACTIONS["construction-submit-daily-report"],
                             conn, ns(daily_report_id=rep_b)))
    other_job = _job(conn, env, mod, name="Other Job")
    other_rep = _daily_report(conn, env, mod, other_job, "2026-04-02")
    before = _snapshot(conn)
    lst = mod.ACTIONS["construction-list-daily-reports"]

    r = call_action(lst, conn, ns(company_id=env["company_id"], job_id=None,
                                  report_status=None, search=None,
                                  limit=50, offset=0))
    assert is_ok(r), r
    assert r["total_count"] == 3
    assert [(d["id"], d["report_date"], d["report_status"])
            for d in r["daily_reports"]] == [
        (rep_b, "2026-04-03", "submitted"),
        (other_rep, "2026-04-02", "draft"),
        (rep_a, "2026-04-01", "draft"),
    ]
    assert [tuple(x) for x in conn.execute(
        "SELECT id, report_date, superintendent, work_description, "
        "report_status FROM constructclaw_daily_report "
        "WHERE company_id = ? ORDER BY report_date DESC",
        (env["company_id"],)).fetchall()] == [
        (rep_b, "2026-04-03", "Jo Lead", "Set formwork", "submitted"),
        (other_rep, "2026-04-02", "Sam Foreman", "Poured footing", "draft"),
        (rep_a, "2026-04-01", "Sam Foreman", "Poured footing", "draft"),
    ]

    r = call_action(lst, conn, ns(company_id=None, job_id=job_id,
                                  report_status="submitted", search=None,
                                  limit=50, offset=0))
    assert is_ok(r), r
    assert [(d["id"], d["superintendent"]) for d in r["daily_reports"]] == [
        (rep_b, "Jo Lead")]

    r = call_action(lst, conn, ns(company_id=None, job_id=job_id,
                                  report_status="approved", search=None,
                                  limit=50, offset=0))
    assert is_ok(r), r
    assert (r["total_count"], r["daily_reports"]) == (0, [])
    assert _snapshot(conn) == before


def test_list_daily_reports_empty_scope_reads_nothing_and_writes_nothing(
        conn, env, mod):
    job_id = _job(conn, env, mod)
    _daily_report(conn, env, mod, job_id)
    before = _snapshot(conn)
    r = call_action(mod.ACTIONS["construction-list-daily-reports"], conn, ns(
        company_id=None, job_id="no-such-job", report_status=None,
        search=None, limit=50, offset=0))
    assert is_ok(r), r
    assert (r["total_count"], r["daily_reports"]) == (0, [])
    assert _snapshot(conn) == before


# ═══════════════════════════════════════════════════════════════════════════
# construction-list-drawings (documents a defect; deliberately not fixed)
# ═══════════════════════════════════════════════════════════════════════════
#
# DEFECT: construction-add-drawing inserts job_id / unit_cost / notes / status
# into constructclaw_daily_material, but the provisioned table has none of
# those columns, so every add fails with
#   sqlite3.OperationalError: table constructclaw_daily_material has no
#   column named job_id
# and construction-list-drawings filters on the same missing status column.
# PyPika quotes the identifier, and SQLite resolves a double-quoted name that
# matches no column as a string literal, so WHERE "status" = 'drawing' is
# literal-to-literal, false for every row: the list always returns empty even
# when material rows exist. The tests below pin that real behaviour.

def test_list_drawings_always_returns_empty_despite_stored_rows(conn, env, mod):
    job_id = _job(conn, env, mod)
    report = _daily_report(conn, env, mod, job_id)
    mat = _daily_material(conn, env, mod, report, "Concrete", "10", "cy",
                          "Acme Supply", "T-101")
    before = _snapshot(conn)

    r = call_action(mod.ACTIONS["construction-list-drawings"], conn, ns(
        company_id=env["company_id"], job_id=job_id))
    assert is_ok(r), r
    assert (r["total_count"], r["drawings"]) == (0, [])
    # The material row the list cannot see is really there.
    assert tuple(conn.execute(
        "SELECT material_name, quantity FROM constructclaw_daily_material "
        "WHERE id = ?", (mat,)).fetchone()) == ("Concrete", "10")
    assert _snapshot(conn) == before


def test_add_drawing_fails_on_the_missing_column_and_writes_nothing(
        conn, env, mod):
    job_id = _job(conn, env, mod)
    before = _snapshot(conn)

    with pytest.raises(sqlite3.OperationalError,
                       match="no column named job_id"):
        call_action(mod.ACTIONS["construction-add-drawing"], conn, ns(
            company_id=env["company_id"], job_id=job_id, name="A-101",
            spec_section="03 30 00", discipline="Structural",
            sheet_number="A-101", description="Foundation plan"))

    assert conn.execute(
        "SELECT COUNT(*) FROM constructclaw_daily_material").fetchone()[0] == 0
    assert _snapshot(conn) == before


# ═══════════════════════════════════════════════════════════════════════════
# construction-list-earned-values (stored-row assertion)
# ═══════════════════════════════════════════════════════════════════════════

def _earned_value(conn, env, mod, job_id, period, planned, earned, actual,
                  bac):
    r = call_action(mod.ACTIONS["construction-add-earned-value"], conn, ns(
        company_id=env["company_id"], job_id=job_id, period_date=period,
        planned_value=planned, earned_value=earned, actual_cost=actual,
        budget_at_completion=bac, notes=None))
    assert is_ok(r), r
    return r["earned_value_id"]


def test_list_earned_values_returns_stored_points_newest_first(conn, env, mod):
    job_id = _job(conn, env, mod)
    ev_apr = _earned_value(conn, env, mod, job_id, "2026-04-30", "40000.00",
                           "35000.00", "38000.00", "100000.00")
    ev_may = _earned_value(conn, env, mod, job_id, "2026-05-31", "60000.00",
                           "55000.00", "58000.00", "100000.00")
    other_job = _job(conn, env, mod, name="Other Job")
    other_ev = _earned_value(conn, env, mod, other_job, "2026-05-31",
                             "10000.00", "9000.00", "9500.00", "50000.00")
    before = _snapshot(conn)
    lst = mod.ACTIONS["construction-list-earned-values"]

    r = call_action(lst, conn, ns(job_id=job_id, company_id=None))
    assert is_ok(r), r
    assert r["total_count"] == 2
    assert [(e["id"], e["period_date"], e["planned_value"], e["earned_value"],
             e["actual_cost"], e["budget_at_completion"])
            for e in r["earned_values"]] == [
        (ev_may, "2026-05-31", "60000.00", "55000.00", "58000.00", "100000.00"),
        (ev_apr, "2026-04-30", "40000.00", "35000.00", "38000.00", "100000.00"),
    ]
    assert [tuple(x) for x in conn.execute(
        "SELECT id, period_date, planned_value, earned_value, actual_cost, "
        "budget_at_completion FROM constructclaw_earned_value "
        "WHERE job_id = ? ORDER BY period_date DESC", (job_id,)).fetchall()] == [
        (ev_may, "2026-05-31", "60000.00", "55000.00", "58000.00", "100000.00"),
        (ev_apr, "2026-04-30", "40000.00", "35000.00", "38000.00", "100000.00"),
    ]
    assert other_ev not in {e["id"] for e in r["earned_values"]}

    r = call_action(lst, conn, ns(job_id=None, company_id=env["company_id"]))
    assert is_ok(r), r
    assert r["total_count"] == 3
    assert _snapshot(conn) == before


def test_list_earned_values_empty_scope_reads_nothing_and_writes_nothing(
        conn, env, mod):
    job_id = _job(conn, env, mod)
    _earned_value(conn, env, mod, job_id, "2026-04-30", "40000.00",
                  "35000.00", "38000.00", "100000.00")
    before = _snapshot(conn)
    r = call_action(mod.ACTIONS["construction-list-earned-values"], conn, ns(
        job_id="no-such-job", company_id=None))
    assert is_ok(r), r
    assert (r["total_count"], r["earned_values"]) == (0, [])
    assert _snapshot(conn) == before


# ═══════════════════════════════════════════════════════════════════════════
# construction-list-estimates (stored-row assertion)
# ═══════════════════════════════════════════════════════════════════════════

def test_list_estimates_returns_stored_estimates_and_filters(conn, env, mod):
    job_id = _job(conn, env, mod)
    est_a = _estimate(conn, env, mod, job_id, name="Tower Estimate")
    est_b = _estimate(conn, env, mod, job_id, name="Shed Estimate")
    assert is_ok(call_action(mod.ACTIONS["construction-submit-estimate"],
                             conn, ns(estimate_id=est_b)))
    other_company = seed_company(conn)
    seed_naming_series(conn, other_company)
    other_est = call_action(mod.ACTIONS["construction-add-estimate"], conn, ns(
        company_id=other_company, job_id=None, name="Foreign Estimate",
        client_name=None, description=None, due_date=None,
        markup_pct=None, overhead_pct=None, profit_pct=None, notes=None))
    assert is_ok(other_est), other_est
    before = _snapshot(conn)
    lst = mod.ACTIONS["construction-list-estimates"]

    r = call_action(lst, conn, ns(company_id=env["company_id"],
                                  estimate_status=None, search=None,
                                  limit=50, offset=0))
    assert is_ok(r), r
    assert r["total_count"] == 2
    assert {(e["id"], e["name"], e["estimate_status"], e["company_id"])
            for e in r["estimates"]} == {
        (est_a, "Tower Estimate", "draft", env["company_id"]),
        (est_b, "Shed Estimate", "submitted", env["company_id"]),
    }
    assert [tuple(x) for x in conn.execute(
        "SELECT id, name, estimate_status, company_id FROM "
        "constructclaw_estimate WHERE company_id = ? ORDER BY name",
        (env["company_id"],)).fetchall()] == [
        (est_b, "Shed Estimate", "submitted", env["company_id"]),
        (est_a, "Tower Estimate", "draft", env["company_id"]),
    ]
    # The other company's estimate is out of scope.
    assert other_est["estimate_id"] not in {e["id"] for e in r["estimates"]}

    r = call_action(lst, conn, ns(company_id=env["company_id"],
                                  estimate_status="submitted", search=None,
                                  limit=50, offset=0))
    assert is_ok(r), r
    assert [(e["id"], e["name"]) for e in r["estimates"]] == [
        (est_b, "Shed Estimate")]

    r = call_action(lst, conn, ns(company_id=env["company_id"],
                                  estimate_status=None, search="Tower",
                                  limit=50, offset=0))
    assert is_ok(r), r
    assert [(e["id"], e["name"]) for e in r["estimates"]] == [
        (est_a, "Tower Estimate")]
    assert _snapshot(conn) == before


def test_list_estimates_empty_scope_reads_nothing_and_writes_nothing(
        conn, env, mod):
    job_id = _job(conn, env, mod)
    _estimate(conn, env, mod, job_id)
    before = _snapshot(conn)
    r = call_action(mod.ACTIONS["construction-list-estimates"], conn, ns(
        company_id=env["company_id"], estimate_status="won", search=None,
        limit=50, offset=0))
    assert is_ok(r), r
    assert (r["total_count"], r["estimates"]) == (0, [])
    assert _snapshot(conn) == before
