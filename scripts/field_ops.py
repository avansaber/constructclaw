"""ConstructClaw -- Field Operations domain module.

Equipment scheduling, certified payroll / prevailing wage, labor time tracking.
18 actions exported via ACTIONS dict.

C1: Equipment Scheduling (6 actions)
C2: Certified Payroll / Prevailing Wage (6 actions)
C3: Labor Time Tracking (6 actions)
"""
import os
import sys
import uuid
from datetime import date as _date, datetime
from decimal import Decimal, ROUND_HALF_UP

import importlib.util
if importlib.util.find_spec("erpclaw_lib") is None:
    sys.path.insert(0, os.path.join(os.path.expanduser(os.environ.get("ERPCLAW_HOME", "~/.openclaw/erpclaw")), "lib"))
from erpclaw_lib.response import ok, err, row_to_dict
from erpclaw_lib.audit import audit
from erpclaw_lib.query import (
    Q, P, Table, Field, fn, Order, insert_row, LiteralValue, dynamic_update, now as sql_now,
)

SKILL = "constructclaw"

_t_ea = Table("constructclaw_equipment_assignment")
_t_pwr = Table("constructclaw_prevailing_wage_rate")
_t_cpe = Table("constructclaw_certified_payroll_entry")
_t_te = Table("constructclaw_time_entry")
_t_job = Table("constructclaw_job")

VALID_EQUIP_STATUSES = ("scheduled", "active", "completed", "cancelled")
VALID_TIME_STATUSES = ("draft", "submitted", "approved", "rejected")
VALID_FRINGE_METHODS = ("cash", "plan")
VALID_WAGE_STATUSES = ("active", "expired")


def _d(val, default="0"):
    """Convert to Decimal safely."""
    if val is None:
        return Decimal(default)
    return Decimal(str(val))


def _require(args, *fields):
    """Validate required fields, call err() on first missing."""
    mapping = {
        "company_id": "--company-id",
        "job_id": "--job-id",
        "equipment_name": "--equipment-name",
        "start_date": "--start-date",
        "employee_name": "--employee-name",
        "trade": "--trade",
        "classification": "--classification",
        "basic_rate": "--basic-rate",
        "total_rate": "--total-rate",
        "week_ending": "--week-ending",
        "hourly_rate": "--hourly-rate",
        "gross_pay": "--gross-pay",
        "net_pay": "--net-pay",
        "work_date": "--work-date",
    }
    for f in fields:
        if not getattr(args, f, None):
            err(f"{mapping.get(f, '--' + f.replace('_', '-'))} is required")


def _check_job(conn, job_id):
    """Verify a job exists or err()."""
    row = conn.execute(
        Q.from_(_t_job).select(Field("id")).where(Field("id") == P()).get_sql(),
        (job_id,),
    ).fetchone()
    if not row:
        err(f"Job {job_id} not found")


# ===========================================================================
# C1: EQUIPMENT SCHEDULING
# ===========================================================================

# ---------------------------------------------------------------------------
# construction-assign-equipment
# ---------------------------------------------------------------------------
def assign_equipment(conn, args):
    _require(args, "company_id", "job_id", "equipment_name", "start_date")
    _check_job(conn, args.job_id)

    ea_id = str(uuid.uuid4())
    sql, _ = insert_row("constructclaw_equipment_assignment", {
        "id": P(), "job_id": P(), "equipment_name": P(), "equipment_type": P(),
        "start_date": P(), "end_date": P(), "daily_rate": P(),
        "mobilization_cost": P(), "demobilization_cost": P(),
        "actual_hours": P(), "notes": P(), "status": P(), "company_id": P(),
    })
    conn.execute(sql, (
        ea_id, args.job_id, args.equipment_name,
        getattr(args, "equipment_type", None),
        args.start_date,
        getattr(args, "end_date", None),
        str(_d(getattr(args, "daily_rate", None))),
        str(_d(getattr(args, "mobilization_cost", None))),
        str(_d(getattr(args, "demobilization_cost", None))),
        str(_d(getattr(args, "actual_hours", None))),
        getattr(args, "notes", None),
        "scheduled",
        args.company_id,
    ))
    audit(conn, SKILL, "construction-assign-equipment",
          "constructclaw_equipment_assignment", ea_id,
          new_values={"equipment_name": args.equipment_name, "job_id": args.job_id})
    conn.commit()
    ok({
        "assignment_id": ea_id, "job_id": args.job_id,
        "equipment_name": args.equipment_name, "assignment_status": "scheduled",
    })


# ---------------------------------------------------------------------------
# construction-release-equipment
# ---------------------------------------------------------------------------
def release_equipment(conn, args):
    ea_id = getattr(args, "assignment_id", None)
    if not ea_id:
        err("--assignment-id is required")

    row = conn.execute(
        Q.from_(_t_ea).select(_t_ea.star).where(_t_ea.id == P()).get_sql(),
        (ea_id,),
    ).fetchone()
    if not row:
        err(f"Equipment assignment {ea_id} not found")
    if row["status"] in ("completed", "cancelled"):
        err(f"Assignment is already {row['status']}")

    data = {"status": "completed", "updated_at": sql_now()}
    end_date = getattr(args, "end_date", None)
    if end_date:
        data["end_date"] = end_date
    actual_hours = getattr(args, "actual_hours", None)
    if actual_hours is not None:
        data["actual_hours"] = str(_d(actual_hours))

    sql, params = dynamic_update("constructclaw_equipment_assignment", data, {"id": ea_id})
    conn.execute(sql, params)
    audit(conn, SKILL, "construction-release-equipment",
          "constructclaw_equipment_assignment", ea_id,
          new_values={"assignment_status": "completed"})
    conn.commit()
    ok({"assignment_id": ea_id, "assignment_status": "completed"})


# ---------------------------------------------------------------------------
# construction-update-equipment-assignment
# ---------------------------------------------------------------------------
def update_equipment_assignment(conn, args):
    ea_id = getattr(args, "assignment_id", None)
    if not ea_id:
        err("--assignment-id is required")

    row = conn.execute(
        Q.from_(_t_ea).select(_t_ea.star).where(_t_ea.id == P()).get_sql(),
        (ea_id,),
    ).fetchone()
    if not row:
        err(f"Equipment assignment {ea_id} not found")
    if row["status"] in ("completed", "cancelled"):
        err(f"Cannot update assignment in {row['status']} status")

    data, changed = {}, []
    for field, attr in [
        ("equipment_name", "equipment_name"), ("equipment_type", "equipment_type"),
        ("start_date", "start_date"), ("end_date", "end_date"),
        ("notes", "notes"),
    ]:
        val = getattr(args, attr, None)
        if val is not None:
            data[field] = val
            changed.append(field)

    for field, attr in [
        ("daily_rate", "daily_rate"), ("mobilization_cost", "mobilization_cost"),
        ("demobilization_cost", "demobilization_cost"), ("actual_hours", "actual_hours"),
    ]:
        val = getattr(args, attr, None)
        if val is not None:
            data[field] = str(_d(val))
            changed.append(field)

    eq_status = getattr(args, "equipment_status", None)
    if eq_status:
        if eq_status not in VALID_EQUIP_STATUSES:
            err(f"Invalid status: {eq_status}")
        data["status"] = eq_status
        changed.append("status")

    if not changed:
        err("No fields to update")

    data["updated_at"] = sql_now()
    sql, params = dynamic_update("constructclaw_equipment_assignment", data, {"id": ea_id})
    conn.execute(sql, params)
    audit(conn, SKILL, "construction-update-equipment-assignment",
          "constructclaw_equipment_assignment", ea_id,
          new_values={"updated_fields": changed})
    conn.commit()
    ok({"assignment_id": ea_id, "updated_fields": changed})


# ---------------------------------------------------------------------------
# construction-list-equipment-assignments
# ---------------------------------------------------------------------------
def list_equipment_assignments(conn, args):
    t = _t_ea
    q_count = Q.from_(t).select(fn.Count("*").as_("cnt"))
    q_rows = Q.from_(t).select(t.star)
    params = []

    cid = getattr(args, "company_id", None)
    if cid:
        q_count = q_count.where(t.company_id == P())
        q_rows = q_rows.where(t.company_id == P())
        params.append(cid)
    job_id = getattr(args, "job_id", None)
    if job_id:
        q_count = q_count.where(t.job_id == P())
        q_rows = q_rows.where(t.job_id == P())
        params.append(job_id)
    st = getattr(args, "equipment_status", None)
    if st:
        q_count = q_count.where(t.status == P())
        q_rows = q_rows.where(t.status == P())
        params.append(st)
    search = getattr(args, "search", None)
    if search:
        s = f"%{search}%"
        like_crit = (t.equipment_name.like(P()) | t.equipment_type.like(P()))
        q_count = q_count.where(like_crit)
        q_rows = q_rows.where(like_crit)
        params.extend([s, s])

    limit = getattr(args, "limit", 50) or 50
    offset = getattr(args, "offset", 0) or 0

    total = conn.execute(q_count.get_sql(), params).fetchone()["cnt"]
    q_rows = q_rows.orderby(t.start_date, order=Order.desc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [limit, offset]).fetchall()
    ok({
        "equipment_assignments": [row_to_dict(r) for r in rows],
        "total_count": total, "limit": limit, "offset": offset,
    })


# ---------------------------------------------------------------------------
# construction-equipment-utilization-report
# ---------------------------------------------------------------------------
def equipment_utilization_report(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")

    conditions = ["company_id = ?"]
    params = [args.company_id]

    job_id = getattr(args, "job_id", None)
    if job_id:
        conditions.append("job_id = ?")
        params.append(job_id)

    where = f"WHERE {' AND '.join(conditions)}"
    rows = conn.execute(
        f"SELECT * FROM constructclaw_equipment_assignment {where} ORDER BY start_date DESC",
        params,
    ).fetchall()

    total_assignments = len(rows)
    by_status = {}
    total_daily_cost = Decimal("0")
    total_mob_cost = Decimal("0")
    total_demob_cost = Decimal("0")
    total_actual_hours = Decimal("0")

    for r in rows:
        st = r["status"]
        by_status[st] = by_status.get(st, 0) + 1
        total_daily_cost += _d(r["daily_rate"])
        total_mob_cost += _d(r["mobilization_cost"])
        total_demob_cost += _d(r["demobilization_cost"])
        total_actual_hours += _d(r["actual_hours"])

    # By equipment type
    by_type = {}
    for r in rows:
        et = r["equipment_type"] or "unspecified"
        by_type[et] = by_type.get(et, 0) + 1

    ok({
        "company_id": args.company_id,
        "total_assignments": total_assignments,
        "by_status": by_status,
        "by_equipment_type": by_type,
        "total_daily_rate_sum": str(total_daily_cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "total_mobilization_cost": str(total_mob_cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "total_demobilization_cost": str(total_demob_cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "total_actual_hours": str(total_actual_hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
    })


# ---------------------------------------------------------------------------
# construction-equipment-conflict-check
# ---------------------------------------------------------------------------
def equipment_conflict_check(conn, args):
    """Check if a piece of equipment is double-booked across jobs."""
    if not getattr(args, "company_id", None):
        err("--company-id is required")
    if not getattr(args, "equipment_name", None):
        err("--equipment-name is required")
    if not getattr(args, "start_date", None):
        err("--start-date is required")

    equip_name = args.equipment_name
    start = args.start_date
    end = getattr(args, "end_date", None) or start

    # Find active/scheduled assignments that overlap with the requested dates
    # Overlap: existing.start_date <= requested.end AND (existing.end_date IS NULL OR existing.end_date >= requested.start)
    rows = conn.execute(
        """SELECT * FROM constructclaw_equipment_assignment
           WHERE company_id = ? AND equipment_name = ?
           AND status IN ('scheduled','active')
           AND start_date <= ?
           AND (end_date IS NULL OR end_date >= ?)
           ORDER BY start_date""",
        (args.company_id, equip_name, end, start),
    ).fetchall()

    conflicts = [row_to_dict(r) for r in rows]
    has_conflict = len(conflicts) > 0

    ok({
        "equipment_name": equip_name,
        "requested_start": start,
        "requested_end": end,
        "has_conflict": has_conflict,
        "conflict_count": len(conflicts),
        "conflicts": conflicts,
    })


# ===========================================================================
# C2: CERTIFIED PAYROLL / PREVAILING WAGE
# ===========================================================================

# ---------------------------------------------------------------------------
# construction-add-prevailing-wage-rate
# ---------------------------------------------------------------------------
def add_prevailing_wage_rate(conn, args):
    _require(args, "company_id", "job_id", "trade", "classification",
             "basic_rate", "total_rate")
    _check_job(conn, args.job_id)

    pw_id = str(uuid.uuid4())
    sql, _ = insert_row("constructclaw_prevailing_wage_rate", {
        "id": P(), "job_id": P(), "trade": P(), "classification": P(),
        "basic_rate": P(), "fringe_rate": P(), "total_rate": P(),
        "overtime_rate": P(), "wage_determination_number": P(),
        "effective_date": P(), "status": P(), "company_id": P(),
    })
    conn.execute(sql, (
        pw_id, args.job_id, args.trade, args.classification,
        str(_d(args.basic_rate)),
        str(_d(getattr(args, "fringe_rate", None))),
        str(_d(args.total_rate)),
        getattr(args, "overtime_rate", None),
        getattr(args, "wage_determination_number", None),
        getattr(args, "effective_date", None),
        "active",
        args.company_id,
    ))
    audit(conn, SKILL, "construction-add-prevailing-wage-rate",
          "constructclaw_prevailing_wage_rate", pw_id,
          new_values={"trade": args.trade, "classification": args.classification,
                      "total_rate": str(_d(args.total_rate))})
    conn.commit()
    ok({
        "wage_rate_id": pw_id, "job_id": args.job_id,
        "trade": args.trade, "classification": args.classification,
        "total_rate": str(_d(args.total_rate)), "wage_status": "active",
    })


# ---------------------------------------------------------------------------
# construction-list-prevailing-wage-rates
# ---------------------------------------------------------------------------
def list_prevailing_wage_rates(conn, args):
    t = _t_pwr
    q = Q.from_(t).select(t.star)
    params = []

    cid = getattr(args, "company_id", None)
    if cid:
        q = q.where(t.company_id == P())
        params.append(cid)
    job_id = getattr(args, "job_id", None)
    if job_id:
        q = q.where(t.job_id == P())
        params.append(job_id)
    trade = getattr(args, "trade", None)
    if trade:
        q = q.where(t.trade == P())
        params.append(trade)
    ws = getattr(args, "wage_status", None)
    if ws:
        q = q.where(t.status == P())
        params.append(ws)

    q = q.orderby(t.trade, order=Order.asc)
    rows = conn.execute(q.get_sql(), params).fetchall()
    ok({"prevailing_wage_rates": [row_to_dict(r) for r in rows],
        "total_count": len(rows)})


# ---------------------------------------------------------------------------
# construction-add-certified-payroll-entry
# ---------------------------------------------------------------------------
def add_certified_payroll_entry(conn, args):
    _require(args, "company_id", "job_id", "week_ending", "employee_name",
             "trade", "classification", "hourly_rate", "gross_pay", "net_pay")
    _check_job(conn, args.job_id)

    # Calculate total_hours from daily hours
    daily_fields = ["mon_hours", "tue_hours", "wed_hours", "thu_hours",
                    "fri_hours", "sat_hours", "sun_hours"]
    daily_vals = [_d(getattr(args, f, None)) for f in daily_fields]
    total_hours = sum(daily_vals, Decimal("0"))

    cpe_id = str(uuid.uuid4())
    sql, _ = insert_row("constructclaw_certified_payroll_entry", {
        "id": P(), "job_id": P(), "week_ending": P(),
        "employee_name": P(), "employee_id": P(),
        "trade": P(), "classification": P(),
        "mon_hours": P(), "tue_hours": P(), "wed_hours": P(),
        "thu_hours": P(), "fri_hours": P(), "sat_hours": P(), "sun_hours": P(),
        "total_hours": P(), "overtime_hours": P(),
        "hourly_rate": P(), "gross_pay": P(),
        "fica": P(), "federal_tax": P(), "state_tax": P(),
        "other_deductions": P(), "net_pay": P(),
        "fringe_paid": P(), "fringe_method": P(), "company_id": P(),
    })

    fringe_method = getattr(args, "fringe_method", None) or "cash"
    if fringe_method not in VALID_FRINGE_METHODS:
        err(f"Invalid fringe-method: {fringe_method}. Must be 'cash' or 'plan'")

    conn.execute(sql, (
        cpe_id, args.job_id, args.week_ending,
        args.employee_name, getattr(args, "employee_id", None),
        args.trade, args.classification,
        str(daily_vals[0]), str(daily_vals[1]), str(daily_vals[2]),
        str(daily_vals[3]), str(daily_vals[4]), str(daily_vals[5]), str(daily_vals[6]),
        str(total_hours), str(_d(getattr(args, "overtime_hours", None))),
        str(_d(args.hourly_rate)), str(_d(args.gross_pay)),
        str(_d(getattr(args, "fica", None))),
        str(_d(getattr(args, "federal_tax", None))),
        str(_d(getattr(args, "state_tax", None))),
        str(_d(getattr(args, "other_deductions", None))),
        str(_d(args.net_pay)),
        str(_d(getattr(args, "fringe_paid", None))),
        fringe_method,
        args.company_id,
    ))
    audit(conn, SKILL, "construction-add-certified-payroll-entry",
          "constructclaw_certified_payroll_entry", cpe_id,
          new_values={"employee_name": args.employee_name, "week_ending": args.week_ending,
                      "gross_pay": str(_d(args.gross_pay))})
    conn.commit()
    ok({
        "payroll_entry_id": cpe_id, "job_id": args.job_id,
        "employee_name": args.employee_name,
        "week_ending": args.week_ending,
        "total_hours": str(total_hours),
        "gross_pay": str(_d(args.gross_pay)),
        "net_pay": str(_d(args.net_pay)),
    })


# ---------------------------------------------------------------------------
# construction-list-certified-payroll
# ---------------------------------------------------------------------------
def list_certified_payroll(conn, args):
    t = _t_cpe
    q = Q.from_(t).select(t.star)
    params = []

    cid = getattr(args, "company_id", None)
    if cid:
        q = q.where(t.company_id == P())
        params.append(cid)
    job_id = getattr(args, "job_id", None)
    if job_id:
        q = q.where(t.job_id == P())
        params.append(job_id)
    week = getattr(args, "week_ending", None)
    if week:
        q = q.where(t.week_ending == P())
        params.append(week)

    q = q.orderby(t.week_ending, order=Order.desc)
    rows = conn.execute(q.get_sql(), params).fetchall()
    ok({"certified_payroll_entries": [row_to_dict(r) for r in rows],
        "total_count": len(rows)})


# ---------------------------------------------------------------------------
# construction-generate-wh347
# ---------------------------------------------------------------------------
def generate_wh347(conn, args):
    """Generate WH-347 report data for a project and week ending date."""
    _require(args, "company_id", "job_id", "week_ending")

    job = conn.execute(
        Q.from_(_t_job).select(_t_job.star).where(_t_job.id == P()).get_sql(),
        (args.job_id,),
    ).fetchone()
    if not job:
        err(f"Job {args.job_id} not found")

    entries = conn.execute(
        Q.from_(_t_cpe).select(_t_cpe.star)
        .where(_t_cpe.job_id == P())
        .where(_t_cpe.week_ending == P())
        .orderby(_t_cpe.employee_name).get_sql(),
        (args.job_id, args.week_ending),
    ).fetchall()

    total_gross = Decimal("0")
    total_net = Decimal("0")
    total_fica = Decimal("0")
    total_federal = Decimal("0")
    total_state = Decimal("0")
    total_other = Decimal("0")
    total_fringe = Decimal("0")
    total_hours = Decimal("0")

    entry_list = []
    for e in entries:
        d = row_to_dict(e)
        total_gross += _d(e["gross_pay"])
        total_net += _d(e["net_pay"])
        total_fica += _d(e["fica"])
        total_federal += _d(e["federal_tax"])
        total_state += _d(e["state_tax"])
        total_other += _d(e["other_deductions"])
        total_fringe += _d(e["fringe_paid"])
        total_hours += _d(e["total_hours"])
        entry_list.append(d)

    ok({
        "report": "WH-347 Certified Payroll",
        "job_id": args.job_id,
        "job_name": job["name"],
        "week_ending": args.week_ending,
        "contractor": job["client_name"] or "N/A",
        "entry_count": len(entry_list),
        "entries": entry_list,
        "totals": {
            "total_hours": str(total_hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "total_gross_pay": str(total_gross.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "total_fica": str(total_fica.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "total_federal_tax": str(total_federal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "total_state_tax": str(total_state.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "total_other_deductions": str(total_other.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "total_net_pay": str(total_net.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "total_fringe_paid": str(total_fringe.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        },
    })


# ---------------------------------------------------------------------------
# construction-certified-payroll-summary
# ---------------------------------------------------------------------------
def certified_payroll_summary(conn, args):
    """Summary of certified payroll across weeks for a project."""
    _require(args, "company_id", "job_id")

    rows = conn.execute(
        """SELECT week_ending,
                  COUNT(*) as employee_count,
                  SUM(CAST(total_hours AS REAL)) as total_hours,
                  SUM(CAST(gross_pay AS REAL)) as total_gross,
                  SUM(CAST(net_pay AS REAL)) as total_net,
                  SUM(CAST(fringe_paid AS REAL)) as total_fringe
           FROM constructclaw_certified_payroll_entry
           WHERE job_id = ? AND company_id = ?
           GROUP BY week_ending
           ORDER BY week_ending DESC""",
        (args.job_id, args.company_id),
    ).fetchall()

    weeks = []
    grand_hours = Decimal("0")
    grand_gross = Decimal("0")
    grand_net = Decimal("0")
    grand_fringe = Decimal("0")

    for r in rows:
        h = _d(r["total_hours"])
        g = _d(r["total_gross"])
        n = _d(r["total_net"])
        f = _d(r["total_fringe"])
        grand_hours += h
        grand_gross += g
        grand_net += n
        grand_fringe += f
        weeks.append({
            "week_ending": r["week_ending"],
            "employee_count": r["employee_count"],
            "total_hours": str(h.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "total_gross_pay": str(g.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "total_net_pay": str(n.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "total_fringe": str(f.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        })

    ok({
        "job_id": args.job_id,
        "total_weeks": len(weeks),
        "weeks": weeks,
        "grand_totals": {
            "total_hours": str(grand_hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "total_gross_pay": str(grand_gross.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "total_net_pay": str(grand_net.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "total_fringe": str(grand_fringe.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        },
    })


# ===========================================================================
# C3: LABOR TIME TRACKING
# ===========================================================================

# ---------------------------------------------------------------------------
# construction-add-time-entry
# ---------------------------------------------------------------------------
def add_time_entry(conn, args):
    _require(args, "company_id", "job_id", "employee_name", "work_date")
    _check_job(conn, args.job_id)

    regular = _d(getattr(args, "regular_hours", None))
    ot = _d(getattr(args, "overtime_hours", None))
    dt = _d(getattr(args, "double_time_hours", None))
    total = regular + ot + dt
    rate = _d(getattr(args, "hourly_rate", None))

    # Cost = (regular * rate) + (overtime * rate * 1.5) + (double_time * rate * 2)
    ot_mult = Decimal("1.5")
    dt_mult = Decimal("2")
    cost = (regular * rate) + (ot * rate * ot_mult) + (dt * rate * dt_mult)

    te_id = str(uuid.uuid4())
    sql, _ = insert_row("constructclaw_time_entry", {
        "id": P(), "job_id": P(), "cost_code_id": P(),
        "employee_name": P(), "employee_id": P(), "trade": P(),
        "work_date": P(), "regular_hours": P(), "overtime_hours": P(),
        "double_time_hours": P(), "total_hours": P(),
        "hourly_rate": P(), "total_cost": P(),
        "description": P(), "status": P(), "company_id": P(),
    })
    conn.execute(sql, (
        te_id, args.job_id,
        getattr(args, "cost_code_id", None),
        args.employee_name,
        getattr(args, "employee_id", None),
        getattr(args, "trade", None),
        args.work_date,
        str(regular), str(ot), str(dt), str(total),
        str(rate),
        str(cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        getattr(args, "description", None),
        "draft",
        args.company_id,
    ))
    audit(conn, SKILL, "construction-add-time-entry",
          "constructclaw_time_entry", te_id,
          new_values={"employee_name": args.employee_name, "work_date": args.work_date,
                      "total_hours": str(total)})
    conn.commit()
    ok({
        "time_entry_id": te_id, "job_id": args.job_id,
        "employee_name": args.employee_name,
        "work_date": args.work_date,
        "total_hours": str(total),
        "total_cost": str(cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "time_status": "draft",
    })


# ---------------------------------------------------------------------------
# construction-list-time-entries
# ---------------------------------------------------------------------------
def list_time_entries(conn, args):
    t = _t_te
    q_count = Q.from_(t).select(fn.Count("*").as_("cnt"))
    q_rows = Q.from_(t).select(t.star)
    params = []

    cid = getattr(args, "company_id", None)
    if cid:
        q_count = q_count.where(t.company_id == P())
        q_rows = q_rows.where(t.company_id == P())
        params.append(cid)
    job_id = getattr(args, "job_id", None)
    if job_id:
        q_count = q_count.where(t.job_id == P())
        q_rows = q_rows.where(t.job_id == P())
        params.append(job_id)
    emp = getattr(args, "employee_name", None)
    if emp:
        q_count = q_count.where(t.employee_name == P())
        q_rows = q_rows.where(t.employee_name == P())
        params.append(emp)
    st = getattr(args, "time_status", None)
    if st:
        q_count = q_count.where(t.status == P())
        q_rows = q_rows.where(t.status == P())
        params.append(st)
    search = getattr(args, "search", None)
    if search:
        s = f"%{search}%"
        like_crit = (t.employee_name.like(P()) | t.description.like(P()))
        q_count = q_count.where(like_crit)
        q_rows = q_rows.where(like_crit)
        params.extend([s, s])

    limit = getattr(args, "limit", 50) or 50
    offset = getattr(args, "offset", 0) or 0

    total = conn.execute(q_count.get_sql(), params).fetchone()["cnt"]
    q_rows = q_rows.orderby(t.work_date, order=Order.desc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [limit, offset]).fetchall()
    ok({
        "time_entries": [row_to_dict(r) for r in rows],
        "total_count": total, "limit": limit, "offset": offset,
    })


# ---------------------------------------------------------------------------
# construction-approve-time-entry
# ---------------------------------------------------------------------------
def approve_time_entry(conn, args):
    te_id = getattr(args, "time_entry_id", None)
    if not te_id:
        err("--time-entry-id is required")

    row = conn.execute(
        Q.from_(_t_te).select(_t_te.star).where(_t_te.id == P()).get_sql(),
        (te_id,),
    ).fetchone()
    if not row:
        err(f"Time entry {te_id} not found")
    if row["status"] not in ("draft", "submitted"):
        err(f"Time entry must be in draft or submitted status to approve (current: {row['status']})")

    data = {
        "status": "approved",
        "approved_at": sql_now(),
    }
    approver = getattr(args, "approved_by", None)
    if approver:
        data["approved_by"] = approver

    sql, params = dynamic_update("constructclaw_time_entry", data, {"id": te_id})
    conn.execute(sql, params)
    audit(conn, SKILL, "construction-approve-time-entry",
          "constructclaw_time_entry", te_id,
          new_values={"time_status": "approved"})
    conn.commit()
    ok({"time_entry_id": te_id, "time_status": "approved"})


# ---------------------------------------------------------------------------
# construction-reject-time-entry
# ---------------------------------------------------------------------------
def reject_time_entry(conn, args):
    te_id = getattr(args, "time_entry_id", None)
    if not te_id:
        err("--time-entry-id is required")

    row = conn.execute(
        Q.from_(_t_te).select(_t_te.star).where(_t_te.id == P()).get_sql(),
        (te_id,),
    ).fetchone()
    if not row:
        err(f"Time entry {te_id} not found")
    if row["status"] not in ("draft", "submitted"):
        err(f"Time entry must be in draft or submitted status to reject (current: {row['status']})")

    data = {"status": "rejected"}
    reason = getattr(args, "notes", None)
    if reason:
        data["description"] = reason

    sql, params = dynamic_update("constructclaw_time_entry", data, {"id": te_id})
    conn.execute(sql, params)
    audit(conn, SKILL, "construction-reject-time-entry",
          "constructclaw_time_entry", te_id,
          new_values={"time_status": "rejected"})
    conn.commit()
    ok({"time_entry_id": te_id, "time_status": "rejected"})


# ---------------------------------------------------------------------------
# construction-time-entry-summary
# ---------------------------------------------------------------------------
def time_entry_summary(conn, args):
    """Summary of time entries by employee for a project."""
    _require(args, "company_id", "job_id")

    rows = conn.execute(
        """SELECT employee_name, trade,
                  SUM(CAST(regular_hours AS REAL)) as total_regular,
                  SUM(CAST(overtime_hours AS REAL)) as total_ot,
                  SUM(CAST(double_time_hours AS REAL)) as total_dt,
                  SUM(CAST(total_hours AS REAL)) as total_hours,
                  SUM(CAST(total_cost AS REAL)) as total_cost,
                  COUNT(*) as entry_count
           FROM constructclaw_time_entry
           WHERE job_id = ? AND company_id = ?
           GROUP BY employee_name, trade
           ORDER BY employee_name""",
        (args.job_id, args.company_id),
    ).fetchall()

    employees = []
    grand_hours = Decimal("0")
    grand_cost = Decimal("0")

    for r in rows:
        h = _d(r["total_hours"])
        c = _d(r["total_cost"])
        grand_hours += h
        grand_cost += c
        employees.append({
            "employee_name": r["employee_name"],
            "trade": r["trade"],
            "regular_hours": str(_d(r["total_regular"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "overtime_hours": str(_d(r["total_ot"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "double_time_hours": str(_d(r["total_dt"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "total_hours": str(h.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "total_cost": str(c.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "entry_count": r["entry_count"],
        })

    ok({
        "job_id": args.job_id,
        "employee_count": len(employees),
        "employees": employees,
        "grand_total_hours": str(grand_hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "grand_total_cost": str(grand_cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
    })


# ---------------------------------------------------------------------------
# construction-labor-cost-report
# ---------------------------------------------------------------------------
def labor_cost_report(conn, args):
    """Labor cost report by trade and date range for a project."""
    _require(args, "company_id", "job_id")

    conditions = ["job_id = ?", "company_id = ?"]
    params = [args.job_id, args.company_id]

    start_date = getattr(args, "start_date", None)
    if start_date:
        conditions.append("work_date >= ?")
        params.append(start_date)
    end_date = getattr(args, "end_date", None)
    if end_date:
        conditions.append("work_date <= ?")
        params.append(end_date)

    where = f"WHERE {' AND '.join(conditions)}"

    # By trade
    by_trade = conn.execute(
        f"""SELECT trade,
                   SUM(CAST(regular_hours AS REAL)) as regular_hours,
                   SUM(CAST(overtime_hours AS REAL)) as overtime_hours,
                   SUM(CAST(double_time_hours AS REAL)) as double_time_hours,
                   SUM(CAST(total_hours AS REAL)) as total_hours,
                   SUM(CAST(total_cost AS REAL)) as total_cost,
                   COUNT(*) as entry_count
            FROM constructclaw_time_entry
            {where}
            GROUP BY trade
            ORDER BY total_cost DESC""",
        params,
    ).fetchall()

    trades = []
    grand_hours = Decimal("0")
    grand_cost = Decimal("0")

    for r in by_trade:
        h = _d(r["total_hours"])
        c = _d(r["total_cost"])
        grand_hours += h
        grand_cost += c
        trades.append({
            "trade": r["trade"] or "unspecified",
            "regular_hours": str(_d(r["regular_hours"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "overtime_hours": str(_d(r["overtime_hours"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "double_time_hours": str(_d(r["double_time_hours"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "total_hours": str(h.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "total_cost": str(c.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "entry_count": r["entry_count"],
        })

    # By date
    by_date = conn.execute(
        f"""SELECT work_date,
                   SUM(CAST(total_hours AS REAL)) as total_hours,
                   SUM(CAST(total_cost AS REAL)) as total_cost,
                   COUNT(*) as entry_count
            FROM constructclaw_time_entry
            {where}
            GROUP BY work_date
            ORDER BY work_date DESC""",
        params,
    ).fetchall()

    dates = []
    for r in by_date:
        dates.append({
            "work_date": r["work_date"],
            "total_hours": str(_d(r["total_hours"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "total_cost": str(_d(r["total_cost"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "entry_count": r["entry_count"],
        })

    ok({
        "job_id": args.job_id,
        "by_trade": trades,
        "by_date": dates,
        "grand_total_hours": str(grand_hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "grand_total_cost": str(grand_cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
    })


# ---------------------------------------------------------------------------
# ACTIONS registry
# ---------------------------------------------------------------------------
ACTIONS = {
    # C1: Equipment Scheduling
    "construction-assign-equipment": assign_equipment,
    "construction-release-equipment": release_equipment,
    "construction-update-equipment-assignment": update_equipment_assignment,
    "construction-list-equipment-assignments": list_equipment_assignments,
    "construction-equipment-utilization-report": equipment_utilization_report,
    "construction-equipment-conflict-check": equipment_conflict_check,
    # C2: Certified Payroll / Prevailing Wage
    "construction-add-prevailing-wage-rate": add_prevailing_wage_rate,
    "construction-list-prevailing-wage-rates": list_prevailing_wage_rates,
    "construction-add-certified-payroll-entry": add_certified_payroll_entry,
    "construction-list-certified-payroll": list_certified_payroll,
    "construction-generate-wh347": generate_wh347,
    "construction-certified-payroll-summary": certified_payroll_summary,
    # C3: Labor Time Tracking
    "construction-add-time-entry": add_time_entry,
    "construction-list-time-entries": list_time_entries,
    "construction-approve-time-entry": approve_time_entry,
    "construction-reject-time-entry": reject_time_entry,
    "construction-time-entry-summary": time_entry_summary,
    "construction-labor-cost-report": labor_cost_report,
}
