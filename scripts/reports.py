"""ConstructClaw -- Reports domain module.

Executive summaries, portfolio overview, cross-domain reports.
7 actions exported via ACTIONS dict.
"""
import os
import sys
from decimal import Decimal, ROUND_HALF_UP

import importlib.util
if importlib.util.find_spec("erpclaw_lib") is None:
    sys.path.insert(0, os.path.join(os.path.expanduser(os.environ.get("ERPCLAW_HOME", "~/.openclaw/erpclaw")), "lib"))
from erpclaw_lib.response import ok, err, row_to_dict
from erpclaw_lib.query import Q, P, Table, Field, fn, Order, insert_row


SKILL = "constructclaw"


def _d(val, default="0"):
    if val is None:
        return Decimal(default)
    return Decimal(str(val))


# ---------------------------------------------------------------------------
# job-cost-report -- detailed job cost report
# ---------------------------------------------------------------------------
def job_cost_report(conn, args):
    job_id = getattr(args, "job_id", None)
    if not job_id:
        err("--job-id is required")

    job = conn.execute(Q.from_(Table("constructclaw_job")).select(Table("constructclaw_job").star).where(Field("id") == P()).get_sql(), (job_id,)).fetchone()
    if not job:
        err(f"Job {job_id} not found")

    contract = _d(job["contract_amount"])

    # Cost by category
    cat_rows = conn.execute(
        """SELECT category, COUNT(*) as entry_count,
                  COALESCE(SUM(CAST(amount AS NUMERIC)), 0) as total_amount,
                  COALESCE(SUM(CAST(hours AS REAL)), 0) as total_hours
           FROM constructclaw_cost_entry WHERE job_id = ?
           GROUP BY category ORDER BY total_amount DESC""",
        (job_id,),
    ).fetchall()

    by_category = []
    total_cost = Decimal("0")
    for r in cat_rows:
        amt = _d(r["total_amount"])
        total_cost += amt
        by_category.append({
            "category": r["category"],
            "entry_count": r["entry_count"],
            "total_amount": str(amt.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "total_hours": str(_d(r["total_hours"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        })

    # Commitments
    commitment_row = conn.execute(
        "SELECT COALESCE(SUM(CAST(revised_amount AS NUMERIC)), 0) as total FROM constructclaw_commitment WHERE job_id = ? AND commitment_status NOT IN ('cancelled','closed')",
        (job_id,),
    ).fetchone()
    total_committed = _d(commitment_row["total"])

    # Change orders
    co_row = conn.execute(
        "SELECT COALESCE(SUM(CAST(cost_change AS NUMERIC)), 0) as total FROM constructclaw_cco WHERE job_id = ? AND cco_status IN ('approved','executed')",
        (job_id,),
    ).fetchone()
    total_cos = _d(co_row["total"])

    revised_contract = contract + total_cos
    variance = revised_contract - total_cost

    ok({
        "job_id": job_id,
        "job_name": job["name"],
        "job_status": job["job_status"],
        "original_contract": str(contract.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "change_orders": str(total_cos.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "revised_contract": str(revised_contract.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "total_cost": str(total_cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "total_committed": str(total_committed.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "variance": str(variance.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "by_category": by_category,
    })


# ---------------------------------------------------------------------------
# wip-report-all -- WIP report across all jobs
# ---------------------------------------------------------------------------
def wip_report_all(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")

    jobs = conn.execute(
        "SELECT * FROM constructclaw_job WHERE company_id = ? AND job_status IN ('active','on_hold','substantially_complete')",
        (args.company_id,),
    ).fetchall()

    report = []
    total_contract_all = Decimal("0")
    total_cost_all = Decimal("0")
    total_billed_all = Decimal("0")

    for j in jobs:
        contract = _d(j["contract_amount"])
        pct = _d(j["percent_complete"])
        total_contract_all += contract

        cost_row = conn.execute(
            "SELECT COALESCE(SUM(CAST(amount AS NUMERIC)), 0) as total FROM constructclaw_cost_entry WHERE job_id = ?",
            (j["id"],),
        ).fetchone()
        total_cost = _d(cost_row["total"])
        total_cost_all += total_cost

        billed_row = conn.execute(
            "SELECT COALESCE(SUM(CAST(current_due AS NUMERIC)), 0) as total FROM constructclaw_progress_bill WHERE job_id = ? AND bill_status != 'rejected'",
            (j["id"],),
        ).fetchone()
        total_billed = _d(billed_row["total"])
        total_billed_all += total_billed

        earned = (contract * pct / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        over_under = total_billed - earned

        report.append({
            "job_id": j["id"],
            "job_name": j["name"],
            "contract_amount": str(contract.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "percent_complete": str(pct),
            "earned_revenue": str(earned),
            "total_cost": str(total_cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "total_billed": str(total_billed.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "over_under_billing": str(over_under.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        })

    ok({
        "company_id": args.company_id,
        "jobs": report,
        "total_count": len(report),
        "total_contract_value": str(total_contract_all.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "total_cost": str(total_cost_all.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "total_billed": str(total_billed_all.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
    })


# ---------------------------------------------------------------------------
# subcontractor-aging (cross-domain report, delegates to subcontractors module data)
# ---------------------------------------------------------------------------
def subcontractor_aging(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")

    subs = conn.execute(
        "SELECT * FROM constructclaw_subcontract WHERE company_id = ? AND subcontract_status NOT IN ('cancelled','terminated') ORDER BY subcontractor_name",
        (args.company_id,),
    ).fetchall()

    report = []
    for s in subs:
        revised = _d(s["revised_amount"])
        paid_row = conn.execute(
            "SELECT COALESCE(SUM(CAST(current_payment_due AS NUMERIC)), 0) as total FROM constructclaw_pay_application WHERE subcontract_id = ? AND pay_app_status IN ('approved','paid')",
            (s["id"],),
        ).fetchone()
        paid = _d(paid_row["total"])
        remaining = revised - paid

        report.append({
            "subcontract_id": s["id"],
            "subcontractor_name": s["subcontractor_name"],
            "trade": s["trade"],
            "contract_amount": str(revised.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "paid": str(paid.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "remaining": str(remaining.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        })

    ok({"company_id": args.company_id, "subcontractors": report, "total_count": len(report)})


# ---------------------------------------------------------------------------
# safety-report (cross-domain report)
# ---------------------------------------------------------------------------
def safety_report(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")

    total = conn.execute(
        "SELECT COUNT(*) as cnt FROM constructclaw_incident WHERE company_id = ?",
        (args.company_id,),
    ).fetchone()["cnt"]

    recordable = conn.execute(
        "SELECT COUNT(*) as cnt FROM constructclaw_incident WHERE company_id = ? AND osha_recordable = 1",
        (args.company_id,),
    ).fetchone()["cnt"]

    days_lost = conn.execute(
        "SELECT COALESCE(SUM(days_lost), 0) as total FROM constructclaw_incident WHERE company_id = ?",
        (args.company_id,),
    ).fetchone()["total"]

    talks = conn.execute(
        "SELECT COUNT(*) as cnt FROM constructclaw_toolbox_talk WHERE company_id = ?",
        (args.company_id,),
    ).fetchone()["cnt"]

    ok({
        "company_id": args.company_id,
        "total_incidents": total,
        "osha_recordable": recordable,
        "days_lost": days_lost,
        "toolbox_talks": talks,
    })


# ---------------------------------------------------------------------------
# executive-summary
# ---------------------------------------------------------------------------
def executive_summary(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")

    company_id = args.company_id

    # Jobs overview
    job_stats = conn.execute(
        """SELECT job_status, COUNT(*) as cnt
           FROM constructclaw_job WHERE company_id = ?
           GROUP BY job_status""",
        (company_id,),
    ).fetchall()
    jobs_by_status = {r["job_status"]: r["cnt"] for r in job_stats}

    total_contract_row = conn.execute(
        "SELECT COALESCE(SUM(CAST(contract_amount AS NUMERIC)), 0) as total FROM constructclaw_job WHERE company_id = ? AND job_status NOT IN ('cancelled')",
        (company_id,),
    ).fetchone()
    total_contract = _d(total_contract_row["total"])

    total_cost_row = conn.execute(
        "SELECT COALESCE(SUM(CAST(amount AS NUMERIC)), 0) as total FROM constructclaw_cost_entry WHERE company_id = ?",
        (company_id,),
    ).fetchone()
    total_cost = _d(total_cost_row["total"])

    total_billed_row = conn.execute(
        "SELECT COALESCE(SUM(CAST(current_due AS NUMERIC)), 0) as total FROM constructclaw_progress_bill WHERE company_id = ? AND bill_status != 'rejected'",
        (company_id,),
    ).fetchone()
    total_billed = _d(total_billed_row["total"])

    open_rfis = conn.execute(
        "SELECT COUNT(*) as cnt FROM constructclaw_rfi WHERE company_id = ? AND rfi_status = 'open'",
        (company_id,),
    ).fetchone()["cnt"]

    pending_cos = conn.execute(
        "SELECT COUNT(*) as cnt FROM constructclaw_pco WHERE company_id = ? AND pco_status NOT IN ('approved','rejected','void')",
        (company_id,),
    ).fetchone()["cnt"]

    open_incidents = conn.execute(
        "SELECT COUNT(*) as cnt FROM constructclaw_incident WHERE company_id = ? AND incident_status != 'closed'",
        (company_id,),
    ).fetchone()["cnt"]

    margin = Decimal("0")
    if total_contract > 0:
        margin = ((total_contract - total_cost) / total_contract * Decimal("100")).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    ok({
        "company_id": company_id,
        "jobs_by_status": jobs_by_status,
        "total_contract_value": str(total_contract.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "total_cost_to_date": str(total_cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "overall_margin_pct": str(margin),
        "total_billed": str(total_billed.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "open_rfis": open_rfis,
        "pending_change_orders": pending_cos,
        "open_safety_incidents": open_incidents,
    })


# ---------------------------------------------------------------------------
# portfolio-overview
# ---------------------------------------------------------------------------
def portfolio_overview(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")

    jobs = conn.execute(
        "SELECT * FROM constructclaw_job WHERE company_id = ? AND job_status NOT IN ('cancelled','closed') ORDER BY created_at DESC",
        (args.company_id,),
    ).fetchall()

    portfolio = []
    for j in jobs:
        contract = _d(j["contract_amount"])

        cost_row = conn.execute(
            "SELECT COALESCE(SUM(CAST(amount AS NUMERIC)), 0) as total FROM constructclaw_cost_entry WHERE job_id = ?",
            (j["id"],),
        ).fetchone()
        total_cost = _d(cost_row["total"])

        co_row = conn.execute(
            "SELECT COALESCE(SUM(CAST(cost_change AS NUMERIC)), 0) as total FROM constructclaw_cco WHERE job_id = ? AND cco_status IN ('approved','executed')",
            (j["id"],),
        ).fetchone()
        total_cos = _d(co_row["total"])

        revised = contract + total_cos
        profit = revised - total_cost
        margin = (profit / revised * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if revised > 0 else Decimal("0")

        portfolio.append({
            "job_id": j["id"],
            "job_name": j["name"],
            "job_status": j["job_status"],
            "percent_complete": j["percent_complete"],
            "contract_amount": str(contract.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "revised_contract": str(revised.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "total_cost": str(total_cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "profit": str(profit.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "margin_pct": str(margin),
        })

    ok({"company_id": args.company_id, "portfolio": portfolio, "total_count": len(portfolio)})


# ---------------------------------------------------------------------------
# report-status
# ---------------------------------------------------------------------------
def report_status(conn, args):
    ok({"skill": "constructclaw", "module": "reports", "report_status_value": "operational"})


# ---------------------------------------------------------------------------
# ACTIONS registry
# ---------------------------------------------------------------------------
ACTIONS = {
    "construction-job-cost-report": job_cost_report,
    "construction-wip-report-all": wip_report_all,
    "construction-subcontractor-aging": subcontractor_aging,
    "construction-safety-report": safety_report,
    "construction-executive-summary": executive_summary,
    "construction-portfolio-overview": portfolio_overview,
    "construction-report-status": report_status,
}
