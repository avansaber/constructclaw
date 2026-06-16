"""ConstructClaw -- Daily Reports domain module.

Daily field reports: labor, materials, weather, delays.
10 actions exported via ACTIONS dict.
"""
import os
import sys
import uuid
from datetime import date as _date
from decimal import Decimal, ROUND_HALF_UP

sys.path.insert(0, os.path.join(os.path.expanduser(os.environ.get("ERPCLAW_HOME", "~/.openclaw/erpclaw")), "lib"))
from erpclaw_lib.naming import get_next_name, register_prefix
from erpclaw_lib.response import ok, err, row_to_dict
from erpclaw_lib.audit import audit
from erpclaw_lib.query import Q, P, Table, Field, fn, Order, insert_row, LiteralValue, dynamic_update

SKILL = "constructclaw"

_t_dr = Table("constructclaw_daily_report")
_t_dl = Table("constructclaw_daily_labor")
_t_dm = Table("constructclaw_daily_material")

register_prefix("constructclaw_daily_report", "CCDR-")

VALID_REPORT_STATUSES = ("draft", "submitted", "approved")


def _d(val, default="0"):
    if val is None:
        return Decimal(default)
    return Decimal(str(val))


# ---------------------------------------------------------------------------
# add-daily-report
# ---------------------------------------------------------------------------
def add_daily_report(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")
    job_id = getattr(args, "job_id", None)
    if not job_id:
        err("--job-id is required")

    if not conn.execute(Q.from_(Table("constructclaw_job")).select(Field("id")).where(Field("id") == P()).get_sql(), (job_id,)).fetchone():
        err(f"Job {job_id} not found")

    dr_id = str(uuid.uuid4())
    ns = get_next_name(conn, "constructclaw_daily_report", company_id=args.company_id)

    sql, _ = insert_row("constructclaw_daily_report", {"id": P(), "naming_series": P(), "job_id": P(), "report_date": P(), "superintendent": P(), "weather": P(), "temperature_high": P(), "temperature_low": P(), "work_description": P(), "delays": P(), "visitors": P(), "notes": P(), "company_id": P()})


    conn.execute(sql,
        (
            dr_id, ns, job_id,
            getattr(args, "report_date", None) or _date.today().isoformat(),
            getattr(args, "superintendent", None),
            getattr(args, "weather", None),
            getattr(args, "temperature_high", None),
            getattr(args, "temperature_low", None),
            getattr(args, "work_description", None),
            getattr(args, "delays", None),
            getattr(args, "visitors", None),
            getattr(args, "notes", None),
            args.company_id,
        ),
    )
    audit(conn, SKILL, "construction-add-daily-report", "constructclaw_daily_report", dr_id,
          new_values={"naming_series": ns, "job_id": job_id})
    conn.commit()
    ok({"daily_report_id": dr_id, "naming_series": ns, "job_id": job_id,
        "report_status": "draft"})


# ---------------------------------------------------------------------------
# update-daily-report
# ---------------------------------------------------------------------------
def update_daily_report(conn, args):
    dr_id = getattr(args, "daily_report_id", None)
    if not dr_id:
        err("--daily-report-id is required")
    row = conn.execute(Q.from_(_t_dr).select(_t_dr.star).where(_t_dr.id == P()).get_sql(), (dr_id,)).fetchone()
    if not row:
        err(f"Daily report {dr_id} not found")
    if row["report_status"] != "draft":
        err(f"Daily report must be in draft status to update (current: {row['report_status']})")

    data, changed = {}, []
    for field, attr in [
        ("report_date", "report_date"), ("superintendent", "superintendent"),
        ("weather", "weather"), ("temperature_high", "temperature_high"),
        ("temperature_low", "temperature_low"), ("work_description", "work_description"),
        ("delays", "delays"), ("visitors", "visitors"), ("notes", "notes"),
    ]:
        val = getattr(args, attr, None)
        if val is not None:
            data[field] = val
            changed.append(field)

    if not changed:
        err("No fields to update")

    data["updated_at"] = LiteralValue("datetime('now')")
    sql, params = dynamic_update("constructclaw_daily_report", data, {"id": dr_id})
    conn.execute(sql, params)
    audit(conn, SKILL, "construction-update-daily-report", "constructclaw_daily_report", dr_id,
          new_values={"updated_fields": changed})
    conn.commit()
    ok({"daily_report_id": dr_id, "updated_fields": changed})


# ---------------------------------------------------------------------------
# get-daily-report
# ---------------------------------------------------------------------------
def get_daily_report(conn, args):
    dr_id = getattr(args, "daily_report_id", None)
    if not dr_id:
        err("--daily-report-id is required")
    row = conn.execute(Q.from_(_t_dr).select(_t_dr.star).where(_t_dr.id == P()).get_sql(), (dr_id,)).fetchone()
    if not row:
        err(f"Daily report {dr_id} not found")

    data = row_to_dict(row)

    # Attach labor entries
    q = Q.from_(_t_dl).select(_t_dl.star).where(_t_dl.daily_report_id == P()).orderby(_t_dl.created_at)
    labor = conn.execute(q.get_sql(), (dr_id,)).fetchall()
    data["labor_entries"] = [row_to_dict(l) for l in labor]

    # Attach material deliveries
    q = Q.from_(_t_dm).select(_t_dm.star).where(_t_dm.daily_report_id == P()).orderby(_t_dm.created_at)
    materials = conn.execute(q.get_sql(), (dr_id,)).fetchall()
    data["material_entries"] = [row_to_dict(m) for m in materials]

    ok(data)


# ---------------------------------------------------------------------------
# list-daily-reports
# ---------------------------------------------------------------------------
def list_daily_reports(conn, args):
    t = _t_dr
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
    rs = getattr(args, "report_status", None)
    if rs:
        q_count = q_count.where(t.report_status == P())
        q_rows = q_rows.where(t.report_status == P())
        params.append(rs)
    search = getattr(args, "search", None)
    if search:
        s = f"%{search}%"
        like_crit = (t.superintendent.like(P()) | t.work_description.like(P()) | t.notes.like(P()))
        q_count = q_count.where(like_crit)
        q_rows = q_rows.where(like_crit)
        params.extend([s] * 3)

    limit = getattr(args, "limit", 50) or 50
    offset = getattr(args, "offset", 0) or 0

    total = conn.execute(q_count.get_sql(), params).fetchone()["cnt"]
    q_rows = q_rows.orderby(t.report_date, order=Order.desc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [limit, offset]).fetchall()
    ok({"daily_reports": [row_to_dict(r) for r in rows], "total_count": total,
        "limit": limit, "offset": offset})


# ---------------------------------------------------------------------------
# submit-daily-report
# ---------------------------------------------------------------------------
def submit_daily_report(conn, args):
    dr_id = getattr(args, "daily_report_id", None)
    if not dr_id:
        err("--daily-report-id is required")
    row = conn.execute(Q.from_(_t_dr).select(_t_dr.star).where(_t_dr.id == P()).get_sql(), (dr_id,)).fetchone()
    if not row:
        err(f"Daily report {dr_id} not found")
    if row["report_status"] != "draft":
        err(f"Daily report must be in draft status to submit (current: {row['report_status']})")

    sql, params = dynamic_update("constructclaw_daily_report",
        {"report_status": "submitted", "updated_at": LiteralValue("datetime('now')")},
        {"id": dr_id})
    conn.execute(sql, params)
    audit(conn, SKILL, "construction-submit-daily-report", "constructclaw_daily_report", dr_id,
          new_values={"report_status": "submitted"})
    conn.commit()
    ok({"daily_report_id": dr_id, "report_status": "submitted"})


# ---------------------------------------------------------------------------
# add-daily-labor
# ---------------------------------------------------------------------------
def add_daily_labor(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")
    dr_id = getattr(args, "daily_report_id", None)
    if not dr_id:
        err("--daily-report-id is required")
    if not getattr(args, "trade", None):
        err("--trade is required")

    if not conn.execute(Q.from_(Table("constructclaw_daily_report")).select(Field("id")).where(Field("id") == P()).get_sql(), (dr_id,)).fetchone():
        err(f"Daily report {dr_id} not found")

    lab_id = str(uuid.uuid4())
    sql, _ = insert_row("constructclaw_daily_labor", {"id": P(), "daily_report_id": P(), "trade": P(), "headcount": P(), "hours": P(), "description": P(), "company_id": P()})

    conn.execute(sql,
        (
            lab_id, dr_id,
            args.trade,
            int(getattr(args, "headcount", None) or 0),
            getattr(args, "hours", None) or "0",
            getattr(args, "description", None),
            args.company_id,
        ),
    )
    conn.commit()
    ok({"daily_labor_id": lab_id, "daily_report_id": dr_id, "trade": args.trade})


# ---------------------------------------------------------------------------
# list-daily-labor
# ---------------------------------------------------------------------------
def list_daily_labor(conn, args):
    dr_id = getattr(args, "daily_report_id", None)
    if not dr_id:
        err("--daily-report-id is required")

    q = Q.from_(_t_dl).select(_t_dl.star).where(_t_dl.daily_report_id == P()).orderby(_t_dl.created_at)
    rows = conn.execute(q.get_sql(), (dr_id,)).fetchall()
    ok({"daily_labor": [row_to_dict(r) for r in rows], "total_count": len(rows)})


# ---------------------------------------------------------------------------
# add-daily-material
# ---------------------------------------------------------------------------
def add_daily_material(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")
    dr_id = getattr(args, "daily_report_id", None)
    if not dr_id:
        err("--daily-report-id is required")
    if not getattr(args, "material_name", None):
        err("--material-name is required")

    if not conn.execute(Q.from_(Table("constructclaw_daily_report")).select(Field("id")).where(Field("id") == P()).get_sql(), (dr_id,)).fetchone():
        err(f"Daily report {dr_id} not found")

    mat_id = str(uuid.uuid4())
    sql, _ = insert_row("constructclaw_daily_material", {"id": P(), "daily_report_id": P(), "material_name": P(), "quantity": P(), "unit": P(), "supplier": P(), "delivery_ticket": P(), "company_id": P()})

    conn.execute(sql,
        (
            mat_id, dr_id,
            args.material_name,
            getattr(args, "quantity", None) or "0",
            getattr(args, "unit", None) or "ea",
            getattr(args, "supplier", None),
            getattr(args, "delivery_ticket", None),
            args.company_id,
        ),
    )
    conn.commit()
    ok({"daily_material_id": mat_id, "daily_report_id": dr_id,
        "material_name": args.material_name})


# ---------------------------------------------------------------------------
# list-daily-materials
# ---------------------------------------------------------------------------
def list_daily_materials(conn, args):
    dr_id = getattr(args, "daily_report_id", None)
    if not dr_id:
        err("--daily-report-id is required")

    q = Q.from_(_t_dm).select(_t_dm.star).where(_t_dm.daily_report_id == P()).orderby(_t_dm.created_at)
    rows = conn.execute(q.get_sql(), (dr_id,)).fetchall()
    ok({"daily_materials": [row_to_dict(r) for r in rows], "total_count": len(rows)})


# ---------------------------------------------------------------------------
# daily-summary
# ---------------------------------------------------------------------------
def daily_summary(conn, args):
    job_id = getattr(args, "job_id", None)
    if not job_id:
        err("--job-id is required")

    reports = conn.execute(
        "SELECT * FROM constructclaw_daily_report WHERE job_id = ? ORDER BY report_date DESC",
        (job_id,),
    ).fetchall()

    total_labor_hours = Decimal("0")
    total_headcount = 0
    total_material_deliveries = 0

    for r in reports:
        labor = conn.execute(
            "SELECT COALESCE(SUM(CAST(hours AS REAL)), 0) as total_hours, COALESCE(SUM(headcount), 0) as total_hc FROM constructclaw_daily_labor WHERE daily_report_id = ?",
            (r["id"],),
        ).fetchone()
        total_labor_hours += _d(labor["total_hours"])
        total_headcount += labor["total_hc"]

        mat_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM constructclaw_daily_material WHERE daily_report_id = ?",
            (r["id"],),
        ).fetchone()["cnt"]
        total_material_deliveries += mat_count

    ok({
        "job_id": job_id,
        "total_reports": len(reports),
        "total_labor_hours": str(total_labor_hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "total_headcount": total_headcount,
        "total_material_deliveries": total_material_deliveries,
    })


# ---------------------------------------------------------------------------
# ACTIONS registry
# ---------------------------------------------------------------------------
ACTIONS = {
    "construction-add-daily-report": add_daily_report,
    "construction-update-daily-report": update_daily_report,
    "construction-get-daily-report": get_daily_report,
    "construction-list-daily-reports": list_daily_reports,
    "construction-submit-daily-report": submit_daily_report,
    "construction-add-daily-labor": add_daily_labor,
    "construction-list-daily-labor": list_daily_labor,
    "construction-add-daily-material": add_daily_material,
    "construction-list-daily-materials": list_daily_materials,
    "construction-daily-summary": daily_summary,
}
