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

SKILL = "constructclaw"

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

    if not conn.execute("SELECT id FROM constructclaw_job WHERE id = ?", (job_id,)).fetchone():
        err(f"Job {job_id} not found")

    pco_id = str(uuid.uuid4())
    ns = get_next_name(conn, "constructclaw_pco", company_id=args.company_id)

    conn.execute(
        """INSERT INTO constructclaw_pco
           (id, naming_series, pco_number, job_id, title, description, reason,
            cost_impact, time_impact_days, requested_by, notes, company_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
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
    row = conn.execute("SELECT * FROM constructclaw_pco WHERE id = ?", (pco_id,)).fetchone()
    if not row:
        err(f"PCO {pco_id} not found")

    updates, params, changed = [], [], []
    for field, attr in [
        ("title", "title"), ("description", "description"),
        ("reason", "reason"), ("cost_impact", "cost_impact"),
        ("requested_by", "requested_by"), ("notes", "notes"),
    ]:
        val = getattr(args, attr, None)
        if val is not None:
            updates.append(f"{field} = ?")
            params.append(val)
            changed.append(field)

    tid = getattr(args, "time_impact_days", None)
    if tid is not None:
        updates.append("time_impact_days = ?")
        params.append(int(tid))
        changed.append("time_impact_days")

    ps = getattr(args, "pco_status", None)
    if ps is not None:
        if ps not in VALID_PCO_STATUSES:
            err(f"Invalid pco-status: {ps}")
        updates.append("pco_status = ?")
        params.append(ps)
        changed.append("pco_status")

    if not changed:
        err("No fields to update")

    updates.append("updated_at = datetime('now')")
    params.append(pco_id)
    conn.execute(
        f"UPDATE constructclaw_pco SET {', '.join(updates)} WHERE id = ?", params
    )
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
    row = conn.execute("SELECT * FROM constructclaw_pco WHERE id = ?", (pco_id,)).fetchone()
    if not row:
        err(f"PCO {pco_id} not found")
    ok(row_to_dict(row))


# ---------------------------------------------------------------------------
# list-pcos
# ---------------------------------------------------------------------------
def list_pcos(conn, args):
    conditions, params = [], []
    cid = getattr(args, "company_id", None)
    if cid:
        conditions.append("company_id = ?")
        params.append(cid)
    job_id = getattr(args, "job_id", None)
    if job_id:
        conditions.append("job_id = ?")
        params.append(job_id)
    ps = getattr(args, "pco_status", None)
    if ps:
        conditions.append("pco_status = ?")
        params.append(ps)
    search = getattr(args, "search", None)
    if search:
        conditions.append("(title LIKE ? OR description LIKE ?)")
        params.extend([f"%{search}%"] * 2)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    limit = getattr(args, "limit", 50) or 50
    offset = getattr(args, "offset", 0) or 0

    total = conn.execute(f"SELECT COUNT(*) as cnt FROM constructclaw_pco {where}", params).fetchone()["cnt"]
    rows = conn.execute(
        f"SELECT * FROM constructclaw_pco {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()
    ok({"pcos": [row_to_dict(r) for r in rows], "total_count": total,
        "limit": limit, "offset": offset})


# ---------------------------------------------------------------------------
# approve-pco -- convert PCO to CCO
# ---------------------------------------------------------------------------
def approve_pco(conn, args):
    pco_id = getattr(args, "pco_id", None)
    if not pco_id:
        err("--pco-id is required")
    pco = conn.execute("SELECT * FROM constructclaw_pco WHERE id = ?", (pco_id,)).fetchone()
    if not pco:
        err(f"PCO {pco_id} not found")
    if pco["pco_status"] not in ("identified", "pricing", "submitted"):
        err(f"PCO must be identified/pricing/submitted to approve (current: {pco['pco_status']})")

    # Update PCO status
    conn.execute(
        "UPDATE constructclaw_pco SET pco_status = 'approved', updated_at = datetime('now') WHERE id = ?",
        (pco_id,),
    )

    # Create CCO from PCO
    cco_id = str(uuid.uuid4())
    ns = get_next_name(conn, "constructclaw_cco", company_id=pco["company_id"])

    # Get current contract amount for job
    job = conn.execute("SELECT contract_amount FROM constructclaw_job WHERE id = ?", (pco["job_id"],)).fetchone()
    current_contract = _d(job["contract_amount"]) if job else Decimal("0")

    # Sum existing approved CCOs
    existing_cos = conn.execute(
        "SELECT COALESCE(SUM(CAST(cost_change AS REAL)), 0) as total FROM constructclaw_cco WHERE job_id = ? AND cco_status IN ('approved','executed')",
        (pco["job_id"],),
    ).fetchone()
    existing_total = _d(existing_cos["total"])

    cost_change = _d(pco["cost_impact"])
    new_contract = current_contract + existing_total + cost_change

    conn.execute(
        """INSERT INTO constructclaw_cco
           (id, naming_series, cco_number, job_id, pco_id, title, description,
            cost_change, time_change_days, new_contract_amount, notes, company_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
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

    if not conn.execute("SELECT id FROM constructclaw_job WHERE id = ?", (job_id,)).fetchone():
        err(f"Job {job_id} not found")

    cco_id = str(uuid.uuid4())
    ns = get_next_name(conn, "constructclaw_cco", company_id=args.company_id)

    cost_change = getattr(args, "cost_change", None) or "0"

    conn.execute(
        """INSERT INTO constructclaw_cco
           (id, naming_series, cco_number, job_id, pco_id, title, description,
            cost_change, time_change_days, notes, company_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
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
    row = conn.execute("SELECT * FROM constructclaw_cco WHERE id = ?", (cco_id,)).fetchone()
    if not row:
        err(f"CCO {cco_id} not found")
    ok(row_to_dict(row))


# ---------------------------------------------------------------------------
# list-ccos
# ---------------------------------------------------------------------------
def list_ccos(conn, args):
    conditions, params = [], []
    cid = getattr(args, "company_id", None)
    if cid:
        conditions.append("company_id = ?")
        params.append(cid)
    job_id = getattr(args, "job_id", None)
    if job_id:
        conditions.append("job_id = ?")
        params.append(job_id)
    cs = getattr(args, "cco_status", None)
    if cs:
        conditions.append("cco_status = ?")
        params.append(cs)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = conn.execute(
        f"SELECT * FROM constructclaw_cco {where} ORDER BY created_at DESC", params
    ).fetchall()
    ok({"ccos": [row_to_dict(r) for r in rows], "total_count": len(rows)})


# ---------------------------------------------------------------------------
# approve-cco
# ---------------------------------------------------------------------------
def approve_cco(conn, args):
    cco_id = getattr(args, "cco_id", None)
    if not cco_id:
        err("--cco-id is required")
    row = conn.execute("SELECT * FROM constructclaw_cco WHERE id = ?", (cco_id,)).fetchone()
    if not row:
        err(f"CCO {cco_id} not found")
    if row["cco_status"] not in ("draft", "pending"):
        err(f"CCO must be draft or pending to approve (current: {row['cco_status']})")

    approved_by = getattr(args, "approved_by", None)

    conn.execute(
        """UPDATE constructclaw_cco
           SET cco_status = 'approved', approved_by = ?, approved_date = date('now'),
               updated_at = datetime('now')
           WHERE id = ?""",
        (approved_by, cco_id),
    )
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

    job = conn.execute("SELECT * FROM constructclaw_job WHERE id = ?", (job_id,)).fetchone()
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
