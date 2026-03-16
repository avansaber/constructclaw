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
from erpclaw_lib.query import Q, P, Table, Field, fn, Order, insert_row, LiteralValue, dynamic_update

SKILL = "constructclaw"

_t_rfi = Table("constructclaw_rfi")
_t_submittal = Table("constructclaw_submittal")

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
    row = conn.execute(Q.from_(_t_rfi).select(_t_rfi.star).where(_t_rfi.id == P()).get_sql(), (rfi_id,)).fetchone()
    if not row:
        err(f"RFI {rfi_id} not found")

    data, changed = {}, []
    for field, attr in [
        ("subject", "subject"), ("question", "question"),
        ("initiated_by", "initiated_by"), ("assigned_to", "assigned_to"),
        ("date_required", "date_required"),
        ("cost_impact", "cost_impact"), ("notes", "notes"),
    ]:
        val = getattr(args, attr, None)
        if val is not None:
            data[field] = val
            changed.append(field)

    sid = getattr(args, "schedule_impact_days", None)
    if sid is not None:
        data["schedule_impact_days"] = int(sid)
        changed.append("schedule_impact_days")

    pr = getattr(args, "priority", None)
    if pr is not None:
        if pr not in VALID_RFI_PRIORITIES:
            err(f"Invalid priority: {pr}")
        data["priority"] = pr
        changed.append("priority")

    if not changed:
        err("No fields to update")

    data["updated_at"] = LiteralValue("datetime('now')")
    sql, params = dynamic_update("constructclaw_rfi", data, {"id": rfi_id})
    conn.execute(sql, params)
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
    t = _t_rfi
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
    rs = getattr(args, "rfi_status", None)
    if rs:
        q_count = q_count.where(t.rfi_status == P())
        q_rows = q_rows.where(t.rfi_status == P())
        params.append(rs)
    pr = getattr(args, "priority", None)
    if pr:
        q_count = q_count.where(t.priority == P())
        q_rows = q_rows.where(t.priority == P())
        params.append(pr)
    search = getattr(args, "search", None)
    if search:
        s = f"%{search}%"
        like_crit = (t.subject.like(P()) | t.question.like(P()))
        q_count = q_count.where(like_crit)
        q_rows = q_rows.where(like_crit)
        params.extend([s] * 2)

    limit = getattr(args, "limit", 50) or 50
    offset = getattr(args, "offset", 0) or 0

    total = conn.execute(q_count.get_sql(), params).fetchone()["cnt"]
    q_rows = q_rows.orderby(t.created_at, order=Order.desc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [limit, offset]).fetchall()
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

    row = conn.execute(Q.from_(_t_rfi).select(_t_rfi.star).where(_t_rfi.id == P()).get_sql(), (rfi_id,)).fetchone()
    if not row:
        err(f"RFI {rfi_id} not found")
    if row["rfi_status"] not in ("open",):
        err(f"RFI must be open to respond (current: {row['rfi_status']})")

    sql, params = dynamic_update("constructclaw_rfi", {
        "response": args.response,
        "rfi_status": "responded",
        "date_responded": LiteralValue("date('now')"),
        "updated_at": LiteralValue("datetime('now')"),
    }, {"id": rfi_id})
    conn.execute(sql, params)
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
    row = conn.execute(Q.from_(_t_rfi).select(_t_rfi.star).where(_t_rfi.id == P()).get_sql(), (rfi_id,)).fetchone()
    if not row:
        err(f"RFI {rfi_id} not found")
    if row["rfi_status"] not in ("open", "responded"):
        err(f"RFI must be open or responded to close (current: {row['rfi_status']})")

    sql, params = dynamic_update("constructclaw_rfi",
        {"rfi_status": "closed", "updated_at": LiteralValue("datetime('now')")},
        {"id": rfi_id})
    conn.execute(sql, params)
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
    row = conn.execute(Q.from_(_t_submittal).select(_t_submittal.star).where(_t_submittal.id == P()).get_sql(), (sub_id,)).fetchone()
    if not row:
        err(f"Submittal {sub_id} not found")

    data, changed = {}, []
    for field, attr in [
        ("spec_section", "spec_section"), ("title", "title"),
        ("description", "description"), ("submitted_by", "submitted_by"),
        ("submitted_to", "submitted_to"), ("date_required", "date_required"),
        ("notes", "notes"),
    ]:
        val = getattr(args, attr, None)
        if val is not None:
            data[field] = val
            changed.append(field)

    if not changed:
        err("No fields to update")

    data["updated_at"] = LiteralValue("datetime('now')")
    sql, params = dynamic_update("constructclaw_submittal", data, {"id": sub_id})
    conn.execute(sql, params)
    audit(conn, SKILL, "construction-update-submittal", "constructclaw_submittal", sub_id,
          new_values={"updated_fields": changed})
    conn.commit()
    ok({"submittal_id": sub_id, "updated_fields": changed})


# ---------------------------------------------------------------------------
# list-submittals
# ---------------------------------------------------------------------------
def list_submittals(conn, args):
    t = _t_submittal
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
    ss = getattr(args, "submittal_status", None)
    if ss:
        q_count = q_count.where(t.submittal_status == P())
        q_rows = q_rows.where(t.submittal_status == P())
        params.append(ss)
    search = getattr(args, "search", None)
    if search:
        s = f"%{search}%"
        like_crit = (t.title.like(P()) | t.spec_section.like(P()))
        q_count = q_count.where(like_crit)
        q_rows = q_rows.where(like_crit)
        params.extend([s] * 2)

    limit = getattr(args, "limit", 50) or 50
    offset = getattr(args, "offset", 0) or 0

    total = conn.execute(q_count.get_sql(), params).fetchone()["cnt"]
    q_rows = q_rows.orderby(t.created_at, order=Order.desc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [limit, offset]).fetchall()
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

    row = conn.execute(Q.from_(_t_submittal).select(_t_submittal.star).where(_t_submittal.id == P()).get_sql(), (sub_id,)).fetchone()
    if not row:
        err(f"Submittal {sub_id} not found")
    if row["submittal_status"] not in ("pending", "under_review"):
        err(f"Submittal must be pending or under_review to review (current: {row['submittal_status']})")

    review_comments = getattr(args, "review_comments", None) or getattr(args, "notes", None)

    sql, params = dynamic_update("constructclaw_submittal", {
        "submittal_status": decision,
        "review_comments": review_comments,
        "date_returned": LiteralValue("date('now')"),
        "updated_at": LiteralValue("datetime('now')"),
    }, {"id": sub_id})
    conn.execute(sql, params)
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
