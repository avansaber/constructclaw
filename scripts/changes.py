"""ConstructClaw -- Change Orders domain module.

Potential change orders (PCOs) and contract change orders (CCOs).
10 actions exported via ACTIONS dict.
"""
import os
import sys
import uuid
from decimal import Decimal, ROUND_HALF_UP

sys.path.insert(0, os.path.expanduser("~/.openclaw/erpclaw/lib"))
from erpclaw_lib.naming import get_next_name, register_prefix
from erpclaw_lib.response import ok, err, row_to_dict
from erpclaw_lib.audit import audit
from erpclaw_lib.query import Q, P, Table, Field, fn, Order, insert_row, LiteralValue, dynamic_update

SKILL = "constructclaw"

_t_pco = Table("constructclaw_pco")
_t_cco = Table("constructclaw_cco")
_t_job = Table("constructclaw_job")

register_prefix("constructclaw_pco", "CCPCO-")
register_prefix("constructclaw_cco", "CCCCO-")

VALID_PCO_STATUSES = ("identified", "pricing", "submitted", "approved", "rejected", "void")
VALID_CCO_STATUSES = ("draft", "pending", "approved", "executed", "rejected", "void")


def _d(val, default="0"):
    if val is None:
        return Decimal(default)
    return Decimal(str(val))


# ---------------------------------------------------------------------------
# add-pco
# ---------------------------------------------------------------------------
def add_pco(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")
    job_id = getattr(args, "job_id", None)
    if not job_id:
        err("--job-id is required")
    if not getattr(args, "title", None):
        err("--title is required")

    if not conn.execute(Q.from_(Table("constructclaw_job")).select(Field("id")).where(Field("id") == P()).get_sql(), (job_id,)).fetchone():
        err(f"Job {job_id} not found")

    pco_id = str(uuid.uuid4())
    ns = get_next_name(conn, "constructclaw_pco", company_id=args.company_id)

    sql, _ = insert_row("constructclaw_pco", {"id": P(), "naming_series": P(), "pco_number": P(), "job_id": P(), "title": P(), "description": P(), "reason": P(), "cost_impact": P(), "time_impact_days": P(), "requested_by": P(), "notes": P(), "company_id": P()})


    conn.execute(sql,
        (
            pco_id, ns, ns, job_id,
            args.title,
            getattr(args, "description", None),
            getattr(args, "reason", None),
            getattr(args, "cost_impact", None) or "0",
            int(getattr(args, "time_impact_days", None) or 0),
            getattr(args, "requested_by", None),
            getattr(args, "notes", None),
            args.company_id,
        ),
    )
    audit(conn, SKILL, "construction-add-pco", "constructclaw_pco", pco_id,
          new_values={"naming_series": ns, "title": args.title})
    conn.commit()
    ok({"pco_id": pco_id, "naming_series": ns, "title": args.title,
        "pco_status": "identified"})


# ---------------------------------------------------------------------------
# update-pco
# ---------------------------------------------------------------------------
def update_pco(conn, args):
    pco_id = getattr(args, "pco_id", None)
    if not pco_id:
        err("--pco-id is required")
    row = conn.execute(Q.from_(_t_pco).select(_t_pco.star).where(_t_pco.id == P()).get_sql(), (pco_id,)).fetchone()
    if not row:
        err(f"PCO {pco_id} not found")

    data, changed = {}, []
    for field, attr in [
        ("title", "title"), ("description", "description"),
        ("reason", "reason"), ("cost_impact", "cost_impact"),
        ("requested_by", "requested_by"), ("notes", "notes"),
    ]:
        val = getattr(args, attr, None)
        if val is not None:
            data[field] = val
            changed.append(field)

    tid = getattr(args, "time_impact_days", None)
    if tid is not None:
        data["time_impact_days"] = int(tid)
        changed.append("time_impact_days")

    ps = getattr(args, "pco_status", None)
    if ps is not None:
        if ps not in VALID_PCO_STATUSES:
            err(f"Invalid pco-status: {ps}")
        data["pco_status"] = ps
        changed.append("pco_status")

    if not changed:
        err("No fields to update")

    data["updated_at"] = LiteralValue("datetime('now')")
    sql, params = dynamic_update("constructclaw_pco", data, {"id": pco_id})
    conn.execute(sql, params)
    audit(conn, SKILL, "construction-update-pco", "constructclaw_pco", pco_id,
          new_values={"updated_fields": changed})
    conn.commit()
    ok({"pco_id": pco_id, "updated_fields": changed})


# ---------------------------------------------------------------------------
# get-pco
# ---------------------------------------------------------------------------
def get_pco(conn, args):
    pco_id = getattr(args, "pco_id", None)
    if not pco_id:
        err("--pco-id is required")
    row = conn.execute(Q.from_(Table("constructclaw_pco")).select(Table("constructclaw_pco").star).where(Field("id") == P()).get_sql(), (pco_id,)).fetchone()
    if not row:
        err(f"PCO {pco_id} not found")
    ok(row_to_dict(row))


# ---------------------------------------------------------------------------
# list-pcos
# ---------------------------------------------------------------------------
def list_pcos(conn, args):
    t = _t_pco
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
    ps = getattr(args, "pco_status", None)
    if ps:
        q_count = q_count.where(t.pco_status == P())
        q_rows = q_rows.where(t.pco_status == P())
        params.append(ps)
    search = getattr(args, "search", None)
    if search:
        s = f"%{search}%"
        like_crit = (t.title.like(P()) | t.description.like(P()))
        q_count = q_count.where(like_crit)
        q_rows = q_rows.where(like_crit)
        params.extend([s] * 2)

    limit = getattr(args, "limit", 50) or 50
    offset = getattr(args, "offset", 0) or 0

    total = conn.execute(q_count.get_sql(), params).fetchone()["cnt"]
    q_rows = q_rows.orderby(t.created_at, order=Order.desc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [limit, offset]).fetchall()
    ok({"pcos": [row_to_dict(r) for r in rows], "total_count": total,
        "limit": limit, "offset": offset})


# ---------------------------------------------------------------------------
# approve-pco -- convert PCO to CCO
# ---------------------------------------------------------------------------
def approve_pco(conn, args):
    pco_id = getattr(args, "pco_id", None)
    if not pco_id:
        err("--pco-id is required")
    pco = conn.execute(Q.from_(_t_pco).select(_t_pco.star).where(_t_pco.id == P()).get_sql(), (pco_id,)).fetchone()
    if not pco:
        err(f"PCO {pco_id} not found")
    if pco["pco_status"] not in ("identified", "pricing", "submitted"):
        err(f"PCO must be identified/pricing/submitted to approve (current: {pco['pco_status']})")

    # Update PCO status
    sql, params = dynamic_update("constructclaw_pco",
        {"pco_status": "approved", "updated_at": LiteralValue("datetime('now')")},
        {"id": pco_id})
    conn.execute(sql, params)

    # Create CCO from PCO
    cco_id = str(uuid.uuid4())
    ns = get_next_name(conn, "constructclaw_cco", company_id=pco["company_id"])

    # Get current contract amount for job
    q = Q.from_(_t_job).select(_t_job.contract_amount).where(_t_job.id == P())
    job = conn.execute(q.get_sql(), (pco["job_id"],)).fetchone()
    current_contract = _d(job["contract_amount"]) if job else Decimal("0")

    # Sum existing approved CCOs
    # PyPika: skipped — CAST inside COALESCE/SUM aggregate with IN clause
    existing_cos = conn.execute(
        "SELECT COALESCE(SUM(CAST(cost_change AS REAL)), 0) as total FROM constructclaw_cco WHERE job_id = ? AND cco_status IN ('approved','executed')",
        (pco["job_id"],),
    ).fetchone()
    existing_total = _d(existing_cos["total"])

    cost_change = _d(pco["cost_impact"])
    new_contract = current_contract + existing_total + cost_change

    sql, _ = insert_row("constructclaw_cco", {"id": P(), "naming_series": P(), "cco_number": P(), "job_id": P(), "pco_id": P(), "title": P(), "description": P(), "cost_change": P(), "time_change_days": P(), "new_contract_amount": P(), "notes": P(), "company_id": P()})


    conn.execute(sql,
        (
            cco_id, ns, ns, pco["job_id"], pco_id,
            pco["title"], pco["description"],
            str(cost_change),
            pco["time_impact_days"],
            str(new_contract.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            pco["notes"],
            pco["company_id"],
        ),
    )
    audit(conn, SKILL, "construction-approve-pco", "constructclaw_pco", pco_id,
          new_values={"pco_status": "approved", "cco_id": cco_id})
    conn.commit()
    ok({
        "pco_id": pco_id, "pco_status": "approved",
        "cco_id": cco_id, "cco_naming_series": ns,
        "cost_change": str(cost_change),
        "new_contract_amount": str(new_contract.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
    })


# ---------------------------------------------------------------------------
# add-cco
# ---------------------------------------------------------------------------
def add_cco(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")
    job_id = getattr(args, "job_id", None)
    if not job_id:
        err("--job-id is required")
    if not getattr(args, "title", None):
        err("--title is required")

    if not conn.execute(Q.from_(Table("constructclaw_job")).select(Field("id")).where(Field("id") == P()).get_sql(), (job_id,)).fetchone():
        err(f"Job {job_id} not found")

    cco_id = str(uuid.uuid4())
    ns = get_next_name(conn, "constructclaw_cco", company_id=args.company_id)

    cost_change = getattr(args, "cost_change", None) or "0"

    sql, _ = insert_row("constructclaw_cco", {"id": P(), "naming_series": P(), "cco_number": P(), "job_id": P(), "pco_id": P(), "title": P(), "description": P(), "cost_change": P(), "time_change_days": P(), "notes": P(), "company_id": P()})


    conn.execute(sql,
        (
            cco_id, ns, ns, job_id,
            getattr(args, "pco_id", None),
            args.title,
            getattr(args, "description", None),
            cost_change,
            int(getattr(args, "time_change_days", None) or 0),
            getattr(args, "notes", None),
            args.company_id,
        ),
    )
    audit(conn, SKILL, "construction-add-cco", "constructclaw_cco", cco_id,
          new_values={"naming_series": ns, "title": args.title})
    conn.commit()
    ok({"cco_id": cco_id, "naming_series": ns, "title": args.title,
        "cco_status": "draft", "cost_change": cost_change})


# ---------------------------------------------------------------------------
# get-cco
# ---------------------------------------------------------------------------
def get_cco(conn, args):
    cco_id = getattr(args, "cco_id", None)
    if not cco_id:
        err("--cco-id is required")
    row = conn.execute(Q.from_(Table("constructclaw_cco")).select(Table("constructclaw_cco").star).where(Field("id") == P()).get_sql(), (cco_id,)).fetchone()
    if not row:
        err(f"CCO {cco_id} not found")
    ok(row_to_dict(row))


# ---------------------------------------------------------------------------
# list-ccos
# ---------------------------------------------------------------------------
def list_ccos(conn, args):
    t = _t_cco
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
    cs = getattr(args, "cco_status", None)
    if cs:
        q = q.where(t.cco_status == P())
        params.append(cs)

    q = q.orderby(t.created_at, order=Order.desc)
    rows = conn.execute(q.get_sql(), params).fetchall()
    ok({"ccos": [row_to_dict(r) for r in rows], "total_count": len(rows)})


# ---------------------------------------------------------------------------
# approve-cco
# ---------------------------------------------------------------------------
def approve_cco(conn, args):
    cco_id = getattr(args, "cco_id", None)
    if not cco_id:
        err("--cco-id is required")
    row = conn.execute(Q.from_(_t_cco).select(_t_cco.star).where(_t_cco.id == P()).get_sql(), (cco_id,)).fetchone()
    if not row:
        err(f"CCO {cco_id} not found")
    if row["cco_status"] not in ("draft", "pending"):
        err(f"CCO must be draft or pending to approve (current: {row['cco_status']})")

    approved_by = getattr(args, "approved_by", None)

    sql, params = dynamic_update("constructclaw_cco", {
        "cco_status": "approved",
        "approved_by": approved_by,
        "approved_date": LiteralValue("date('now')"),
        "updated_at": LiteralValue("datetime('now')"),
    }, {"id": cco_id})
    conn.execute(sql, params)
    audit(conn, SKILL, "construction-approve-cco", "constructclaw_cco", cco_id,
          new_values={"cco_status": "approved", "approved_by": approved_by})
    conn.commit()
    ok({"cco_id": cco_id, "cco_status": "approved"})


# ---------------------------------------------------------------------------
# change-order-impact -- total budget impact of all change orders on a job
# ---------------------------------------------------------------------------
def change_order_impact(conn, args):
    job_id = getattr(args, "job_id", None)
    if not job_id:
        err("--job-id is required")

    job = conn.execute(Q.from_(Table("constructclaw_job")).select(Table("constructclaw_job").star).where(Field("id") == P()).get_sql(), (job_id,)).fetchone()
    if not job:
        err(f"Job {job_id} not found")

    original_contract = _d(job["contract_amount"])

    # PCOs
    pcos = conn.execute(
        "SELECT * FROM constructclaw_pco WHERE job_id = ? ORDER BY created_at", (job_id,)
    ).fetchall()

    pco_list = []
    total_pco_cost = Decimal("0")
    total_pco_days = 0
    for p in pcos:
        cost = _d(p["cost_impact"])
        total_pco_cost += cost
        days = p["time_impact_days"] or 0
        total_pco_days += days
        pco_list.append({
            "pco_id": p["id"],
            "pco_number": p["pco_number"],
            "title": p["title"],
            "cost_impact": str(cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "time_impact_days": days,
            "pco_status": p["pco_status"],
        })

    # CCOs
    ccos = conn.execute(
        "SELECT * FROM constructclaw_cco WHERE job_id = ? ORDER BY created_at", (job_id,)
    ).fetchall()

    cco_list = []
    total_cco_cost = Decimal("0")
    total_cco_days = 0
    for c in ccos:
        cost = _d(c["cost_change"])
        total_cco_cost += cost
        days = c["time_change_days"] or 0
        total_cco_days += days
        cco_list.append({
            "cco_id": c["id"],
            "cco_number": c["cco_number"],
            "title": c["title"],
            "cost_change": str(cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "time_change_days": days,
            "cco_status": c["cco_status"],
        })

    # Only approved/executed CCOs affect contract
    approved_cos = conn.execute(
        "SELECT COALESCE(SUM(CAST(cost_change AS REAL)), 0) as total FROM constructclaw_cco WHERE job_id = ? AND cco_status IN ('approved','executed')",
        (job_id,),
    ).fetchone()
    approved_impact = _d(approved_cos["total"])
    revised_contract = original_contract + approved_impact

    ok({
        "job_id": job_id,
        "job_name": job["name"],
        "original_contract": str(original_contract.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "pcos": pco_list,
        "total_pco_cost_impact": str(total_pco_cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "total_pco_time_impact_days": total_pco_days,
        "ccos": cco_list,
        "total_cco_cost_change": str(total_cco_cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "total_cco_time_change_days": total_cco_days,
        "approved_cost_impact": str(approved_impact.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "revised_contract": str(revised_contract.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
    })


# ---------------------------------------------------------------------------
# ACTIONS registry
# ---------------------------------------------------------------------------
ACTIONS = {
    "construction-add-pco": add_pco,
    "construction-update-pco": update_pco,
    "construction-get-pco": get_pco,
    "construction-list-pcos": list_pcos,
    "construction-approve-pco": approve_pco,
    "construction-add-cco": add_cco,
    "construction-get-cco": get_cco,
    "construction-list-ccos": list_ccos,
    "construction-approve-cco": approve_cco,
    "construction-change-order-impact": change_order_impact,
}
