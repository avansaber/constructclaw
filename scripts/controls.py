"""ConstructClaw -- Project Controls domain module.

Earned value management, schedule variance, cost forecasting, project health.
8 actions exported via ACTIONS dict.
"""
import os
import sys
import uuid
from datetime import date as _date
from decimal import Decimal, ROUND_HALF_UP

sys.path.insert(0, os.path.expanduser("~/.openclaw/erpclaw/lib"))
from erpclaw_lib.response import ok, err, row_to_dict
from erpclaw_lib.audit import audit

SKILL = "constructclaw"


def _d(val, default="0"):
    if val is None:
        return Decimal(default)
    return Decimal(str(val))


# ---------------------------------------------------------------------------
# add-earned-value
# ---------------------------------------------------------------------------
def add_earned_value(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")
    job_id = getattr(args, "job_id", None)
    if not job_id:
        err("--job-id is required")

    if not conn.execute("SELECT id FROM constructclaw_job WHERE id = ?", (job_id,)).fetchone():
        err(f"Job {job_id} not found")

    ev_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO constructclaw_earned_value
           (id, job_id, period_date, planned_value, earned_value,
            actual_cost, budget_at_completion, notes, company_id)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            ev_id, job_id,
            getattr(args, "period_date", None) or _date.today().isoformat(),
            getattr(args, "planned_value", None) or "0",
            getattr(args, "earned_value", None) or "0",
            getattr(args, "actual_cost", None) or "0",
            getattr(args, "budget_at_completion", None) or "0",
            getattr(args, "notes", None),
            args.company_id,
        ),
    )
    audit(conn, SKILL, "construction-add-earned-value", "constructclaw_earned_value", ev_id,
          new_values={"job_id": job_id})
    conn.commit()
    ok({"earned_value_id": ev_id, "job_id": job_id})


# ---------------------------------------------------------------------------
# list-earned-values
# ---------------------------------------------------------------------------
def list_earned_values(conn, args):
    conditions, params = [], []
    job_id = getattr(args, "job_id", None)
    if job_id:
        conditions.append("job_id = ?")
        params.append(job_id)
    cid = getattr(args, "company_id", None)
    if cid:
        conditions.append("company_id = ?")
        params.append(cid)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = conn.execute(
        f"SELECT * FROM constructclaw_earned_value {where} ORDER BY period_date DESC",
        params,
    ).fetchall()
    ok({"earned_values": [row_to_dict(r) for r in rows], "total_count": len(rows)})


# ---------------------------------------------------------------------------
# calculate-ev-metrics -- CPI, SPI, EAC, ETC, VAC
# ---------------------------------------------------------------------------
def calculate_ev_metrics(conn, args):
    job_id = getattr(args, "job_id", None)
    if not job_id:
        err("--job-id is required")

    # Get latest earned value data point
    row = conn.execute(
        "SELECT * FROM constructclaw_earned_value WHERE job_id = ? ORDER BY period_date DESC LIMIT 1",
        (job_id,),
    ).fetchone()

    if not row:
        err(f"No earned value data found for job {job_id}")

    pv = _d(row["planned_value"])
    ev = _d(row["earned_value"])
    ac = _d(row["actual_cost"])
    bac = _d(row["budget_at_completion"])

    # Schedule Variance (SV) = EV - PV
    sv = ev - pv

    # Cost Variance (CV) = EV - AC
    cv = ev - ac

    # Schedule Performance Index (SPI) = EV / PV
    spi = (ev / pv).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if pv > 0 else Decimal("0")

    # Cost Performance Index (CPI) = EV / AC
    cpi = (ev / ac).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if ac > 0 else Decimal("0")

    # Estimate at Completion (EAC) = BAC / CPI
    eac = (bac / cpi).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if cpi > 0 else Decimal("0")

    # Estimate to Complete (ETC) = EAC - AC
    etc = eac - ac

    # Variance at Completion (VAC) = BAC - EAC
    vac = bac - eac

    # To Complete Performance Index (TCPI) = (BAC - EV) / (BAC - AC)
    remaining_budget = bac - ac
    tcpi = ((bac - ev) / remaining_budget).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if remaining_budget > 0 else Decimal("0")

    # Percent complete
    pct_complete = (ev / bac * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if bac > 0 else Decimal("0")

    ok({
        "job_id": job_id,
        "period_date": row["period_date"],
        "planned_value": str(pv.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "earned_value": str(ev.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "actual_cost": str(ac.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "budget_at_completion": str(bac.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "schedule_variance": str(sv.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "cost_variance": str(cv.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "spi": str(spi),
        "cpi": str(cpi),
        "eac": str(eac),
        "etc": str(etc.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "vac": str(vac.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "tcpi": str(tcpi),
        "percent_complete": str(pct_complete),
        "schedule_health": "ahead" if sv > 0 else ("on_track" if sv == 0 else "behind"),
        "cost_health": "under_budget" if cv > 0 else ("on_budget" if cv == 0 else "over_budget"),
    })


# ---------------------------------------------------------------------------
# schedule-variance-report
# ---------------------------------------------------------------------------
def schedule_variance_report(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")

    # Get all active jobs
    jobs = conn.execute(
        "SELECT * FROM constructclaw_job WHERE company_id = ? AND job_status IN ('active','on_hold')",
        (args.company_id,),
    ).fetchall()

    report = []
    for j in jobs:
        ev_row = conn.execute(
            "SELECT * FROM constructclaw_earned_value WHERE job_id = ? ORDER BY period_date DESC LIMIT 1",
            (j["id"],),
        ).fetchone()

        if ev_row:
            pv = _d(ev_row["planned_value"])
            ev = _d(ev_row["earned_value"])
            sv = ev - pv
            spi = (ev / pv).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if pv > 0 else Decimal("0")
        else:
            sv = Decimal("0")
            spi = Decimal("0")

        report.append({
            "job_id": j["id"],
            "job_name": j["name"],
            "job_status": j["job_status"],
            "schedule_variance": str(sv.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "spi": str(spi),
            "schedule_health": "ahead" if sv > 0 else ("on_track" if sv == 0 else "behind"),
        })

    ok({"company_id": args.company_id, "jobs": report, "total_count": len(report)})


# ---------------------------------------------------------------------------
# cost-forecast
# ---------------------------------------------------------------------------
def cost_forecast(conn, args):
    job_id = getattr(args, "job_id", None)
    if not job_id:
        err("--job-id is required")

    job = conn.execute("SELECT * FROM constructclaw_job WHERE id = ?", (job_id,)).fetchone()
    if not job:
        err(f"Job {job_id} not found")

    contract = _d(job["contract_amount"])

    # Total actual cost
    cost_row = conn.execute(
        "SELECT COALESCE(SUM(CAST(amount AS REAL)), 0) as total FROM constructclaw_cost_entry WHERE job_id = ?",
        (job_id,),
    ).fetchone()
    actual_cost = _d(cost_row["total"])

    # Total committed
    committed_row = conn.execute(
        "SELECT COALESCE(SUM(CAST(revised_amount AS REAL)), 0) as total FROM constructclaw_commitment WHERE job_id = ? AND commitment_status NOT IN ('cancelled','closed')",
        (job_id,),
    ).fetchone()
    total_committed = _d(committed_row["total"])

    # Projected final cost = actual + remaining commitments
    projected = actual_cost + total_committed
    projected_variance = contract - projected

    # Latest EV-based EAC if available
    ev_row = conn.execute(
        "SELECT * FROM constructclaw_earned_value WHERE job_id = ? ORDER BY period_date DESC LIMIT 1",
        (job_id,),
    ).fetchone()

    ev_based_eac = None
    if ev_row:
        ev = _d(ev_row["earned_value"])
        ac = _d(ev_row["actual_cost"])
        bac = _d(ev_row["budget_at_completion"])
        cpi = (ev / ac) if ac > 0 else Decimal("1")
        ev_based_eac = str((bac / cpi).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) if cpi > 0 else None

    ok({
        "job_id": job_id,
        "job_name": job["name"],
        "contract_amount": str(contract.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "actual_cost": str(actual_cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "total_committed": str(total_committed.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "projected_final_cost": str(projected.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "projected_variance": str(projected_variance.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "ev_based_eac": ev_based_eac,
    })


# ---------------------------------------------------------------------------
# project-health-dashboard
# ---------------------------------------------------------------------------
def project_health_dashboard(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")

    company_id = args.company_id

    total_jobs = conn.execute(
        "SELECT COUNT(*) as cnt FROM constructclaw_job WHERE company_id = ?", (company_id,)
    ).fetchone()["cnt"]

    active_jobs = conn.execute(
        "SELECT COUNT(*) as cnt FROM constructclaw_job WHERE company_id = ? AND job_status = 'active'",
        (company_id,),
    ).fetchone()["cnt"]

    total_contract_row = conn.execute(
        "SELECT COALESCE(SUM(CAST(contract_amount AS REAL)), 0) as total FROM constructclaw_job WHERE company_id = ? AND job_status NOT IN ('cancelled')",
        (company_id,),
    ).fetchone()
    total_contract = _d(total_contract_row["total"])

    total_cost_row = conn.execute(
        "SELECT COALESCE(SUM(CAST(amount AS REAL)), 0) as total FROM constructclaw_cost_entry WHERE company_id = ?",
        (company_id,),
    ).fetchone()
    total_cost = _d(total_cost_row["total"])

    open_rfis = conn.execute(
        "SELECT COUNT(*) as cnt FROM constructclaw_rfi WHERE company_id = ? AND rfi_status = 'open'",
        (company_id,),
    ).fetchone()["cnt"]

    pending_submittals = conn.execute(
        "SELECT COUNT(*) as cnt FROM constructclaw_submittal WHERE company_id = ? AND submittal_status IN ('pending','under_review')",
        (company_id,),
    ).fetchone()["cnt"]

    open_pcos = conn.execute(
        "SELECT COUNT(*) as cnt FROM constructclaw_pco WHERE company_id = ? AND pco_status NOT IN ('approved','rejected','void')",
        (company_id,),
    ).fetchone()["cnt"]

    open_incidents = conn.execute(
        "SELECT COUNT(*) as cnt FROM constructclaw_incident WHERE company_id = ? AND incident_status != 'closed'",
        (company_id,),
    ).fetchone()["cnt"]

    ok({
        "company_id": company_id,
        "total_jobs": total_jobs,
        "active_jobs": active_jobs,
        "total_contract_value": str(total_contract.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "total_cost_to_date": str(total_cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "open_rfis": open_rfis,
        "pending_submittals": pending_submittals,
        "open_change_orders": open_pcos,
        "open_safety_incidents": open_incidents,
    })


# ---------------------------------------------------------------------------
# resource-utilization
# ---------------------------------------------------------------------------
def resource_utilization(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")

    company_id = args.company_id

    # Labor hours from daily reports
    labor_row = conn.execute(
        """SELECT COALESCE(SUM(CAST(dl.hours AS REAL)), 0) as total_hours,
                  COALESCE(SUM(dl.headcount), 0) as total_headcount
           FROM constructclaw_daily_labor dl
           JOIN constructclaw_daily_report dr ON dl.daily_report_id = dr.id
           WHERE dr.company_id = ?""",
        (company_id,),
    ).fetchone()

    total_labor_hours = _d(labor_row["total_hours"])
    total_headcount = labor_row["total_headcount"]

    # Labor hours from cost entries
    cost_labor_row = conn.execute(
        "SELECT COALESCE(SUM(CAST(hours AS REAL)), 0) as total FROM constructclaw_cost_entry WHERE company_id = ? AND category = 'labor'",
        (company_id,),
    ).fetchone()
    cost_labor_hours = _d(cost_labor_row["total"])

    # By trade from daily labor
    by_trade = conn.execute(
        """SELECT dl.trade, SUM(dl.headcount) as total_hc, SUM(CAST(dl.hours AS REAL)) as total_hours
           FROM constructclaw_daily_labor dl
           JOIN constructclaw_daily_report dr ON dl.daily_report_id = dr.id
           WHERE dr.company_id = ?
           GROUP BY dl.trade ORDER BY total_hours DESC""",
        (company_id,),
    ).fetchall()

    trade_breakdown = [
        {
            "trade": r["trade"],
            "headcount": r["total_hc"],
            "hours": str(_d(r["total_hours"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        }
        for r in by_trade
    ]

    ok({
        "company_id": company_id,
        "daily_report_labor_hours": str(total_labor_hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "daily_report_headcount": total_headcount,
        "cost_entry_labor_hours": str(cost_labor_hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "by_trade": trade_breakdown,
    })


# ---------------------------------------------------------------------------
# status -- module status
# ---------------------------------------------------------------------------
def module_status(conn, args):
    company_id = getattr(args, "company_id", None)

    counts = {}
    tables = [
        "constructclaw_job", "constructclaw_cost_code", "constructclaw_cost_entry",
        "constructclaw_commitment", "constructclaw_estimate", "constructclaw_bid",
        "constructclaw_subcontract", "constructclaw_pay_application",
        "constructclaw_schedule_of_values", "constructclaw_progress_bill",
        "constructclaw_daily_report", "constructclaw_pco", "constructclaw_cco",
        "constructclaw_rfi", "constructclaw_submittal", "constructclaw_incident",
        "constructclaw_toolbox_talk", "constructclaw_safety_cert",
        "constructclaw_earned_value", "constructclaw_retention",
        "constructclaw_lien_waiver",
    ]

    for t in tables:
        try:
            if company_id:
                row = conn.execute(f"SELECT COUNT(*) as cnt FROM {t} WHERE company_id = ?", (company_id,)).fetchone()
            else:
                row = conn.execute(f"SELECT COUNT(*) as cnt FROM {t}").fetchone()
            counts[t] = row["cnt"]
        except Exception:
            counts[t] = 0

    ok({"skill": "constructclaw", "table_counts": counts, "total_tables": len(tables)})


# ---------------------------------------------------------------------------
# ACTIONS registry
# ---------------------------------------------------------------------------
ACTIONS = {
    "construction-add-earned-value": add_earned_value,
    "construction-list-earned-values": list_earned_values,
    "construction-calculate-ev-metrics": calculate_ev_metrics,
    "construction-schedule-variance-report": schedule_variance_report,
    "construction-cost-forecast": cost_forecast,
    "construction-project-health-dashboard": project_health_dashboard,
    "construction-resource-utilization": resource_utilization,
    "status": module_status,
}
