"""ConstructClaw -- Subcontractors domain module.

Subcontract management, pay applications, lien waivers.
15 actions exported via ACTIONS dict.
"""
import os
import sys
import uuid
from decimal import Decimal, ROUND_HALF_UP

import importlib.util
if importlib.util.find_spec("erpclaw_lib") is None:
    sys.path.insert(0, os.path.join(os.path.expanduser(os.environ.get("ERPCLAW_HOME", "~/.openclaw/erpclaw")), "lib"))
from erpclaw_lib.naming import get_next_name, register_prefix
from erpclaw_lib.response import ok, err, row_to_dict
from erpclaw_lib.audit import audit
from erpclaw_lib.query import Q, P, Table, Field, fn, Order, insert_row, dynamic_update, now
from erpclaw_lib.cross_skill import create_purchase_invoice, CrossSkillError

SKILL = "constructclaw"

_t_sub = Table("constructclaw_subcontract")
_t_sub_line = Table("constructclaw_subcontract_line")
_t_pa = Table("constructclaw_pay_application")
_t_lw = Table("constructclaw_lien_waiver")

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


def _parse_nonneg_amount(raw, message):
    """Parse a pay-application money input as a finite Decimal of 0 or more."""
    try:
        val = Decimal(str(raw))
    except Exception:
        err(message)
    if not val.is_finite() or val < 0:
        err(message)
    return val


def _certified_to_date(conn, sub_id, exclude_id=None):
    """Sum of current_payment_due over approved/paid applications of a subcontract.

    Rows are selected with a parameterized PyPika query and summed as Decimals
    in Python. exclude_id leaves one application out of the sum (the one being
    approved, whose own stored figure must not certify against itself).
    """
    q = Q.from_(_t_pa).select(_t_pa.current_payment_due).where(_t_pa.subcontract_id == P())
    params = [sub_id]
    q = q.where((_t_pa.pay_app_status == P()) | (_t_pa.pay_app_status == P()))
    params.extend(["approved", "paid"])
    if exclude_id is not None:
        q = q.where(_t_pa.id != P())
        params.append(exclude_id)
    total = Decimal("0")
    for prow in conn.execute(q.get_sql(), params).fetchall():
        total += _d(prow["current_payment_due"])
    return total


# ---------------------------------------------------------------------------
# add-subcontract
# ---------------------------------------------------------------------------
def add_subcontract(conn, args):
    """Create a subcontract, optionally linked to a company supplier."""
    if not getattr(args, "company_id", None):
        err("--company-id is required")
    job_id = getattr(args, "job_id", None)
    if not job_id:
        err("--job-id is required")
    if not getattr(args, "subcontractor_name", None):
        err("--subcontractor-name is required")

    if not conn.execute(Q.from_(Table("constructclaw_job")).select(Field("id")).where(Field("id") == P()).get_sql(), (job_id,)).fetchone():
        err(f"Job {job_id} not found")

    supplier_id = getattr(args, "supplier_id", None)
    if supplier_id:
        sup_t = Table("supplier")
        found = conn.execute(
            Q.from_(sup_t).select(sup_t.id).where(sup_t.id == P()).where(sup_t.company_id == P()).get_sql(),
            (supplier_id, args.company_id),
        ).fetchone()
        if not found:
            err(f"Supplier {supplier_id} not found for company {args.company_id}")

    sub_id = str(uuid.uuid4())
    ns = get_next_name(conn, "constructclaw_subcontract", company_id=args.company_id)

    original_amount = getattr(args, "original_amount", None) or "0"

    sql, _ = insert_row("constructclaw_subcontract", {"id": P(), "naming_series": P(), "subcontract_number": P(), "job_id": P(), "subcontractor_name": P(), "trade": P(), "scope_of_work": P(), "original_amount": P(), "revised_amount": P(), "retention_pct": P(), "insurance_expiry": P(), "license_number": P(), "start_date": P(), "end_date": P(), "notes": P(), "company_id": P(), "supplier_id": P()})


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
            supplier_id,
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
    """Update subcontract fields, including the company supplier link."""
    sub_id = getattr(args, "subcontract_id", None)
    if not sub_id:
        err("--subcontract-id is required")
    row = conn.execute(Q.from_(_t_sub).select(_t_sub.star).where(_t_sub.id == P()).get_sql(), (sub_id,)).fetchone()
    if not row:
        err(f"Subcontract {sub_id} not found")

    data, changed = {}, []
    for field, attr in [
        ("subcontractor_name", "subcontractor_name"), ("trade", "trade"),
        ("scope_of_work", "scope_of_work"), ("original_amount", "original_amount"),
        ("revised_amount", "revised_amount"), ("retention_pct", "retention_pct"),
        ("insurance_expiry", "insurance_expiry"), ("license_number", "license_number"),
        ("start_date", "start_date"), ("end_date", "end_date"), ("notes", "notes"),
    ]:
        val = getattr(args, attr, None)
        if val is not None:
            data[field] = val
            changed.append(field)

    ss = getattr(args, "subcontract_status", None)
    if ss is not None:
        if ss not in VALID_SUB_STATUSES:
            err(f"Invalid subcontract-status: {ss}")
        data["subcontract_status"] = ss
        changed.append("subcontract_status")

    supplier_id = getattr(args, "supplier_id", None)
    if supplier_id:
        sup_t = Table("supplier")
        found = conn.execute(
            Q.from_(sup_t).select(sup_t.id).where(sup_t.id == P()).where(sup_t.company_id == P()).get_sql(),
            (supplier_id, row["company_id"]),
        ).fetchone()
        if not found:
            err(f"Supplier {supplier_id} not found for company {row['company_id']}")
        data["supplier_id"] = supplier_id
        changed.append("supplier_id")

    if not changed:
        err("No fields to update")

    data["updated_at"] = now()
    sql, params = dynamic_update("constructclaw_subcontract", data, {"id": sub_id})
    conn.execute(sql, params)
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
    row = conn.execute(Q.from_(_t_sub).select(_t_sub.star).where(_t_sub.id == P()).get_sql(), (sub_id,)).fetchone()
    if not row:
        err(f"Subcontract {sub_id} not found")

    data = row_to_dict(row)
    q = Q.from_(_t_sub_line).select(_t_sub_line.star).where(_t_sub_line.subcontract_id == P()).orderby(_t_sub_line.line_number)
    lines = conn.execute(q.get_sql(), (sub_id,)).fetchall()
    data["lines"] = [row_to_dict(l) for l in lines]
    ok(data)


# ---------------------------------------------------------------------------
# list-subcontracts
# ---------------------------------------------------------------------------
def list_subcontracts(conn, args):
    t = _t_sub
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
    ss = getattr(args, "subcontract_status", None)
    if ss:
        q_count = q_count.where(t.subcontract_status == P())
        q_rows = q_rows.where(t.subcontract_status == P())
        params.append(ss)
    search = getattr(args, "search", None)
    if search:
        s = f"%{search}%"
        like_crit = (t.subcontractor_name.like(P()) | t.trade.like(P()))
        q_count = q_count.where(like_crit)
        q_rows = q_rows.where(like_crit)
        params.extend([s] * 2)

    limit = getattr(args, "limit", 50) or 50
    offset = getattr(args, "offset", 0) or 0

    total = conn.execute(q_count.get_sql(), params).fetchone()["cnt"]
    q_rows = q_rows.orderby(t.created_at, order=Order.desc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [limit, offset]).fetchall()
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
    q = Q.from_(_t_sub_line).select(fn.Coalesce(fn.Max(_t_sub_line.line_number), 0).as_("mx")).where(_t_sub_line.subcontract_id == P())
    max_row = conn.execute(q.get_sql(), (sub_id,)).fetchone()
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

    q = Q.from_(_t_sub_line).select(_t_sub_line.star).where(_t_sub_line.subcontract_id == P()).orderby(_t_sub_line.line_number)
    rows = conn.execute(q.get_sql(), (sub_id,)).fetchall()
    ok({"lines": [row_to_dict(r) for r in rows], "total_count": len(rows)})


# ---------------------------------------------------------------------------
# approve-subcontract
# ---------------------------------------------------------------------------
def approve_subcontract(conn, args):
    sub_id = getattr(args, "subcontract_id", None)
    if not sub_id:
        err("--subcontract-id is required")
    row = conn.execute(Q.from_(_t_sub).select(_t_sub.star).where(_t_sub.id == P()).get_sql(), (sub_id,)).fetchone()
    if not row:
        err(f"Subcontract {sub_id} not found")
    if row["subcontract_status"] not in ("draft", "pending_approval"):
        err(f"Subcontract must be draft or pending_approval to approve (current: {row['subcontract_status']})")

    sql, params = dynamic_update("constructclaw_subcontract",
        {"subcontract_status": "approved", "updated_at": now()},
        {"id": sub_id})
    conn.execute(sql, params)
    audit(conn, SKILL, "construction-approve-subcontract", "constructclaw_subcontract", sub_id,
          new_values={"subcontract_status": "approved"})
    conn.commit()
    ok({"subcontract_id": sub_id, "subcontract_status": "approved"})


# ---------------------------------------------------------------------------
# add-pay-application
# ---------------------------------------------------------------------------
def add_pay_application(conn, args):
    """Record a cumulative pay application; total earned is capped at the subcontract amount."""
    if not getattr(args, "company_id", None):
        err("--company-id is required")
    sub_id = getattr(args, "subcontract_id", None)
    if not sub_id:
        err("--subcontract-id is required")

    sub = conn.execute(Q.from_(_t_sub).select(_t_sub.star).where(_t_sub.id == P()).get_sql(), (sub_id,)).fetchone()
    if not sub:
        err(f"Subcontract {sub_id} not found")

    # Get next application number
    q = Q.from_(_t_pa).select(fn.Coalesce(fn.Max(_t_pa.application_number), 0).as_("mx")).where(_t_pa.subcontract_id == P())
    max_row = conn.execute(q.get_sql(), (sub_id,)).fetchone()
    app_number = (max_row["mx"] or 0) + 1

    pa_id = str(uuid.uuid4())

    work_raw = getattr(args, "work_completed", None) or "0"
    materials_raw = getattr(args, "materials_stored", None) or "0"
    work_completed = _parse_nonneg_amount(work_raw, "--work-completed must be a non-negative number")
    materials_stored = _parse_nonneg_amount(materials_raw, "--materials-stored must be a non-negative number")

    total_earned = work_completed + materials_stored
    retention_pct = _d(sub["retention_pct"])
    retention_held = (total_earned * retention_pct / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    subcontract_number = sub["subcontract_number"] or sub["naming_series"]
    te_capped = total_earned.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    rev_capped = _d(sub["revised_amount"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if te_capped > rev_capped:
        err(f"Total earned {te_capped} exceeds the subcontract amount {rev_capped} for subcontract {subcontract_number}")

    # Previously certified payments: recomputed at approval time too, so two
    # applications that were open together cannot both certify the same work.
    previous_payments = _certified_to_date(conn, sub_id)

    current_due = total_earned - retention_held - previous_payments

    ns = get_next_name(conn, "constructclaw_pay_application", company_id=args.company_id)

    sql, _ = insert_row("constructclaw_pay_application", {"id": P(), "naming_series": P(), "subcontract_id": P(), "application_number": P(), "period_from": P(), "period_to": P(), "work_completed": P(), "materials_stored": P(), "total_earned": P(), "retention_held": P(), "previous_payments": P(), "current_payment_due": P(), "notes": P(), "company_id": P()})


    conn.execute(sql,
        (
            pa_id, ns, sub_id, app_number,
            getattr(args, "period_from", None),
            getattr(args, "period_to", None),
            work_raw, materials_raw,
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
    t = _t_pa
    q = Q.from_(t).select(t.star)
    params = []

    sub_id = getattr(args, "subcontract_id", None)
    if sub_id:
        q = q.where(t.subcontract_id == P())
        params.append(sub_id)
    cid = getattr(args, "company_id", None)
    if cid:
        q = q.where(t.company_id == P())
        params.append(cid)
    pas = getattr(args, "pay_app_status", None)
    if pas:
        q = q.where(t.pay_app_status == P())
        params.append(pas)

    q = q.orderby(t.application_number, order=Order.desc)
    rows = conn.execute(q.get_sql(), params).fetchall()
    ok({"pay_applications": [row_to_dict(r) for r in rows], "total_count": len(rows)})


# ---------------------------------------------------------------------------
# approve-pay-application
# ---------------------------------------------------------------------------
def approve_pay_application(conn, args):
    """Approve a pay application once, within its subcontract, and post its payable.

    Previous payments are recomputed from the applications already approved or
    paid, so two applications that were open together cannot both certify the
    same work. Approval creates the payable: a draft purchase invoice for the
    subcontract's supplier, made through the buying module and linked to the
    application. An application that already carries a link reuses that invoice
    and never creates a second one. The payable stays a draft; no ledger row is
    written until someone submits it in the buying module.
    """
    pa_id = getattr(args, "pay_application_id", None)
    if not pa_id:
        err("--pay-application-id is required")
    row = conn.execute(Q.from_(_t_pa).select(_t_pa.star).where(_t_pa.id == P()).get_sql(), (pa_id,)).fetchone()
    if not row:
        err(f"Pay application {pa_id} not found")
    if row["pay_app_status"] not in ("draft", "submitted"):
        err(f"Pay application must be draft or submitted to approve (current: {row['pay_app_status']})")

    sub_id = row["subcontract_id"]
    sub = conn.execute(Q.from_(_t_sub).select(_t_sub.star).where(_t_sub.id == P()).get_sql(), (sub_id,)).fetchone()
    if not sub:
        err(f"Subcontract {sub_id} not found")
    subcontract_number = sub["subcontract_number"] or sub["naming_series"]
    naming_series = row["naming_series"]
    supplier_id = row_to_dict(sub).get("supplier_id")
    if not supplier_id:
        err(f"Subcontract {subcontract_number} has no supplier_id set. Assign a supplier to the subcontract before approving a pay application.")

    te = _d(row["total_earned"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    rev = _d(sub["revised_amount"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if te > rev:
        err(f"Total earned {te} exceeds the subcontract amount {rev} for subcontract {subcontract_number}")

    prev = _certified_to_date(conn, sub_id, exclude_id=pa_id).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    ret = _d(row["retention_held"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    due = (te - ret - prev).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if due <= 0:
        err(f"Nothing is due on pay application {naming_series}: total earned {te} less retention {ret} less previous payments {prev} is {due}")

    pa_link = row_to_dict(row).get("purchase_invoice_id")
    if pa_link:
        inv_t = Table("purchase_invoice")
        inv = conn.execute(
            Q.from_(inv_t).select(inv_t.status, inv_t.grand_total, inv_t.supplier_id, inv_t.company_id).where(inv_t.id == P()).get_sql(),
            (pa_link,),
        ).fetchone()
        status = inv["status"] if inv is not None else None
        grand_total = inv["grand_total"] if inv is not None else None
        if inv is None or status == "cancelled":
            err(f"Pay application {naming_series} is linked to purchase invoice {pa_link} in status '{status}'; it cannot be approved against that invoice.")
        if inv["company_id"] != row["company_id"]:
            err(f"Pay application {naming_series} is linked to purchase invoice {pa_link} of another company; it cannot be approved against that invoice.")
        if inv["supplier_id"] != supplier_id:
            err(f"Pay application {naming_series} is linked to purchase invoice {pa_link} for a different supplier than subcontract {subcontract_number}; it cannot be approved against that invoice.")
        if _d(grand_total) != due:
            err(f"Pay application {naming_series} is linked to purchase invoice {pa_link} for {grand_total}, but {due} is due; it cannot be approved against that invoice.")
        pi_id = pa_link
    else:
        items = [{
            "description": f"Pay Application #{row['application_number']} - {sub['subcontractor_name']} ({subcontract_number})",
            "qty": "1",
            "rate": str(due),
        }]
        try:
            result = create_purchase_invoice(
                supplier_id=supplier_id,
                items=items,
                company_id=row["company_id"],
                db_path=getattr(args, "db_path", None),
            )
        except CrossSkillError as e:
            err(f"Purchase invoice could not be created for pay application {naming_series}: {e}")
        pi_id = result.get("purchase_invoice_id") if isinstance(result, dict) else None
        if not pi_id:
            err(f"Purchase invoice could not be created for pay application {naming_series}: the buying module returned no purchase_invoice_id")

    old_values = {
        "pay_app_status": row["pay_app_status"],
        "previous_payments": row["previous_payments"],
        "current_payment_due": row["current_payment_due"],
        "purchase_invoice_id": pa_link,
    }
    new_values = {
        "pay_app_status": "approved",
        "previous_payments": str(prev),
        "current_payment_due": str(due),
        "purchase_invoice_id": pi_id,
    }
    uq = (Q.update(_t_pa)
          .set(_t_pa.pay_app_status, P())
          .set(_t_pa.previous_payments, P())
          .set(_t_pa.current_payment_due, P())
          .set(_t_pa.purchase_invoice_id, P())
          .set(_t_pa.updated_at, now())
          .where(_t_pa.id == P())
          .where((_t_pa.pay_app_status == P()) | (_t_pa.pay_app_status == P())))
    cur = conn.execute(uq.get_sql(), ("approved", str(prev), str(due), pi_id, pa_id, "draft", "submitted"))
    if cur.rowcount != 1:
        conn.rollback()
        err(f"Pay application {naming_series} changed while it was being approved; purchase invoice {pi_id} is not linked to it")
    audit(conn, SKILL, "construction-approve-pay-application", "constructclaw_pay_application", pa_id,
          old_values=old_values, new_values=new_values)
    conn.commit()
    ok({"pay_application_id": pa_id, "pay_app_status": "approved",
        "previous_payments": str(prev), "current_payment_due": str(due),
        "purchase_invoice_id": pi_id})


# ---------------------------------------------------------------------------
# reject-pay-application
# ---------------------------------------------------------------------------
def reject_pay_application(conn, args):
    pa_id = getattr(args, "pay_application_id", None)
    if not pa_id:
        err("--pay-application-id is required")
    row = conn.execute(Q.from_(_t_pa).select(_t_pa.star).where(_t_pa.id == P()).get_sql(), (pa_id,)).fetchone()
    if not row:
        err(f"Pay application {pa_id} not found")
    if row["pay_app_status"] not in ("draft", "submitted"):
        err(f"Pay application must be draft or submitted to reject (current: {row['pay_app_status']})")

    sql, params = dynamic_update("constructclaw_pay_application",
        {"pay_app_status": "rejected", "updated_at": now()},
        {"id": pa_id})
    conn.execute(sql, params)
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
    t = _t_lw
    q = Q.from_(t).select(t.star)
    params = []

    sub_id = getattr(args, "subcontract_id", None)
    if sub_id:
        q = q.where(t.subcontract_id == P())
        params.append(sub_id)
    cid = getattr(args, "company_id", None)
    if cid:
        q = q.where(t.company_id == P())
        params.append(cid)

    q = q.orderby(t.created_at, order=Order.desc)
    rows = conn.execute(q.get_sql(), params).fetchall()
    ok({"lien_waivers": [row_to_dict(r) for r in rows], "total_count": len(rows)})


# ---------------------------------------------------------------------------
# subcontractor-aging-report
# ---------------------------------------------------------------------------
def subcontractor_aging_report(conn, args):
    """Aging per subcontract; retention is the latest certified figure, not a sum."""
    if not getattr(args, "company_id", None):
        err("--company-id is required")

    # PyPika: skipped — NOT IN clause with multiple status values
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

        paid = _certified_to_date(conn, s["id"])
        total_paid += paid

        # retention_held is cumulative to date, so the report reads the latest
        # certified application (highest application_number), never a sum.
        latest_q = (Q.from_(_t_pa).select(_t_pa.retention_held)
                    .where(_t_pa.subcontract_id == P())
                    .where((_t_pa.pay_app_status == P()) | (_t_pa.pay_app_status == P()))
                    .orderby(_t_pa.application_number, order=Order.desc)
                    .limit(1))
        latest_row = conn.execute(latest_q.get_sql(), (s["id"], "approved", "paid")).fetchone()
        ret_held = _d(latest_row["retention_held"]) if latest_row is not None else Decimal("0")
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
