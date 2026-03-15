"""ConstructClaw -- RFIs & Submittals domain module.

Request for information and submittal tracking.
10 actions exported via ACTIONS dict.
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.expanduser("~/.openclaw/erpclaw/lib"))
from erpclaw_lib.naming import get_next_name, register_prefix
from erpclaw_lib.response import ok, err, row_to_dict
from erpclaw_lib.audit import audit
from erpclaw_lib.query import Q, P, Table, Field, fn, Order, insert_row

SKILL = "constructclaw"

register_prefix("constructclaw_rfi", "CCRFI-")
register_prefix("constructclaw_submittal", "CCSUBM-")

VALID_RFI_STATUSES = ("open", "responded", "closed", "void")
VALID_RFI_PRIORITIES = ("critical", "high", "normal", "low")
VALID_SUBMITTAL_STATUSES = (
    "pending", "under_review", "approved",
    "approved_as_noted", "revise_resubmit", "rejected",
)


# ---------------------------------------------------------------------------
# add-rfi
# ---------------------------------------------------------------------------
def add_rfi(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")
    job_id = getattr(args, "job_id", None)
    if not job_id:
        err("--job-id is required")
    if not getattr(args, "subject", None):
        err("--subject is required")
    if not getattr(args, "question", None):
        err("--question is required")

    if not conn.execute(Q.from_(Table("constructclaw_job")).select(Field("id")).where(Field("id") == P()).get_sql(), (job_id,)).fetchone():
        err(f"Job {job_id} not found")

    priority = getattr(args, "priority", None) or "normal"
    if priority not in VALID_RFI_PRIORITIES:
        err(f"Invalid priority: {priority}")

    rfi_id = str(uuid.uuid4())
    ns = get_next_name(conn, "constructclaw_rfi", company_id=args.company_id)

    sql, _ = insert_row("constructclaw_rfi", {"id": P(), "naming_series": P(), "rfi_number": P(), "job_id": P(), "subject": P(), "question": P(), "initiated_by": P(), "assigned_to": P(), "priority": P(), "date_required": P(), "cost_impact": P(), "schedule_impact_days": P(), "notes": P(), "company_id": P()})


    conn.execute(sql,
        (
            rfi_id, ns, ns, job_id,
            args.subject, args.question,
            getattr(args, "initiated_by", None),
            getattr(args, "assigned_to", None),
            priority,
            getattr(args, "date_required", None),
            getattr(args, "cost_impact", None) or "0",
            int(getattr(args, "schedule_impact_days", None) or 0),
            getattr(args, "notes", None),
            args.company_id,
        ),
    )
    audit(conn, SKILL, "construction-add-rfi", "constructclaw_rfi", rfi_id,
          new_values={"naming_series": ns, "subject": args.subject})
    conn.commit()
    ok({"rfi_id": rfi_id, "naming_series": ns, "subject": args.subject,
        "rfi_status": "open", "priority": priority})


# ---------------------------------------------------------------------------
# update-rfi
# ---------------------------------------------------------------------------
def update_rfi(conn, args):
    rfi_id = getattr(args, "rfi_id", None)
    if not rfi_id:
        err("--rfi-id is required")
    row = conn.execute(Q.from_(Table("constructclaw_rfi")).select(Table("constructclaw_rfi").star).where(Field("id") == P()).get_sql(), (rfi_id,)).fetchone()
    if not row:
        err(f"RFI {rfi_id} not found")

    updates, params, changed = [], [], []
    for field, attr in [
        ("subject", "subject"), ("question", "question"),
        ("initiated_by", "initiated_by"), ("assigned_to", "assigned_to"),
        ("date_required", "date_required"),
        ("cost_impact", "cost_impact"), ("notes", "notes"),
    ]:
        val = getattr(args, attr, None)
        if val is not None:
            updates.append(f"{field} = ?")
            params.append(val)
            changed.append(field)

    sid = getattr(args, "schedule_impact_days", None)
    if sid is not None:
        updates.append("schedule_impact_days = ?")
        params.append(int(sid))
        changed.append("schedule_impact_days")

    pr = getattr(args, "priority", None)
    if pr is not None:
        if pr not in VALID_RFI_PRIORITIES:
            err(f"Invalid priority: {pr}")
        updates.append("priority = ?")
        params.append(pr)
        changed.append("priority")

    if not changed:
        err("No fields to update")

    updates.append("updated_at = datetime('now')")
    params.append(rfi_id)
    conn.execute(
        f"UPDATE constructclaw_rfi SET {', '.join(updates)} WHERE id = ?", params
    )
    audit(conn, SKILL, "construction-update-rfi", "constructclaw_rfi", rfi_id,
          new_values={"updated_fields": changed})
    conn.commit()
    ok({"rfi_id": rfi_id, "updated_fields": changed})


# ---------------------------------------------------------------------------
# get-rfi
# ---------------------------------------------------------------------------
def get_rfi(conn, args):
    rfi_id = getattr(args, "rfi_id", None)
    if not rfi_id:
        err("--rfi-id is required")
    row = conn.execute(Q.from_(Table("constructclaw_rfi")).select(Table("constructclaw_rfi").star).where(Field("id") == P()).get_sql(), (rfi_id,)).fetchone()
    if not row:
        err(f"RFI {rfi_id} not found")
    ok(row_to_dict(row))


# ---------------------------------------------------------------------------
# list-rfis
# ---------------------------------------------------------------------------
def list_rfis(conn, args):
    conditions, params = [], []
    cid = getattr(args, "company_id", None)
    if cid:
        conditions.append("company_id = ?")
        params.append(cid)
    job_id = getattr(args, "job_id", None)
    if job_id:
        conditions.append("job_id = ?")
        params.append(job_id)
    rs = getattr(args, "rfi_status", None)
    if rs:
        conditions.append("rfi_status = ?")
        params.append(rs)
    pr = getattr(args, "priority", None)
    if pr:
        conditions.append("priority = ?")
        params.append(pr)
    search = getattr(args, "search", None)
    if search:
        conditions.append("(subject LIKE ? OR question LIKE ?)")
        params.extend([f"%{search}%"] * 2)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    limit = getattr(args, "limit", 50) or 50
    offset = getattr(args, "offset", 0) or 0

    total = conn.execute(f"SELECT COUNT(*) as cnt FROM constructclaw_rfi {where}", params).fetchone()["cnt"]
    rows = conn.execute(
        f"SELECT * FROM constructclaw_rfi {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()
    ok({"rfis": [row_to_dict(r) for r in rows], "total_count": total,
        "limit": limit, "offset": offset})


# ---------------------------------------------------------------------------
# respond-to-rfi
# ---------------------------------------------------------------------------
def respond_to_rfi(conn, args):
    rfi_id = getattr(args, "rfi_id", None)
    if not rfi_id:
        err("--rfi-id is required")
    if not getattr(args, "response", None):
        err("--response is required")

    row = conn.execute(Q.from_(Table("constructclaw_rfi")).select(Table("constructclaw_rfi").star).where(Field("id") == P()).get_sql(), (rfi_id,)).fetchone()
    if not row:
        err(f"RFI {rfi_id} not found")
    if row["rfi_status"] not in ("open",):
        err(f"RFI must be open to respond (current: {row['rfi_status']})")

    conn.execute(
        """UPDATE constructclaw_rfi
           SET response = ?, rfi_status = 'responded',
               date_responded = date('now'), updated_at = datetime('now')
           WHERE id = ?""",
        (args.response, rfi_id),
    )
    audit(conn, SKILL, "construction-respond-to-rfi", "constructclaw_rfi", rfi_id,
          new_values={"rfi_status": "responded"})
    conn.commit()
    ok({"rfi_id": rfi_id, "rfi_status": "responded"})


# ---------------------------------------------------------------------------
# close-rfi
# ---------------------------------------------------------------------------
def close_rfi(conn, args):
    rfi_id = getattr(args, "rfi_id", None)
    if not rfi_id:
        err("--rfi-id is required")
    row = conn.execute(Q.from_(Table("constructclaw_rfi")).select(Table("constructclaw_rfi").star).where(Field("id") == P()).get_sql(), (rfi_id,)).fetchone()
    if not row:
        err(f"RFI {rfi_id} not found")
    if row["rfi_status"] not in ("open", "responded"):
        err(f"RFI must be open or responded to close (current: {row['rfi_status']})")

    conn.execute(
        "UPDATE constructclaw_rfi SET rfi_status = 'closed', updated_at = datetime('now') WHERE id = ?",
        (rfi_id,),
    )
    audit(conn, SKILL, "construction-close-rfi", "constructclaw_rfi", rfi_id,
          new_values={"rfi_status": "closed"})
    conn.commit()
    ok({"rfi_id": rfi_id, "rfi_status": "closed"})


# ---------------------------------------------------------------------------
# add-submittal
# ---------------------------------------------------------------------------
def add_submittal(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")
    job_id = getattr(args, "job_id", None)
    if not job_id:
        err("--job-id is required")
    if not getattr(args, "title", None):
        err("--title is required")

    if not conn.execute(Q.from_(Table("constructclaw_job")).select(Field("id")).where(Field("id") == P()).get_sql(), (job_id,)).fetchone():
        err(f"Job {job_id} not found")

    sub_id = str(uuid.uuid4())
    ns = get_next_name(conn, "constructclaw_submittal", company_id=args.company_id)

    sql, _ = insert_row("constructclaw_submittal", {"id": P(), "naming_series": P(), "submittal_number": P(), "job_id": P(), "spec_section": P(), "title": P(), "description": P(), "submitted_by": P(), "submitted_to": P(), "date_required": P(), "notes": P(), "company_id": P()})


    conn.execute(sql,
        (
            sub_id, ns, ns, job_id,
            getattr(args, "spec_section", None),
            args.title,
            getattr(args, "description", None),
            getattr(args, "submitted_by", None),
            getattr(args, "submitted_to", None),
            getattr(args, "date_required", None),
            getattr(args, "notes", None),
            args.company_id,
        ),
    )
    audit(conn, SKILL, "construction-add-submittal", "constructclaw_submittal", sub_id,
          new_values={"naming_series": ns, "title": args.title})
    conn.commit()
    ok({"submittal_id": sub_id, "naming_series": ns, "title": args.title,
        "submittal_status": "pending"})


# ---------------------------------------------------------------------------
# update-submittal
# ---------------------------------------------------------------------------
def update_submittal(conn, args):
    sub_id = getattr(args, "submittal_id", None)
    if not sub_id:
        err("--submittal-id is required")
    row = conn.execute(Q.from_(Table("constructclaw_submittal")).select(Table("constructclaw_submittal").star).where(Field("id") == P()).get_sql(), (sub_id,)).fetchone()
    if not row:
        err(f"Submittal {sub_id} not found")

    updates, params, changed = [], [], []
    for field, attr in [
        ("spec_section", "spec_section"), ("title", "title"),
        ("description", "description"), ("submitted_by", "submitted_by"),
        ("submitted_to", "submitted_to"), ("date_required", "date_required"),
        ("notes", "notes"),
    ]:
        val = getattr(args, attr, None)
        if val is not None:
            updates.append(f"{field} = ?")
            params.append(val)
            changed.append(field)

    if not changed:
        err("No fields to update")

    updates.append("updated_at = datetime('now')")
    params.append(sub_id)
    conn.execute(
        f"UPDATE constructclaw_submittal SET {', '.join(updates)} WHERE id = ?", params
    )
    audit(conn, SKILL, "construction-update-submittal", "constructclaw_submittal", sub_id,
          new_values={"updated_fields": changed})
    conn.commit()
    ok({"submittal_id": sub_id, "updated_fields": changed})


# ---------------------------------------------------------------------------
# list-submittals
# ---------------------------------------------------------------------------
def list_submittals(conn, args):
    conditions, params = [], []
    cid = getattr(args, "company_id", None)
    if cid:
        conditions.append("company_id = ?")
        params.append(cid)
    job_id = getattr(args, "job_id", None)
    if job_id:
        conditions.append("job_id = ?")
        params.append(job_id)
    ss = getattr(args, "submittal_status", None)
    if ss:
        conditions.append("submittal_status = ?")
        params.append(ss)
    search = getattr(args, "search", None)
    if search:
        conditions.append("(title LIKE ? OR spec_section LIKE ?)")
        params.extend([f"%{search}%"] * 2)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    limit = getattr(args, "limit", 50) or 50
    offset = getattr(args, "offset", 0) or 0

    total = conn.execute(f"SELECT COUNT(*) as cnt FROM constructclaw_submittal {where}", params).fetchone()["cnt"]
    rows = conn.execute(
        f"SELECT * FROM constructclaw_submittal {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()
    ok({"submittals": [row_to_dict(r) for r in rows], "total_count": total,
        "limit": limit, "offset": offset})


# ---------------------------------------------------------------------------
# review-submittal -- approve/reject with comments
# ---------------------------------------------------------------------------
def review_submittal(conn, args):
    sub_id = getattr(args, "submittal_id", None)
    if not sub_id:
        err("--submittal-id is required")
    decision = getattr(args, "decision", None)
    if not decision:
        err("--decision is required (approved, approved_as_noted, revise_resubmit, rejected)")

    if decision not in ("approved", "approved_as_noted", "revise_resubmit", "rejected"):
        err(f"Invalid decision: {decision}. Must be approved, approved_as_noted, revise_resubmit, or rejected")

    row = conn.execute(Q.from_(Table("constructclaw_submittal")).select(Table("constructclaw_submittal").star).where(Field("id") == P()).get_sql(), (sub_id,)).fetchone()
    if not row:
        err(f"Submittal {sub_id} not found")
    if row["submittal_status"] not in ("pending", "under_review"):
        err(f"Submittal must be pending or under_review to review (current: {row['submittal_status']})")

    review_comments = getattr(args, "review_comments", None) or getattr(args, "notes", None)

    conn.execute(
        """UPDATE constructclaw_submittal
           SET submittal_status = ?, review_comments = ?,
               date_returned = date('now'), updated_at = datetime('now')
           WHERE id = ?""",
        (decision, review_comments, sub_id),
    )
    audit(conn, SKILL, "construction-review-submittal", "constructclaw_submittal", sub_id,
          new_values={"submittal_status": decision, "review_comments": review_comments})
    conn.commit()
    ok({"submittal_id": sub_id, "submittal_status": decision,
        "review_comments": review_comments})


# ---------------------------------------------------------------------------
# ACTIONS registry
# ---------------------------------------------------------------------------
ACTIONS = {
    "construction-add-rfi": add_rfi,
    "construction-update-rfi": update_rfi,
    "construction-get-rfi": get_rfi,
    "construction-list-rfis": list_rfis,
    "construction-respond-to-rfi": respond_to_rfi,
    "construction-close-rfi": close_rfi,
    "construction-add-submittal": add_submittal,
    "construction-update-submittal": update_submittal,
    "construction-list-submittals": list_submittals,
    "construction-review-submittal": review_submittal,
}
