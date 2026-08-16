"""ConstructClaw -- Project Management domain module.

Permit & Inspection, Punch List, Material Procurement,
Insurance & Bond, Drawing/Plan Management, Warranty Tracking,
Project Scheduling/CPM (milestones).
27 actions exported via ACTIONS dict.

C4: Permit & Inspection (6 actions)
C5: Punch List (4 actions)
C6: Material Procurement (4 actions)
C7: Insurance & Bond (4 actions)
C8: Drawing/Plan Management (2 actions)
C9: Warranty Tracking (3 actions)
C10: Project Scheduling/CPM (4 actions)
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
    Q, P, Table, Field, fn, Order, insert_row, LiteralValue, dynamic_update,
)

SKILL = "constructclaw"

_t_permit = Table("constructclaw_permit")
_t_punch = Table("constructclaw_punch_list_item")
_t_dm = Table("constructclaw_daily_material")
_t_bond = Table("constructclaw_insurance_bond")
_t_warranty = Table("constructclaw_warranty")
_t_milestone = Table("constructclaw_milestone")
_t_job = Table("constructclaw_job")
_t_sub = Table("constructclaw_subcontract")

VALID_INSPECTION_RESULTS = ("pass", "fail", "conditional", "pending")
VALID_PERMIT_STATUSES = ("applied", "approved", "expired", "closed")
VALID_PUNCH_PRIORITIES = ("critical", "high", "normal", "low")
VALID_PUNCH_STATUSES = ("open", "in_progress", "completed", "verified")
VALID_BOND_DOC_TYPES = ("coi", "bid_bond", "performance_bond", "payment_bond", "builders_risk")
VALID_BOND_STATUSES = ("active", "expired", "cancelled")
VALID_WARRANTY_TYPES = ("standard", "extended", "manufacturer")
VALID_WARRANTY_STATUSES = ("active", "expired", "claimed")
VALID_MILESTONE_STATUSES = ("pending", "in_progress", "completed", "delayed")
VALID_DEPENDENCY_TYPES = ("finish_to_start", "start_to_start", "finish_to_finish", "start_to_finish")


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
        "permit_type": "--permit-type",
        "description": "--description",
        "name": "--name",
        "system": "--system",
        "start_date": "--start-date",
        "end_date": "--end-date",
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
# C4: PERMIT & INSPECTION
# ===========================================================================

def add_permit(conn, args):
    _require(args, "company_id", "job_id", "permit_type")
    _check_job(conn, args.job_id)

    p_id = str(uuid.uuid4())
    sql, _ = insert_row("constructclaw_permit", {
        "id": P(), "job_id": P(), "permit_type": P(), "permit_number": P(),
        "jurisdiction": P(), "application_date": P(), "approval_date": P(),
        "expiration_date": P(), "inspection_required": P(),
        "inspection_date": P(), "inspection_result": P(),
        "inspector_name": P(), "correction_notes": P(),
        "status": P(), "company_id": P(),
    })
    conn.execute(sql, (
        p_id, args.job_id, args.permit_type,
        getattr(args, "permit_number", None),
        getattr(args, "jurisdiction", None),
        getattr(args, "application_date", None) or _date.today().isoformat(),
        getattr(args, "approval_date", None),
        getattr(args, "expiration_date", None),
        1,  # inspection_required default
        None, None, None, None,
        "applied",
        args.company_id,
    ))
    audit(conn, SKILL, "construction-add-permit",
          "constructclaw_permit", p_id,
          new_values={"permit_type": args.permit_type, "job_id": args.job_id})
    conn.commit()
    ok({
        "permit_id": p_id, "job_id": args.job_id,
        "permit_type": args.permit_type, "permit_status": "applied",
    })


def update_permit(conn, args):
    permit_id = getattr(args, "permit_id", None)
    if not permit_id:
        err("--permit-id is required")

    row = conn.execute(
        Q.from_(_t_permit).select(_t_permit.star).where(_t_permit.id == P()).get_sql(),
        (permit_id,),
    ).fetchone()
    if not row:
        err(f"Permit {permit_id} not found")

    data, changed = {}, []
    for field, attr in [
        ("permit_number", "permit_number"), ("jurisdiction", "jurisdiction"),
        ("application_date", "application_date"), ("approval_date", "approval_date"),
        ("expiration_date", "expiration_date"), ("inspector_name", "inspector_name"),
        ("correction_notes", "correction_notes"),
    ]:
        val = getattr(args, attr, None)
        if val is not None:
            data[field] = val
            changed.append(field)

    ps = getattr(args, "permit_status", None)
    if ps:
        if ps not in VALID_PERMIT_STATUSES:
            err(f"Invalid permit status: {ps}")
        data["status"] = ps
        changed.append("status")

    if not changed:
        err("No fields to update")

    sql, params = dynamic_update("constructclaw_permit", data, {"id": permit_id})
    conn.execute(sql, params)
    audit(conn, SKILL, "construction-update-permit",
          "constructclaw_permit", permit_id,
          new_values={"updated_fields": changed})
    conn.commit()
    ok({"permit_id": permit_id, "updated_fields": changed})


def list_permits(conn, args):
    t = _t_permit
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
    ps = getattr(args, "permit_status", None)
    if ps:
        q_count = q_count.where(t.status == P())
        q_rows = q_rows.where(t.status == P())
        params.append(ps)

    limit = getattr(args, "limit", 50) or 50
    offset = getattr(args, "offset", 0) or 0

    total = conn.execute(q_count.get_sql(), params).fetchone()["cnt"]
    q_rows = q_rows.orderby(t.created_at, order=Order.desc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [limit, offset]).fetchall()
    ok({
        "permits": [row_to_dict(r) for r in rows],
        "total_count": total, "limit": limit, "offset": offset,
    })


def schedule_inspection(conn, args):
    permit_id = getattr(args, "permit_id", None)
    if not permit_id:
        err("--permit-id is required")
    inspection_date = getattr(args, "inspection_date", None)
    if not inspection_date:
        err("--inspection-date is required")

    row = conn.execute(
        Q.from_(_t_permit).select(_t_permit.star).where(_t_permit.id == P()).get_sql(),
        (permit_id,),
    ).fetchone()
    if not row:
        err(f"Permit {permit_id} not found")

    data = {"inspection_date": inspection_date, "inspection_result": "pending"}
    inspector = getattr(args, "inspector_name", None)
    if inspector:
        data["inspector_name"] = inspector

    sql, params = dynamic_update("constructclaw_permit", data, {"id": permit_id})
    conn.execute(sql, params)
    audit(conn, SKILL, "construction-schedule-inspection",
          "constructclaw_permit", permit_id,
          new_values={"inspection_date": inspection_date})
    conn.commit()
    ok({"permit_id": permit_id, "inspection_date": inspection_date,
        "inspection_result": "pending"})


def record_inspection_result(conn, args):
    permit_id = getattr(args, "permit_id", None)
    if not permit_id:
        err("--permit-id is required")
    result = getattr(args, "inspection_result", None)
    if not result:
        err("--inspection-result is required")
    if result not in VALID_INSPECTION_RESULTS:
        err(f"Invalid inspection result: {result}. Must be one of: {', '.join(VALID_INSPECTION_RESULTS)}")

    row = conn.execute(
        Q.from_(_t_permit).select(_t_permit.star).where(_t_permit.id == P()).get_sql(),
        (permit_id,),
    ).fetchone()
    if not row:
        err(f"Permit {permit_id} not found")

    data = {"inspection_result": result}
    inspector = getattr(args, "inspector_name", None)
    if inspector:
        data["inspector_name"] = inspector
    notes = getattr(args, "correction_notes", None)
    if notes:
        data["correction_notes"] = notes

    # If passed, auto-approve the permit
    if result == "pass":
        data["status"] = "approved"

    sql, params = dynamic_update("constructclaw_permit", data, {"id": permit_id})
    conn.execute(sql, params)
    audit(conn, SKILL, "construction-record-inspection-result",
          "constructclaw_permit", permit_id,
          new_values={"inspection_result": result})
    conn.commit()
    ok({"permit_id": permit_id, "inspection_result": result,
        "permit_status": data.get("status", row["status"])})


def permit_expiry_report(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")

    rows = conn.execute(
        """SELECT * FROM constructclaw_permit
           WHERE company_id = ? AND status IN ('applied', 'approved')
           AND expiration_date IS NOT NULL
           ORDER BY expiration_date ASC""",
        (args.company_id,),
    ).fetchall()

    today = _date.today().isoformat()
    expiring_soon = []
    expired = []
    for r in rows:
        d = row_to_dict(r)
        if r["expiration_date"] < today:
            expired.append(d)
        elif r["expiration_date"] <= (_date.today().isoformat()[:8] + "31"):
            # Within current month as "expiring soon"
            expiring_soon.append(d)
        else:
            expiring_soon.append(d)

    ok({
        "company_id": args.company_id,
        "total_permits": len(rows),
        "expired_count": len(expired),
        "expired": expired,
        "expiring_soon_count": len(expiring_soon),
        "expiring_soon": expiring_soon,
    })


# ===========================================================================
# C5: PUNCH LIST
# ===========================================================================

def add_punch_list_item(conn, args):
    _require(args, "company_id", "job_id", "description")
    _check_job(conn, args.job_id)

    priority = getattr(args, "priority", None) or "normal"
    if priority not in VALID_PUNCH_PRIORITIES:
        err(f"Invalid priority: {priority}")

    p_id = str(uuid.uuid4())
    sql, _ = insert_row("constructclaw_punch_list_item", {
        "id": P(), "job_id": P(), "description": P(), "location": P(),
        "assigned_to": P(), "subcontractor_id": P(), "priority": P(),
        "photo_url": P(), "completion_date": P(), "status": P(), "company_id": P(),
    })
    conn.execute(sql, (
        p_id, args.job_id, args.description,
        getattr(args, "location", None),
        getattr(args, "assigned_to", None),
        getattr(args, "subcontractor_id", None),
        priority,
        getattr(args, "photo_url", None),
        None,  # completion_date
        "open",
        args.company_id,
    ))
    audit(conn, SKILL, "construction-add-punch-list-item",
          "constructclaw_punch_list_item", p_id,
          new_values={"description": args.description, "priority": priority})
    conn.commit()
    ok({
        "punch_list_item_id": p_id, "job_id": args.job_id,
        "priority": priority, "punch_status": "open",
    })


def update_punch_list_item(conn, args):
    item_id = getattr(args, "punch_item_id", None)
    if not item_id:
        err("--punch-item-id is required")

    row = conn.execute(
        Q.from_(_t_punch).select(_t_punch.star).where(_t_punch.id == P()).get_sql(),
        (item_id,),
    ).fetchone()
    if not row:
        err(f"Punch list item {item_id} not found")

    data, changed = {}, []
    for field, attr in [
        ("description", "description"), ("location", "location"),
        ("assigned_to", "assigned_to"), ("subcontractor_id", "subcontractor_id"),
        ("photo_url", "photo_url"), ("completion_date", "completion_date"),
    ]:
        val = getattr(args, attr, None)
        if val is not None:
            data[field] = val
            changed.append(field)

    pr = getattr(args, "priority", None)
    if pr:
        if pr not in VALID_PUNCH_PRIORITIES:
            err(f"Invalid priority: {pr}")
        data["priority"] = pr
        changed.append("priority")

    ps = getattr(args, "punch_status", None)
    if ps:
        if ps not in VALID_PUNCH_STATUSES:
            err(f"Invalid status: {ps}")
        data["status"] = ps
        changed.append("status")

    if not changed:
        err("No fields to update")

    sql, params = dynamic_update("constructclaw_punch_list_item", data, {"id": item_id})
    conn.execute(sql, params)
    audit(conn, SKILL, "construction-update-punch-list-item",
          "constructclaw_punch_list_item", item_id,
          new_values={"updated_fields": changed})
    conn.commit()
    ok({"punch_list_item_id": item_id, "updated_fields": changed})


def list_punch_list(conn, args):
    t = _t_punch
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
    ps = getattr(args, "punch_status", None)
    if ps:
        q_count = q_count.where(t.status == P())
        q_rows = q_rows.where(t.status == P())
        params.append(ps)
    search = getattr(args, "search", None)
    if search:
        s = f"%{search}%"
        like_crit = t.description.like(P())
        q_count = q_count.where(like_crit)
        q_rows = q_rows.where(like_crit)
        params.append(s)

    limit = getattr(args, "limit", 50) or 50
    offset = getattr(args, "offset", 0) or 0

    total = conn.execute(q_count.get_sql(), params).fetchone()["cnt"]
    q_rows = q_rows.orderby(t.created_at, order=Order.desc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [limit, offset]).fetchall()
    ok({
        "punch_list_items": [row_to_dict(r) for r in rows],
        "total_count": total, "limit": limit, "offset": offset,
    })


def punch_list_summary(conn, args):
    _require(args, "company_id", "job_id")

    rows = conn.execute(
        """SELECT status, priority, COUNT(*) as cnt
           FROM constructclaw_punch_list_item
           WHERE job_id = ? AND company_id = ?
           GROUP BY status, priority
           ORDER BY status, priority""",
        (args.job_id, args.company_id),
    ).fetchall()

    by_status = {}
    by_priority = {}
    total = 0
    for r in rows:
        st = r["status"]
        pr = r["priority"]
        c = r["cnt"]
        total += c
        by_status[st] = by_status.get(st, 0) + c
        by_priority[pr] = by_priority.get(pr, 0) + c

    ok({
        "job_id": args.job_id,
        "total_items": total,
        "by_status": by_status,
        "by_priority": by_priority,
        "open_count": by_status.get("open", 0) + by_status.get("in_progress", 0),
        "completed_count": by_status.get("completed", 0) + by_status.get("verified", 0),
    })


# ===========================================================================
# C6: MATERIAL PROCUREMENT
# ===========================================================================

def create_material_requisition(conn, args):
    """Create a material requisition from field to office, stored as a daily_material with requisition status."""
    _require(args, "company_id", "job_id")
    _check_job(conn, args.job_id)

    material_name = getattr(args, "material_name", None)
    if not material_name:
        err("--material-name is required")
    quantity = getattr(args, "quantity", None)
    if not quantity:
        err("--quantity is required")

    req_id = str(uuid.uuid4())
    sql, _ = insert_row("constructclaw_daily_material", {
        "id": P(), "daily_report_id": P(), "job_id": P(),
        "material_name": P(), "quantity": P(), "unit": P(),
        "unit_cost": P(), "supplier": P(), "delivery_ticket": P(),
        "notes": P(), "status": P(), "company_id": P(),
    })
    conn.execute(sql, (
        req_id, None, args.job_id,
        material_name,
        str(_d(quantity)),
        getattr(args, "unit", None),
        str(_d(getattr(args, "unit_cost", None))),
        getattr(args, "supplier", None),
        None,  # delivery_ticket
        getattr(args, "notes", None),
        "requisition",
        args.company_id,
    ))
    audit(conn, SKILL, "construction-create-material-requisition",
          "constructclaw_daily_material", req_id,
          new_values={"material_name": material_name, "quantity": quantity})
    conn.commit()
    ok({
        "requisition_id": req_id, "job_id": args.job_id,
        "material_name": material_name, "quantity": str(_d(quantity)),
        "status": "requisition",
    })


def list_material_requisitions(conn, args):
    t = _t_dm
    q = Q.from_(t).select(t.star).where(t.status == P())
    params = ["requisition"]

    cid = getattr(args, "company_id", None)
    if cid:
        q = q.where(t.company_id == P())
        params.append(cid)
    job_id = getattr(args, "job_id", None)
    if job_id:
        q = q.where(t.job_id == P())
        params.append(job_id)

    q = q.orderby(t.created_at, order=Order.desc)
    rows = conn.execute(q.get_sql(), params).fetchall()
    ok({"material_requisitions": [row_to_dict(r) for r in rows],
        "total_count": len(rows)})


def track_material_delivery(conn, args):
    """Update a material entry with delivery information."""
    req_id = getattr(args, "material_id", None)
    if not req_id:
        err("--material-id is required")

    row = conn.execute(
        Q.from_(_t_dm).select(_t_dm.star).where(_t_dm.id == P()).get_sql(),
        (req_id,),
    ).fetchone()
    if not row:
        err(f"Material record {req_id} not found")

    data = {"status": "delivered"}
    ticket = getattr(args, "delivery_ticket", None)
    if ticket:
        data["delivery_ticket"] = ticket
    supplier = getattr(args, "supplier", None)
    if supplier:
        data["supplier"] = supplier
    notes = getattr(args, "notes", None)
    if notes:
        data["notes"] = notes

    sql, params = dynamic_update("constructclaw_daily_material", data, {"id": req_id})
    conn.execute(sql, params)
    audit(conn, SKILL, "construction-track-material-delivery",
          "constructclaw_daily_material", req_id,
          new_values={"status": "delivered"})
    conn.commit()
    ok({"material_id": req_id, "status": "delivered"})


def material_waste_report(conn, args):
    _require(args, "company_id", "job_id")

    rows = conn.execute(
        """SELECT material_name,
                  SUM(CAST(quantity AS REAL)) as total_qty,
                  SUM(CAST(unit_cost AS REAL) * CAST(quantity AS REAL)) as total_cost,
                  COUNT(*) as delivery_count
           FROM constructclaw_daily_material
           WHERE job_id = ? AND company_id = ?
           GROUP BY material_name
           ORDER BY total_cost DESC""",
        (args.job_id, args.company_id),
    ).fetchall()

    materials = []
    grand_cost = Decimal("0")
    for r in rows:
        c = _d(r["total_cost"])
        grand_cost += c
        materials.append({
            "material_name": r["material_name"],
            "total_quantity": str(_d(r["total_qty"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "total_cost": str(c.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "delivery_count": r["delivery_count"],
        })

    ok({
        "job_id": args.job_id,
        "materials": materials,
        "grand_total_cost": str(grand_cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
    })


# ===========================================================================
# C7: INSURANCE & BOND
# ===========================================================================

def add_insurance_bond(conn, args):
    _require(args, "company_id")
    doc_type = getattr(args, "document_type", None)
    if not doc_type:
        err("--document-type is required")
    if doc_type not in VALID_BOND_DOC_TYPES:
        err(f"Invalid document type: {doc_type}. Must be one of: {', '.join(VALID_BOND_DOC_TYPES)}")

    b_id = str(uuid.uuid4())
    sql, _ = insert_row("constructclaw_insurance_bond", {
        "id": P(), "job_id": P(), "subcontractor_id": P(),
        "document_type": P(), "carrier": P(), "policy_number": P(),
        "coverage_amount": P(), "effective_date": P(), "expiration_date": P(),
        "verified": P(), "verified_by": P(), "verified_date": P(),
        "status": P(), "company_id": P(),
    })
    conn.execute(sql, (
        b_id,
        getattr(args, "job_id", None),
        getattr(args, "subcontractor_id", None),
        doc_type,
        getattr(args, "carrier", None),
        getattr(args, "policy_number", None),
        str(_d(getattr(args, "coverage_amount", None))),
        getattr(args, "effective_date", None),
        getattr(args, "expiration_date", None),
        0, None, None,
        "active",
        args.company_id,
    ))
    audit(conn, SKILL, "construction-add-insurance-bond",
          "constructclaw_insurance_bond", b_id,
          new_values={"document_type": doc_type})
    conn.commit()
    ok({
        "insurance_bond_id": b_id, "document_type": doc_type, "bond_status": "active",
    })


def list_insurance_bonds(conn, args):
    t = _t_bond
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
    sub_id = getattr(args, "subcontractor_id", None)
    if sub_id:
        q = q.where(t.subcontractor_id == P())
        params.append(sub_id)
    doc_type = getattr(args, "document_type", None)
    if doc_type:
        q = q.where(t.document_type == P())
        params.append(doc_type)

    q = q.orderby(t.created_at, order=Order.desc)
    rows = conn.execute(q.get_sql(), params).fetchall()
    ok({"insurance_bonds": [row_to_dict(r) for r in rows],
        "total_count": len(rows)})


def check_expiring_insurance(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")

    # Find all active bonds expiring within 30 days
    rows = conn.execute(
        """SELECT * FROM constructclaw_insurance_bond
           WHERE company_id = ? AND status = 'active'
           AND expiration_date IS NOT NULL
           AND expiration_date <= date('now', '+30 days')
           ORDER BY expiration_date ASC""",
        (args.company_id,),
    ).fetchall()

    today = _date.today().isoformat()
    expired = []
    expiring = []
    for r in rows:
        d = row_to_dict(r)
        if r["expiration_date"] < today:
            expired.append(d)
        else:
            expiring.append(d)

    ok({
        "company_id": args.company_id,
        "expired_count": len(expired),
        "expired": expired,
        "expiring_within_30_days_count": len(expiring),
        "expiring_within_30_days": expiring,
    })


def insurance_compliance_report(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")

    rows = conn.execute(
        """SELECT * FROM constructclaw_insurance_bond
           WHERE company_id = ?
           ORDER BY document_type, expiration_date""",
        (args.company_id,),
    ).fetchall()

    by_type = {}
    total_coverage = Decimal("0")
    verified_count = 0
    unverified_count = 0

    for r in rows:
        dt = r["document_type"]
        by_type.setdefault(dt, []).append(row_to_dict(r))
        total_coverage += _d(r["coverage_amount"])
        if r["verified"]:
            verified_count += 1
        else:
            unverified_count += 1

    ok({
        "company_id": args.company_id,
        "total_bonds": len(rows),
        "by_document_type": {k: {"count": len(v), "bonds": v} for k, v in by_type.items()},
        "total_coverage": str(total_coverage.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "verified_count": verified_count,
        "unverified_count": unverified_count,
    })


# ===========================================================================
# C8: DRAWING/PLAN MANAGEMENT
# ===========================================================================

def add_drawing(conn, args):
    """Add a drawing/plan reference for a construction job."""
    _require(args, "company_id", "job_id", "name")

    d_id = str(uuid.uuid4())
    # Store as a construction-specific document entry
    # We use the existing constructclaw tables approach -- store drawing metadata
    # alongside the daily report mechanism. For full document management, use erpclaw-documents.
    sql, _ = insert_row("constructclaw_daily_material", {
        "id": P(), "daily_report_id": P(), "job_id": P(),
        "material_name": P(), "quantity": P(), "unit": P(),
        "unit_cost": P(), "supplier": P(), "delivery_ticket": P(),
        "notes": P(), "status": P(), "company_id": P(),
    })
    # Store drawing metadata: spec_section in unit, discipline in supplier, sheet_number in delivery_ticket
    conn.execute(sql, (
        d_id, None, args.job_id,
        args.name,  # drawing name in material_name field
        "1",  # quantity=1 for a drawing
        getattr(args, "spec_section", None),  # spec_section in unit field
        "0",
        getattr(args, "discipline", None),  # discipline in supplier field
        getattr(args, "sheet_number", None),  # sheet_number in delivery_ticket field
        getattr(args, "description", None),
        "drawing",
        args.company_id,
    ))
    audit(conn, SKILL, "construction-add-drawing",
          "constructclaw_daily_material", d_id,
          new_values={"name": args.name, "type": "drawing"})
    conn.commit()
    ok({
        "drawing_id": d_id, "job_id": args.job_id,
        "name": args.name,
        "spec_section": getattr(args, "spec_section", None),
        "discipline": getattr(args, "discipline", None),
        "sheet_number": getattr(args, "sheet_number", None),
    })


def list_drawings(conn, args):
    t = _t_dm
    q = Q.from_(t).select(t.star).where(t.status == P())
    params = ["drawing"]

    cid = getattr(args, "company_id", None)
    if cid:
        q = q.where(t.company_id == P())
        params.append(cid)
    job_id = getattr(args, "job_id", None)
    if job_id:
        q = q.where(t.job_id == P())
        params.append(job_id)

    q = q.orderby(t.created_at, order=Order.desc)
    rows = conn.execute(q.get_sql(), params).fetchall()

    # Map fields back to drawing terminology
    drawings = []
    for r in rows:
        drawings.append({
            "drawing_id": r["id"],
            "job_id": r["job_id"],
            "name": r["material_name"],
            "spec_section": r["unit"],
            "discipline": r["supplier"],
            "sheet_number": r["delivery_ticket"],
            "description": r["notes"],
            "created_at": r["created_at"],
        })

    ok({"drawings": drawings, "total_count": len(drawings)})


# ===========================================================================
# C9: WARRANTY TRACKING
# ===========================================================================

def add_warranty(conn, args):
    _require(args, "company_id", "job_id", "system", "start_date", "end_date")
    _check_job(conn, args.job_id)

    wt = getattr(args, "warranty_type", None) or "standard"
    if wt not in VALID_WARRANTY_TYPES:
        err(f"Invalid warranty type: {wt}")

    w_id = str(uuid.uuid4())
    sql, _ = insert_row("constructclaw_warranty", {
        "id": P(), "job_id": P(), "trade": P(), "system": P(),
        "subcontractor_id": P(), "start_date": P(), "end_date": P(),
        "warranty_type": P(), "description": P(), "contact_info": P(),
        "status": P(), "company_id": P(),
    })
    conn.execute(sql, (
        w_id, args.job_id,
        getattr(args, "trade", None),
        args.system,
        getattr(args, "subcontractor_id", None),
        args.start_date, args.end_date,
        wt,
        getattr(args, "description", None),
        getattr(args, "contact_info", None),
        "active",
        args.company_id,
    ))
    audit(conn, SKILL, "construction-add-warranty",
          "constructclaw_warranty", w_id,
          new_values={"system": args.system, "warranty_type": wt})
    conn.commit()
    ok({
        "warranty_id": w_id, "job_id": args.job_id,
        "system": args.system, "warranty_type": wt, "warranty_status": "active",
    })


def list_warranties(conn, args):
    t = _t_warranty
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
    ws = getattr(args, "warranty_status", None)
    if ws:
        q = q.where(t.status == P())
        params.append(ws)

    q = q.orderby(t.end_date, order=Order.asc)
    rows = conn.execute(q.get_sql(), params).fetchall()
    ok({"warranties": [row_to_dict(r) for r in rows],
        "total_count": len(rows)})


def check_expiring_warranties(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")

    rows = conn.execute(
        """SELECT * FROM constructclaw_warranty
           WHERE company_id = ? AND status = 'active'
           AND end_date <= date('now', '+60 days')
           ORDER BY end_date ASC""",
        (args.company_id,),
    ).fetchall()

    today = _date.today().isoformat()
    expired = []
    expiring = []
    for r in rows:
        d = row_to_dict(r)
        if r["end_date"] < today:
            expired.append(d)
        else:
            expiring.append(d)

    ok({
        "company_id": args.company_id,
        "expired_count": len(expired),
        "expired": expired,
        "expiring_within_60_days_count": len(expiring),
        "expiring_within_60_days": expiring,
    })


# ===========================================================================
# C10: PROJECT SCHEDULING / CPM (MILESTONES)
# ===========================================================================

def add_milestone(conn, args):
    _require(args, "company_id", "job_id", "name")
    _check_job(conn, args.job_id)

    dep_type = getattr(args, "dependency_type", None) or "finish_to_start"
    if dep_type not in VALID_DEPENDENCY_TYPES:
        err(f"Invalid dependency type: {dep_type}")

    m_id = str(uuid.uuid4())
    sql, _ = insert_row("constructclaw_milestone", {
        "id": P(), "job_id": P(), "name": P(), "description": P(),
        "planned_date": P(), "actual_date": P(),
        "predecessor_id": P(), "dependency_type": P(), "lag_days": P(),
        "is_critical": P(), "status": P(), "company_id": P(),
    })
    conn.execute(sql, (
        m_id, args.job_id, args.name,
        getattr(args, "description", None),
        getattr(args, "planned_date", None),
        None,  # actual_date
        getattr(args, "predecessor_id", None),
        dep_type,
        int(getattr(args, "lag_days", None) or 0),
        int(getattr(args, "is_critical", None) or 0),
        "pending",
        args.company_id,
    ))
    audit(conn, SKILL, "construction-add-milestone",
          "constructclaw_milestone", m_id,
          new_values={"name": args.name, "job_id": args.job_id})
    conn.commit()
    ok({
        "milestone_id": m_id, "job_id": args.job_id,
        "name": args.name, "milestone_status": "pending",
    })


def list_milestones(conn, args):
    t = _t_milestone
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
    ms = getattr(args, "milestone_status", None)
    if ms:
        q = q.where(t.status == P())
        params.append(ms)

    q = q.orderby(t.planned_date, order=Order.asc)
    rows = conn.execute(q.get_sql(), params).fetchall()
    ok({"milestones": [row_to_dict(r) for r in rows],
        "total_count": len(rows)})


def update_milestone(conn, args):
    m_id = getattr(args, "milestone_id", None)
    if not m_id:
        err("--milestone-id is required")

    row = conn.execute(
        Q.from_(_t_milestone).select(_t_milestone.star).where(_t_milestone.id == P()).get_sql(),
        (m_id,),
    ).fetchone()
    if not row:
        err(f"Milestone {m_id} not found")

    data, changed = {}, []
    for field, attr in [
        ("name", "name"), ("description", "description"),
        ("planned_date", "planned_date"), ("actual_date", "actual_date"),
        ("predecessor_id", "predecessor_id"),
    ]:
        val = getattr(args, attr, None)
        if val is not None:
            data[field] = val
            changed.append(field)

    dep_type = getattr(args, "dependency_type", None)
    if dep_type:
        if dep_type not in VALID_DEPENDENCY_TYPES:
            err(f"Invalid dependency type: {dep_type}")
        data["dependency_type"] = dep_type
        changed.append("dependency_type")

    lag = getattr(args, "lag_days", None)
    if lag is not None:
        data["lag_days"] = int(lag)
        changed.append("lag_days")

    ic = getattr(args, "is_critical", None)
    if ic is not None:
        data["is_critical"] = int(ic)
        changed.append("is_critical")

    ms = getattr(args, "milestone_status", None)
    if ms:
        if ms not in VALID_MILESTONE_STATUSES:
            err(f"Invalid status: {ms}")
        data["status"] = ms
        changed.append("status")

    if not changed:
        err("No fields to update")

    sql, params = dynamic_update("constructclaw_milestone", data, {"id": m_id})
    conn.execute(sql, params)
    audit(conn, SKILL, "construction-update-milestone",
          "constructclaw_milestone", m_id,
          new_values={"updated_fields": changed})
    conn.commit()
    ok({"milestone_id": m_id, "updated_fields": changed})


def critical_path_report(conn, args):
    _require(args, "company_id", "job_id")

    all_milestones = conn.execute(
        """SELECT * FROM constructclaw_milestone
           WHERE job_id = ? AND company_id = ?
           ORDER BY planned_date ASC""",
        (args.job_id, args.company_id),
    ).fetchall()

    critical = []
    non_critical = []
    delayed = []
    completed = []
    today = _date.today().isoformat()

    for m in all_milestones:
        d = row_to_dict(m)
        if m["status"] == "completed":
            completed.append(d)
        elif m["status"] == "delayed":
            delayed.append(d)
        elif m["is_critical"]:
            critical.append(d)
        else:
            non_critical.append(d)

    # Check for milestones past their planned date
    at_risk = []
    for m in all_milestones:
        if m["status"] in ("pending", "in_progress") and m["planned_date"] and m["planned_date"] < today:
            at_risk.append(row_to_dict(m))

    ok({
        "job_id": args.job_id,
        "total_milestones": len(all_milestones),
        "critical_path": critical,
        "critical_count": len(critical),
        "non_critical": non_critical,
        "delayed": delayed,
        "delayed_count": len(delayed),
        "completed": completed,
        "completed_count": len(completed),
        "at_risk": at_risk,
        "at_risk_count": len(at_risk),
    })


# ---------------------------------------------------------------------------
# ACTIONS registry
# ---------------------------------------------------------------------------
ACTIONS = {
    # C4: Permit & Inspection
    "construction-add-permit": add_permit,
    "construction-update-permit": update_permit,
    "construction-list-permits": list_permits,
    "construction-schedule-inspection": schedule_inspection,
    "construction-record-inspection-result": record_inspection_result,
    "construction-permit-expiry-report": permit_expiry_report,
    # C5: Punch List
    "construction-add-punch-list-item": add_punch_list_item,
    "construction-update-punch-list-item": update_punch_list_item,
    "construction-list-punch-list": list_punch_list,
    "construction-punch-list-summary": punch_list_summary,
    # C6: Material Procurement
    "construction-create-material-requisition": create_material_requisition,
    "construction-list-material-requisitions": list_material_requisitions,
    "construction-track-material-delivery": track_material_delivery,
    "construction-material-waste-report": material_waste_report,
    # C7: Insurance & Bond
    "construction-add-insurance-bond": add_insurance_bond,
    "construction-list-insurance-bonds": list_insurance_bonds,
    "construction-check-expiring-insurance": check_expiring_insurance,
    "construction-insurance-compliance-report": insurance_compliance_report,
    # C8: Drawing/Plan Management
    "construction-add-drawing": add_drawing,
    "construction-list-drawings": list_drawings,
    # C9: Warranty Tracking
    "construction-add-warranty": add_warranty,
    "construction-list-warranties": list_warranties,
    "construction-check-expiring-warranties": check_expiring_warranties,
    # C10: Project Scheduling/CPM
    "construction-add-milestone": add_milestone,
    "construction-list-milestones": list_milestones,
    "construction-update-milestone": update_milestone,
    "construction-critical-path-report": critical_path_report,
}
