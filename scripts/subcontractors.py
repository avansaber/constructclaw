"""ConstructClaw -- Subcontractors domain module.

Subcontract management, pay applications, lien waivers.
15 actions exported via ACTIONS dict.
"""
import os
import sys
import uuid
from decimal import Decimal, ROUND_HALF_UP

sys.path.insert(0, os.path.expanduser("~/.openclaw/erpclaw/lib"))
from erpclaw_lib.naming import get_next_name, register_prefix
from erpclaw_lib.response import ok, err, row_to_dict
from erpclaw_lib.audit import audit
from erpclaw_lib.query import Q, P, Table, Field, fn, Order, insert_row

SKILL = "constructclaw"

register_prefix("constructclaw_subcontract", "CCSUB-")
register_prefix("constructclaw_pay_application", "CCPA-")

VALID_SUB_STATUSES = (
    "draft", "pending_approval", "approved", "active",
    "on_hold", "complete", "terminated", "cancelled",
)
VALID_PA_STATUSES = ("draft", "submitted", "approved", "rejected", "paid")
VALID_WAIVER_TYPES = (
    "conditional_progress", "unconditional_progress",
    "conditional_final", "unconditional_final",
)
VALID_WAIVER_STATUSES = ("pending", "received", "verified")


def _d(val, default="0"):
    if val is None:
        return Decimal(default)
    return Decimal(str(val))


# ---------------------------------------------------------------------------
# add-subcontract
# ---------------------------------------------------------------------------
def add_subcontract(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")
    job_id = getattr(args, "job_id", None)
    if not job_id:
        err("--job-id is required")
    if not getattr(args, "subcontractor_name", None):
        err("--subcontractor-name is required")

    if not conn.execute(Q.from_(Table("constructclaw_job")).select(Field("id")).where(Field("id") == P()).get_sql(), (job_id,)).fetchone():
        err(f"Job {job_id} not found")

    sub_id = str(uuid.uuid4())
    ns = get_next_name(conn, "constructclaw_subcontract", company_id=args.company_id)

    original_amount = getattr(args, "original_amount", None) or "0"

    sql, _ = insert_row("constructclaw_subcontract", {"id": P(), "naming_series": P(), "subcontract_number": P(), "job_id": P(), "subcontractor_name": P(), "trade": P(), "scope_of_work": P(), "original_amount": P(), "revised_amount": P(), "retention_pct": P(), "insurance_expiry": P(), "license_number": P(), "start_date": P(), "end_date": P(), "notes": P(), "company_id": P()})


    conn.execute(sql,
        (
            sub_id, ns, ns, job_id,
            args.subcontractor_name,
            getattr(args, "trade", None),
            getattr(args, "scope_of_work", None),
            original_amount,
            original_amount,  # revised starts same as original
            getattr(args, "retention_pct", None) or "10",
            getattr(args, "insurance_expiry", None),
            getattr(args, "license_number", None),
            getattr(args, "start_date", None),
            getattr(args, "end_date", None),
            getattr(args, "notes", None),
            args.company_id,
        ),
    )
    audit(conn, SKILL, "construction-add-subcontract", "constructclaw_subcontract", sub_id,
          new_values={"naming_series": ns, "subcontractor_name": args.subcontractor_name})
    conn.commit()
    ok({"subcontract_id": sub_id, "naming_series": ns,
        "subcontractor_name": args.subcontractor_name,
        "subcontract_status": "draft"})


# ---------------------------------------------------------------------------
# update-subcontract
# ---------------------------------------------------------------------------
def update_subcontract(conn, args):
    sub_id = getattr(args, "subcontract_id", None)
    if not sub_id:
        err("--subcontract-id is required")
    row = conn.execute(Q.from_(Table("constructclaw_subcontract")).select(Table("constructclaw_subcontract").star).where(Field("id") == P()).get_sql(), (sub_id,)).fetchone()
    if not row:
        err(f"Subcontract {sub_id} not found")

    updates, params, changed = [], [], []
    for field, attr in [
        ("subcontractor_name", "subcontractor_name"), ("trade", "trade"),
        ("scope_of_work", "scope_of_work"), ("original_amount", "original_amount"),
        ("revised_amount", "revised_amount"), ("retention_pct", "retention_pct"),
        ("insurance_expiry", "insurance_expiry"), ("license_number", "license_number"),
        ("start_date", "start_date"), ("end_date", "end_date"), ("notes", "notes"),
    ]:
        val = getattr(args, attr, None)
        if val is not None:
            updates.append(f"{field} = ?")
            params.append(val)
            changed.append(field)

    ss = getattr(args, "subcontract_status", None)
    if ss is not None:
        if ss not in VALID_SUB_STATUSES:
            err(f"Invalid subcontract-status: {ss}")
        updates.append("subcontract_status = ?")
        params.append(ss)
        changed.append("subcontract_status")

    if not changed:
        err("No fields to update")

    updates.append("updated_at = datetime('now')")
    params.append(sub_id)
    conn.execute(
        f"UPDATE constructclaw_subcontract SET {', '.join(updates)} WHERE id = ?", params
    )
    audit(conn, SKILL, "construction-update-subcontract", "constructclaw_subcontract", sub_id,
          new_values={"updated_fields": changed})
    conn.commit()
    ok({"subcontract_id": sub_id, "updated_fields": changed})


# ---------------------------------------------------------------------------
# get-subcontract
# ---------------------------------------------------------------------------
def get_subcontract(conn, args):
    sub_id = getattr(args, "subcontract_id", None)
    if not sub_id:
        err("--subcontract-id is required")
    row = conn.execute(Q.from_(Table("constructclaw_subcontract")).select(Table("constructclaw_subcontract").star).where(Field("id") == P()).get_sql(), (sub_id,)).fetchone()
    if not row:
        err(f"Subcontract {sub_id} not found")

    data = row_to_dict(row)
    lines = conn.execute(
        "SELECT * FROM constructclaw_subcontract_line WHERE subcontract_id = ? ORDER BY line_number",
        (sub_id,),
    ).fetchall()
    data["lines"] = [row_to_dict(l) for l in lines]
    ok(data)


# ---------------------------------------------------------------------------
# list-subcontracts
# ---------------------------------------------------------------------------
def list_subcontracts(conn, args):
    conditions, params = [], []
    cid = getattr(args, "company_id", None)
    if cid:
        conditions.append("company_id = ?")
        params.append(cid)
    job_id = getattr(args, "job_id", None)
    if job_id:
        conditions.append("job_id = ?")
        params.append(job_id)
    ss = getattr(args, "subcontract_status", None)
    if ss:
        conditions.append("subcontract_status = ?")
        params.append(ss)
    search = getattr(args, "search", None)
    if search:
        conditions.append("(subcontractor_name LIKE ? OR trade LIKE ?)")
        params.extend([f"%{search}%"] * 2)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    limit = getattr(args, "limit", 50) or 50
    offset = getattr(args, "offset", 0) or 0

    total = conn.execute(f"SELECT COUNT(*) as cnt FROM constructclaw_subcontract {where}", params).fetchone()["cnt"]
    rows = conn.execute(
        f"SELECT * FROM constructclaw_subcontract {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()
    ok({"subcontracts": [row_to_dict(r) for r in rows], "total_count": total,
        "limit": limit, "offset": offset})


# ---------------------------------------------------------------------------
# add-subcontract-line
# ---------------------------------------------------------------------------
def add_subcontract_line(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")
    sub_id = getattr(args, "subcontract_id", None)
    if not sub_id:
        err("--subcontract-id is required")
    if not getattr(args, "description", None):
        err("--description is required")

    if not conn.execute(Q.from_(Table("constructclaw_subcontract")).select(Field("id")).where(Field("id") == P()).get_sql(), (sub_id,)).fetchone():
        err(f"Subcontract {sub_id} not found")

    quantity = getattr(args, "quantity", None) or "0"
    unit_cost = getattr(args, "unit_cost", None) or "0"
    amount = getattr(args, "amount", None) or "0"

    if amount == "0" and quantity != "0" and unit_cost != "0":
        amount = str((_d(quantity) * _d(unit_cost)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    line_id = str(uuid.uuid4())
    max_row = conn.execute(
        "SELECT COALESCE(MAX(line_number), 0) as mx FROM constructclaw_subcontract_line WHERE subcontract_id = ?",
        (sub_id,),
    ).fetchone()
    line_number = (max_row["mx"] or 0) + 1

    sql, _ = insert_row("constructclaw_subcontract_line", {"id": P(), "subcontract_id": P(), "line_number": P(), "description": P(), "quantity": P(), "unit": P(), "unit_cost": P(), "amount": P(), "company_id": P()})


    conn.execute(sql,
        (
            line_id, sub_id, line_number,
            args.description, quantity,
            getattr(args, "unit", None) or "ls",
            unit_cost, amount, args.company_id,
        ),
    )
    conn.commit()
    ok({"line_id": line_id, "subcontract_id": sub_id, "line_number": line_number, "amount": amount})


# ---------------------------------------------------------------------------
# list-subcontract-lines
# ---------------------------------------------------------------------------
def list_subcontract_lines(conn, args):
    sub_id = getattr(args, "subcontract_id", None)
    if not sub_id:
        err("--subcontract-id is required")

    rows = conn.execute(
        "SELECT * FROM constructclaw_subcontract_line WHERE subcontract_id = ? ORDER BY line_number",
        (sub_id,),
    ).fetchall()
    ok({"lines": [row_to_dict(r) for r in rows], "total_count": len(rows)})


# ---------------------------------------------------------------------------
# approve-subcontract
# ---------------------------------------------------------------------------
def approve_subcontract(conn, args):
    sub_id = getattr(args, "subcontract_id", None)
    if not sub_id:
        err("--subcontract-id is required")
    row = conn.execute(Q.from_(Table("constructclaw_subcontract")).select(Table("constructclaw_subcontract").star).where(Field("id") == P()).get_sql(), (sub_id,)).fetchone()
    if not row:
        err(f"Subcontract {sub_id} not found")
    if row["subcontract_status"] not in ("draft", "pending_approval"):
        err(f"Subcontract must be draft or pending_approval to approve (current: {row['subcontract_status']})")

    conn.execute(
        "UPDATE constructclaw_subcontract SET subcontract_status = 'approved', updated_at = datetime('now') WHERE id = ?",
        (sub_id,),
    )
    audit(conn, SKILL, "construction-approve-subcontract", "constructclaw_subcontract", sub_id,
          new_values={"subcontract_status": "approved"})
    conn.commit()
    ok({"subcontract_id": sub_id, "subcontract_status": "approved"})


# ---------------------------------------------------------------------------
# add-pay-application
# ---------------------------------------------------------------------------
def add_pay_application(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")
    sub_id = getattr(args, "subcontract_id", None)
    if not sub_id:
        err("--subcontract-id is required")

    sub = conn.execute(Q.from_(Table("constructclaw_subcontract")).select(Table("constructclaw_subcontract").star).where(Field("id") == P()).get_sql(), (sub_id,)).fetchone()
    if not sub:
        err(f"Subcontract {sub_id} not found")

    # Get next application number
    max_row = conn.execute(
        "SELECT COALESCE(MAX(application_number), 0) as mx FROM constructclaw_pay_application WHERE subcontract_id = ?",
        (sub_id,),
    ).fetchone()
    app_number = (max_row["mx"] or 0) + 1

    pa_id = str(uuid.uuid4())
    ns = get_next_name(conn, "constructclaw_pay_application", company_id=args.company_id)

    work_completed = getattr(args, "work_completed", None) or "0"
    materials_stored = getattr(args, "materials_stored", None) or "0"

    total_earned = _d(work_completed) + _d(materials_stored)
    retention_pct = _d(sub["retention_pct"])
    retention_held = (total_earned * retention_pct / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # Get previous payments
    prev_row = conn.execute(
        "SELECT COALESCE(SUM(CAST(current_payment_due AS REAL)), 0) as total FROM constructclaw_pay_application WHERE subcontract_id = ? AND pay_app_status IN ('approved', 'paid')",
        (sub_id,),
    ).fetchone()
    previous_payments = _d(prev_row["total"])

    current_due = total_earned - retention_held - previous_payments

    sql, _ = insert_row("constructclaw_pay_application", {"id": P(), "naming_series": P(), "subcontract_id": P(), "application_number": P(), "period_from": P(), "period_to": P(), "work_completed": P(), "materials_stored": P(), "total_earned": P(), "retention_held": P(), "previous_payments": P(), "current_payment_due": P(), "notes": P(), "company_id": P()})


    conn.execute(sql,
        (
            pa_id, ns, sub_id, app_number,
            getattr(args, "period_from", None),
            getattr(args, "period_to", None),
            work_completed, materials_stored,
            str(total_earned.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            str(retention_held),
            str(previous_payments.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            str(current_due.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            getattr(args, "notes", None),
            args.company_id,
        ),
    )
    audit(conn, SKILL, "construction-add-pay-application", "constructclaw_pay_application", pa_id,
          new_values={"application_number": app_number, "current_payment_due": str(current_due)})
    conn.commit()
    ok({
        "pay_application_id": pa_id, "naming_series": ns,
        "application_number": app_number,
        "total_earned": str(total_earned.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "retention_held": str(retention_held),
        "current_payment_due": str(current_due.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "pay_app_status": "draft",
    })


# ---------------------------------------------------------------------------
# get-pay-application
# ---------------------------------------------------------------------------
def get_pay_application(conn, args):
    pa_id = getattr(args, "pay_application_id", None)
    if not pa_id:
        err("--pay-application-id is required")
    row = conn.execute(Q.from_(Table("constructclaw_pay_application")).select(Table("constructclaw_pay_application").star).where(Field("id") == P()).get_sql(), (pa_id,)).fetchone()
    if not row:
        err(f"Pay application {pa_id} not found")
    ok(row_to_dict(row))


# ---------------------------------------------------------------------------
# list-pay-applications
# ---------------------------------------------------------------------------
def list_pay_applications(conn, args):
    conditions, params = [], []
    sub_id = getattr(args, "subcontract_id", None)
    if sub_id:
        conditions.append("subcontract_id = ?")
        params.append(sub_id)
    cid = getattr(args, "company_id", None)
    if cid:
        conditions.append("company_id = ?")
        params.append(cid)
    pas = getattr(args, "pay_app_status", None)
    if pas:
        conditions.append("pay_app_status = ?")
        params.append(pas)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = conn.execute(
        f"SELECT * FROM constructclaw_pay_application {where} ORDER BY application_number DESC",
        params,
    ).fetchall()
    ok({"pay_applications": [row_to_dict(r) for r in rows], "total_count": len(rows)})


# ---------------------------------------------------------------------------
# approve-pay-application
# ---------------------------------------------------------------------------
def approve_pay_application(conn, args):
    pa_id = getattr(args, "pay_application_id", None)
    if not pa_id:
        err("--pay-application-id is required")
    row = conn.execute(Q.from_(Table("constructclaw_pay_application")).select(Table("constructclaw_pay_application").star).where(Field("id") == P()).get_sql(), (pa_id,)).fetchone()
    if not row:
        err(f"Pay application {pa_id} not found")
    if row["pay_app_status"] not in ("draft", "submitted"):
        err(f"Pay application must be draft or submitted to approve (current: {row['pay_app_status']})")

    conn.execute(
        "UPDATE constructclaw_pay_application SET pay_app_status = 'approved', updated_at = datetime('now') WHERE id = ?",
        (pa_id,),
    )
    audit(conn, SKILL, "construction-approve-pay-application", "constructclaw_pay_application", pa_id,
          new_values={"pay_app_status": "approved"})
    conn.commit()
    ok({"pay_application_id": pa_id, "pay_app_status": "approved"})


# ---------------------------------------------------------------------------
# reject-pay-application
# ---------------------------------------------------------------------------
def reject_pay_application(conn, args):
    pa_id = getattr(args, "pay_application_id", None)
    if not pa_id:
        err("--pay-application-id is required")
    row = conn.execute(Q.from_(Table("constructclaw_pay_application")).select(Table("constructclaw_pay_application").star).where(Field("id") == P()).get_sql(), (pa_id,)).fetchone()
    if not row:
        err(f"Pay application {pa_id} not found")
    if row["pay_app_status"] not in ("draft", "submitted"):
        err(f"Pay application must be draft or submitted to reject (current: {row['pay_app_status']})")

    conn.execute(
        "UPDATE constructclaw_pay_application SET pay_app_status = 'rejected', updated_at = datetime('now') WHERE id = ?",
        (pa_id,),
    )
    audit(conn, SKILL, "construction-reject-pay-application", "constructclaw_pay_application", pa_id,
          new_values={"pay_app_status": "rejected"})
    conn.commit()
    ok({"pay_application_id": pa_id, "pay_app_status": "rejected",
        "notes": getattr(args, "notes", None)})


# ---------------------------------------------------------------------------
# add-lien-waiver
# ---------------------------------------------------------------------------
def add_lien_waiver(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")
    sub_id = getattr(args, "subcontract_id", None)
    if not sub_id:
        err("--subcontract-id is required")

    if not conn.execute(Q.from_(Table("constructclaw_subcontract")).select(Field("id")).where(Field("id") == P()).get_sql(), (sub_id,)).fetchone():
        err(f"Subcontract {sub_id} not found")

    waiver_type = getattr(args, "waiver_type", None) or "conditional_progress"
    if waiver_type not in VALID_WAIVER_TYPES:
        err(f"Invalid waiver-type: {waiver_type}")

    lw_id = str(uuid.uuid4())
    sql, _ = insert_row("constructclaw_lien_waiver", {"id": P(), "subcontract_id": P(), "pay_application_id": P(), "waiver_type": P(), "amount": P(), "through_date": P(), "received_date": P(), "notes": P(), "company_id": P()})

    conn.execute(sql,
        (
            lw_id, sub_id,
            getattr(args, "pay_application_id", None),
            waiver_type,
            getattr(args, "amount", None) or "0",
            getattr(args, "through_date", None),
            getattr(args, "received_date", None),
            getattr(args, "notes", None),
            args.company_id,
        ),
    )
    audit(conn, SKILL, "construction-add-lien-waiver", "constructclaw_lien_waiver", lw_id,
          new_values={"subcontract_id": sub_id, "waiver_type": waiver_type})
    conn.commit()
    ok({"lien_waiver_id": lw_id, "subcontract_id": sub_id,
        "waiver_type": waiver_type, "waiver_status": "pending"})


# ---------------------------------------------------------------------------
# list-lien-waivers
# ---------------------------------------------------------------------------
def list_lien_waivers(conn, args):
    conditions, params = [], []
    sub_id = getattr(args, "subcontract_id", None)
    if sub_id:
        conditions.append("subcontract_id = ?")
        params.append(sub_id)
    cid = getattr(args, "company_id", None)
    if cid:
        conditions.append("company_id = ?")
        params.append(cid)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = conn.execute(
        f"SELECT * FROM constructclaw_lien_waiver {where} ORDER BY created_at DESC",
        params,
    ).fetchall()
    ok({"lien_waivers": [row_to_dict(r) for r in rows], "total_count": len(rows)})


# ---------------------------------------------------------------------------
# subcontractor-aging-report
# ---------------------------------------------------------------------------
def subcontractor_aging_report(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")

    subs = conn.execute(
        "SELECT * FROM constructclaw_subcontract WHERE company_id = ? AND subcontract_status NOT IN ('cancelled','terminated')",
        (args.company_id,),
    ).fetchall()

    report = []
    total_committed = Decimal("0")
    total_paid = Decimal("0")
    total_retention = Decimal("0")

    for s in subs:
        revised = _d(s["revised_amount"])
        total_committed += revised

        paid_row = conn.execute(
            "SELECT COALESCE(SUM(CAST(current_payment_due AS REAL)), 0) as total FROM constructclaw_pay_application WHERE subcontract_id = ? AND pay_app_status IN ('approved','paid')",
            (s["id"],),
        ).fetchone()
        paid = _d(paid_row["total"])
        total_paid += paid

        ret_held_row = conn.execute(
            "SELECT COALESCE(SUM(CAST(retention_held AS REAL)), 0) as total FROM constructclaw_pay_application WHERE subcontract_id = ? AND pay_app_status IN ('approved','paid')",
            (s["id"],),
        ).fetchone()
        ret_held = _d(ret_held_row["total"])
        total_retention += ret_held

        remaining = revised - paid - ret_held
        report.append({
            "subcontract_id": s["id"],
            "subcontractor_name": s["subcontractor_name"],
            "trade": s["trade"],
            "contract_amount": str(revised.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "paid": str(paid.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "retention_held": str(ret_held.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "remaining": str(remaining.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        })

    ok({
        "company_id": args.company_id,
        "subcontractors": report,
        "total_count": len(report),
        "total_committed": str(total_committed.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "total_paid": str(total_paid.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "total_retention": str(total_retention.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
    })


# ---------------------------------------------------------------------------
# ACTIONS registry
# ---------------------------------------------------------------------------
ACTIONS = {
    "construction-add-subcontract": add_subcontract,
    "construction-update-subcontract": update_subcontract,
    "construction-get-subcontract": get_subcontract,
    "construction-list-subcontracts": list_subcontracts,
    "construction-add-subcontract-line": add_subcontract_line,
    "construction-list-subcontract-lines": list_subcontract_lines,
    "construction-approve-subcontract": approve_subcontract,
    "construction-add-pay-application": add_pay_application,
    "construction-get-pay-application": get_pay_application,
    "construction-list-pay-applications": list_pay_applications,
    "construction-approve-pay-application": approve_pay_application,
    "construction-reject-pay-application": reject_pay_application,
    "construction-add-lien-waiver": add_lien_waiver,
    "construction-list-lien-waivers": list_lien_waivers,
    "construction-subcontractor-aging-report": subcontractor_aging_report,
}
