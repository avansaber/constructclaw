"""ConstructClaw -- Billing domain module.

AIA progress billing: schedule of values, progress bills, retention.
14 actions exported via ACTIONS dict (includes approve-progress-bill with cross_skill invoice).
"""
import os
import sys
import uuid
from decimal import Decimal, ROUND_HALF_UP

sys.path.insert(0, os.path.join(os.path.expanduser(os.environ.get("ERPCLAW_HOME", "~/.openclaw/erpclaw")), "lib"))
from erpclaw_lib.naming import get_next_name, register_prefix
from erpclaw_lib.response import ok, err, row_to_dict
from erpclaw_lib.audit import audit
from erpclaw_lib.cross_skill import create_invoice, submit_invoice, CrossSkillError
from erpclaw_lib.query import Q, P, Table, Field, fn, Order, insert_row, dynamic_update, now, today

SKILL = "constructclaw"

_t_sov = Table("constructclaw_schedule_of_values")
_t_sov_line = Table("constructclaw_sov_line")
_t_pb = Table("constructclaw_progress_bill")
_t_pb_line = Table("constructclaw_progress_bill_line")
_t_ret = Table("constructclaw_retention")
_t_job = Table("constructclaw_job")

register_prefix("constructclaw_schedule_of_values", "CCSOV-")
register_prefix("constructclaw_progress_bill", "CCPB-")

VALID_SOV_STATUSES = ("draft", "approved", "active", "closed")
VALID_BILL_STATUSES = ("draft", "submitted", "approved", "paid", "rejected")
VALID_RETENTION_TYPES = ("owner", "subcontractor")
VALID_RETENTION_STATUSES = ("held", "partial_release", "released")


def _d(val, default="0"):
    if val is None:
        return Decimal(default)
    return Decimal(str(val))


# ---------------------------------------------------------------------------
# add-schedule-of-values
# ---------------------------------------------------------------------------
def add_schedule_of_values(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")
    job_id = getattr(args, "job_id", None)
    if not job_id:
        err("--job-id is required")
    if not getattr(args, "name", None):
        err("--name is required")

    if not conn.execute(Q.from_(Table("constructclaw_job")).select(Field("id")).where(Field("id") == P()).get_sql(), (job_id,)).fetchone():
        err(f"Job {job_id} not found")

    sov_id = str(uuid.uuid4())
    ns = get_next_name(conn, "constructclaw_schedule_of_values", company_id=args.company_id)

    total_contract = getattr(args, "total_contract", None) or "0"

    sql, _ = insert_row("constructclaw_schedule_of_values", {"id": P(), "naming_series": P(), "sov_number": P(), "job_id": P(), "name": P(), "total_contract": P(), "revised_contract": P(), "notes": P(), "company_id": P()})


    conn.execute(sql,
        (
            sov_id, ns, ns, job_id,
            args.name, total_contract, total_contract,
            getattr(args, "notes", None),
            args.company_id,
        ),
    )
    audit(conn, SKILL, "construction-add-schedule-of-values", "constructclaw_schedule_of_values", sov_id,
          new_values={"naming_series": ns, "name": args.name})
    conn.commit()
    ok({"sov_id": sov_id, "naming_series": ns, "name": args.name,
        "sov_status": "draft"})


# ---------------------------------------------------------------------------
# get-schedule-of-values
# ---------------------------------------------------------------------------
def get_schedule_of_values(conn, args):
    sov_id = getattr(args, "sov_id", None)
    if not sov_id:
        err("--sov-id is required")
    row = conn.execute(Q.from_(_t_sov).select(_t_sov.star).where(_t_sov.id == P()).get_sql(), (sov_id,)).fetchone()
    if not row:
        err(f"Schedule of values {sov_id} not found")

    data = row_to_dict(row)
    q = Q.from_(_t_sov_line).select(_t_sov_line.star).where(_t_sov_line.sov_id == P()).orderby(_t_sov_line.item_number)
    lines = conn.execute(q.get_sql(), (sov_id,)).fetchall()
    data["lines"] = [row_to_dict(l) for l in lines]
    ok(data)


# ---------------------------------------------------------------------------
# list-schedules-of-values
# ---------------------------------------------------------------------------
def list_schedules_of_values(conn, args):
    t = _t_sov
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

    q = q.orderby(t.created_at, order=Order.desc)
    rows = conn.execute(q.get_sql(), params).fetchall()
    ok({"schedules_of_values": [row_to_dict(r) for r in rows], "total_count": len(rows)})


# ---------------------------------------------------------------------------
# add-sov-line
# ---------------------------------------------------------------------------
def add_sov_line(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")
    sov_id = getattr(args, "sov_id", None)
    if not sov_id:
        err("--sov-id is required")
    if not getattr(args, "description", None):
        err("--description is required")

    if not conn.execute(Q.from_(Table("constructclaw_schedule_of_values")).select(Field("id")).where(Field("id") == P()).get_sql(), (sov_id,)).fetchone():
        err(f"Schedule of values {sov_id} not found")

    item_number = getattr(args, "item_number", None) or "1"
    scheduled_value = getattr(args, "scheduled_value", None) or "0"
    retention_pct = getattr(args, "retention_pct", None) or "10"

    line_id = str(uuid.uuid4())
    balance = scheduled_value  # initially, balance = scheduled value

    sql, _ = insert_row("constructclaw_sov_line", {"id": P(), "sov_id": P(), "item_number": P(), "description": P(), "scheduled_value": P(), "balance_to_finish": P(), "retention_pct": P(), "company_id": P()})


    conn.execute(sql,
        (
            line_id, sov_id, item_number,
            args.description, scheduled_value,
            balance, retention_pct,
            args.company_id,
        ),
    )
    conn.commit()
    ok({"sov_line_id": line_id, "sov_id": sov_id, "item_number": item_number,
        "scheduled_value": scheduled_value})


# ---------------------------------------------------------------------------
# list-sov-lines
# ---------------------------------------------------------------------------
def list_sov_lines(conn, args):
    sov_id = getattr(args, "sov_id", None)
    if not sov_id:
        err("--sov-id is required")

    q = Q.from_(_t_sov_line).select(_t_sov_line.star).where(_t_sov_line.sov_id == P()).orderby(_t_sov_line.item_number)
    rows = conn.execute(q.get_sql(), (sov_id,)).fetchall()
    ok({"sov_lines": [row_to_dict(r) for r in rows], "total_count": len(rows)})


# ---------------------------------------------------------------------------
# add-progress-bill
# ---------------------------------------------------------------------------
def add_progress_bill(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")
    job_id = getattr(args, "job_id", None)
    if not job_id:
        err("--job-id is required")

    if not conn.execute(Q.from_(Table("constructclaw_job")).select(Field("id")).where(Field("id") == P()).get_sql(), (job_id,)).fetchone():
        err(f"Job {job_id} not found")

    # Get next bill number
    q = Q.from_(_t_pb).select(fn.Coalesce(fn.Max(_t_pb.bill_number), 0).as_("mx")).where(_t_pb.job_id == P())
    max_row = conn.execute(q.get_sql(), (job_id,)).fetchone()
    bill_number = (max_row["mx"] or 0) + 1

    pb_id = str(uuid.uuid4())
    ns = get_next_name(conn, "constructclaw_progress_bill", company_id=args.company_id)

    total_completed = getattr(args, "total_completed", None) or "0"
    total_retention = getattr(args, "total_retention", None) or "0"

    # Get previous bills total
    # PyPika: skipped — CAST inside COALESCE/SUM aggregate
    prev_row = conn.execute(
        "SELECT COALESCE(SUM(CAST(current_due AS NUMERIC)), 0) as total FROM constructclaw_progress_bill WHERE job_id = ? AND bill_status != 'rejected'",
        (job_id,),
    ).fetchone()
    total_previous = str(_d(prev_row["total"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    current_due = _d(total_completed) - _d(total_retention) - _d(total_previous)
    current_due_str = str(current_due.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    sql, _ = insert_row("constructclaw_progress_bill", {"id": P(), "naming_series": P(), "job_id": P(), "sov_id": P(), "bill_number": P(), "period_from": P(), "period_to": P(), "total_completed": P(), "total_retention": P(), "total_previous": P(), "current_due": P(), "notes": P(), "company_id": P()})


    conn.execute(sql,
        (
            pb_id, ns, job_id,
            getattr(args, "sov_id", None),
            bill_number,
            getattr(args, "period_from", None),
            getattr(args, "period_to", None),
            total_completed, total_retention, total_previous,
            current_due_str,
            getattr(args, "notes", None),
            args.company_id,
        ),
    )
    audit(conn, SKILL, "construction-add-progress-bill", "constructclaw_progress_bill", pb_id,
          new_values={"bill_number": bill_number, "current_due": current_due_str})
    conn.commit()
    ok({
        "progress_bill_id": pb_id, "naming_series": ns,
        "bill_number": bill_number,
        "total_completed": total_completed,
        "total_retention": total_retention,
        "total_previous": total_previous,
        "current_due": current_due_str,
        "bill_status": "draft",
    })


# ---------------------------------------------------------------------------
# get-progress-bill
# ---------------------------------------------------------------------------
def get_progress_bill(conn, args):
    pb_id = getattr(args, "progress_bill_id", None)
    if not pb_id:
        err("--progress-bill-id is required")
    row = conn.execute(Q.from_(_t_pb).select(_t_pb.star).where(_t_pb.id == P()).get_sql(), (pb_id,)).fetchone()
    if not row:
        err(f"Progress bill {pb_id} not found")

    data = row_to_dict(row)
    q = Q.from_(_t_pb_line).select(_t_pb_line.star).where(_t_pb_line.bill_id == P()).orderby(_t_pb_line.item_number)
    lines = conn.execute(q.get_sql(), (pb_id,)).fetchall()
    data["lines"] = [row_to_dict(l) for l in lines]
    ok(data)


# ---------------------------------------------------------------------------
# list-progress-bills
# ---------------------------------------------------------------------------
def list_progress_bills(conn, args):
    t = _t_pb
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
    bs = getattr(args, "bill_status", None)
    if bs:
        q = q.where(t.bill_status == P())
        params.append(bs)

    q = q.orderby(t.bill_number, order=Order.desc)
    rows = conn.execute(q.get_sql(), params).fetchall()
    ok({"progress_bills": [row_to_dict(r) for r in rows], "total_count": len(rows)})


# ---------------------------------------------------------------------------
# submit-progress-bill
# ---------------------------------------------------------------------------
def submit_progress_bill(conn, args):
    pb_id = getattr(args, "progress_bill_id", None)
    if not pb_id:
        err("--progress-bill-id is required")
    row = conn.execute(Q.from_(_t_pb).select(_t_pb.star).where(_t_pb.id == P()).get_sql(), (pb_id,)).fetchone()
    if not row:
        err(f"Progress bill {pb_id} not found")
    if row["bill_status"] != "draft":
        err(f"Progress bill must be in draft status to submit (current: {row['bill_status']})")

    sql, params = dynamic_update("constructclaw_progress_bill",
        {"bill_status": "submitted", "updated_at": now()},
        {"id": pb_id})
    conn.execute(sql, params)
    audit(conn, SKILL, "construction-submit-progress-bill", "constructclaw_progress_bill", pb_id,
          new_values={"bill_status": "submitted"})
    conn.commit()
    ok({"progress_bill_id": pb_id, "bill_status": "submitted"})


# ---------------------------------------------------------------------------
# approve-progress-bill — creates sales_invoice via cross_skill
# ---------------------------------------------------------------------------
def approve_progress_bill(conn, args):
    """Approve a submitted progress bill and create a sales invoice.

    Transitions bill from 'submitted' -> 'approved'.
    Looks up the job's customer (client_id) and creates a real
    sales_invoice via erpclaw-selling cross_skill integration.
    The invoice is auto-submitted to post GL entries.
    """
    pb_id = getattr(args, "progress_bill_id", None)
    if not pb_id:
        err("--progress-bill-id is required")
    row = conn.execute(Q.from_(_t_pb).select(_t_pb.star).where(_t_pb.id == P()).get_sql(), (pb_id,)).fetchone()
    if not row:
        err(f"Progress bill {pb_id} not found")
    if row["bill_status"] != "submitted":
        err(f"Progress bill must be in submitted status to approve (current: {row['bill_status']})")

    current_due = _d(row["current_due"])
    if current_due <= 0:
        err(f"Cannot approve progress bill with zero or negative current_due ({current_due})")

    # Look up the job to get customer (client_id) and company_id
    job = conn.execute(Q.from_(_t_job).select(_t_job.star).where(_t_job.id == P()).get_sql(), (row["job_id"],)).fetchone()
    if not job:
        err(f"Job {row['job_id']} not found")

    customer_id = job["client_id"]
    if not customer_id:
        err(f"Job {row['job_id']} has no client_id set. Assign a customer to the job before approving a progress bill.")

    company_id = row["company_id"]
    bill_number = row["bill_number"]
    job_name = job["name"]

    # Build invoice line items — single line for the progress bill
    # This preserves the AIA G702/G703 structure in constructclaw
    # while creating a proper sales invoice for GL posting
    items = [{
        "description": f"Progress Bill #{bill_number} - {job_name}",
        "qty": "1",
        "rate": str(current_due.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
    }]

    # If the bill has detail lines, include them as additional context
    q = Q.from_(_t_pb_line).select(_t_pb_line.star).where(_t_pb_line.bill_id == P()).orderby(_t_pb_line.item_number)
    bill_lines = conn.execute(q.get_sql(), (pb_id,)).fetchall()

    if bill_lines:
        # Replace single-line with detailed SOV lines
        items = []
        for bl in bill_lines:
            this_period = _d(bl["this_period"])
            if this_period > 0:
                items.append({
                    "description": f"[{bl['item_number']}] {bl['description']}",
                    "qty": "1",
                    "rate": str(this_period.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
                })
        # Fallback if all line this_period are zero
        if not items:
            items = [{
                "description": f"Progress Bill #{bill_number} - {job_name}",
                "qty": "1",
                "rate": str(current_due.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            }]

    # Create and submit the sales invoice via cross_skill
    db_path = getattr(args, "db_path", None)
    sales_invoice_id = None

    try:
        inv_result = create_invoice(
            customer_id=customer_id,
            items=items,
            company_id=company_id,
            remarks=f"ConstructClaw Progress Bill #{bill_number} for job {job_name}",
            db_path=db_path,
        )
        # Extract the invoice ID from the response
        inv_data = inv_result.get("sales_invoice", inv_result)
        sales_invoice_id = inv_data.get("id") or inv_data.get("sales_invoice_id")

        if sales_invoice_id:
            # Auto-submit the invoice to post GL entries
            try:
                submit_invoice(invoice_id=sales_invoice_id, db_path=db_path)
            except CrossSkillError:
                # Invoice created but submit failed — still link it
                pass

    except CrossSkillError as e:
        # Invoice creation failed — approve the bill but warn about missing invoice
        # This allows the billing workflow to continue even without erpclaw-selling installed
        sales_invoice_id = None
        import sys as _sys
        _sys.stderr.write(f"[constructclaw] Warning: Could not create sales invoice: {e}\n")

    # Update the progress bill status and link the invoice
    sql, params = dynamic_update("constructclaw_progress_bill",
        {"bill_status": "approved", "sales_invoice_id": sales_invoice_id,
         "updated_at": now()},
        {"id": pb_id})
    conn.execute(sql, params)

    audit(conn, SKILL, "construction-approve-progress-bill", "constructclaw_progress_bill", pb_id,
          new_values={"bill_status": "approved", "sales_invoice_id": sales_invoice_id})
    conn.commit()

    result = {
        "progress_bill_id": pb_id,
        "bill_status": "approved",
        "current_due": str(current_due.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
    }
    if sales_invoice_id:
        result["sales_invoice_id"] = sales_invoice_id
    else:
        result["warning"] = "Sales invoice could not be created. erpclaw-selling may not be installed."

    ok(result)


# ---------------------------------------------------------------------------
# add-retention
# ---------------------------------------------------------------------------
def add_retention(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")
    job_id = getattr(args, "job_id", None)
    if not job_id:
        err("--job-id is required")

    if not conn.execute(Q.from_(Table("constructclaw_job")).select(Field("id")).where(Field("id") == P()).get_sql(), (job_id,)).fetchone():
        err(f"Job {job_id} not found")

    retention_type = getattr(args, "retention_type", None) or "owner"
    if retention_type not in VALID_RETENTION_TYPES:
        err(f"Invalid retention-type: {retention_type}")

    amount_held = getattr(args, "amount_held", None) or "0"
    ret_id = str(uuid.uuid4())

    sql, _ = insert_row("constructclaw_retention", {"id": P(), "job_id": P(), "subcontract_id": P(), "retention_type": P(), "amount_held": P(), "balance": P(), "notes": P(), "company_id": P()})


    conn.execute(sql,
        (
            ret_id, job_id,
            getattr(args, "subcontract_id", None),
            retention_type, amount_held, amount_held,
            getattr(args, "notes", None),
            args.company_id,
        ),
    )
    audit(conn, SKILL, "construction-add-retention", "constructclaw_retention", ret_id,
          new_values={"job_id": job_id, "amount_held": amount_held})
    conn.commit()
    ok({"retention_id": ret_id, "job_id": job_id, "amount_held": amount_held,
        "retention_status": "held"})


# ---------------------------------------------------------------------------
# list-retentions
# ---------------------------------------------------------------------------
def list_retentions(conn, args):
    t = _t_ret
    q = Q.from_(t).select(t.star)
    params = []

    job_id = getattr(args, "job_id", None)
    if job_id:
        q = q.where(t.job_id == P())
        params.append(job_id)
    cid = getattr(args, "company_id", None)
    if cid:
        q = q.where(t.company_id == P())
        params.append(cid)
    rs = getattr(args, "retention_status", None)
    if rs:
        q = q.where(t.retention_status == P())
        params.append(rs)

    q = q.orderby(t.created_at, order=Order.desc)
    rows = conn.execute(q.get_sql(), params).fetchall()
    ok({"retentions": [row_to_dict(r) for r in rows], "total_count": len(rows)})


# ---------------------------------------------------------------------------
# release-retention
# ---------------------------------------------------------------------------
def release_retention(conn, args):
    ret_id = getattr(args, "retention_id", None)
    if not ret_id:
        err("--retention-id is required")
    row = conn.execute(Q.from_(_t_ret).select(_t_ret.star).where(_t_ret.id == P()).get_sql(), (ret_id,)).fetchone()
    if not row:
        err(f"Retention {ret_id} not found")
    if row["retention_status"] == "released":
        err("Retention already fully released")

    release_amount = getattr(args, "release_amount", None)
    balance = _d(row["balance"])

    if release_amount:
        release = _d(release_amount)
        if release > balance:
            err(f"Release amount ({release}) exceeds balance ({balance})")
        new_balance = balance - release
        new_released = _d(row["amount_released"]) + release
    else:
        # Full release
        release = balance
        new_balance = Decimal("0")
        new_released = _d(row["amount_released"]) + release

    new_status = "released" if new_balance == 0 else "partial_release"

    sql, params = dynamic_update("constructclaw_retention", {
        "amount_released": str(new_released.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "balance": str(new_balance.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "retention_status": new_status,
        "release_date": today(),
        "updated_at": now(),
    }, {"id": ret_id})
    conn.execute(sql, params)
    audit(conn, SKILL, "construction-release-retention", "constructclaw_retention", ret_id,
          new_values={"release_amount": str(release), "new_status": new_status})
    conn.commit()
    ok({
        "retention_id": ret_id,
        "released_amount": str(release.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "new_balance": str(new_balance.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "retention_status": new_status,
    })


# ---------------------------------------------------------------------------
# billing-summary
# ---------------------------------------------------------------------------
def billing_summary(conn, args):
    job_id = getattr(args, "job_id", None)
    if not job_id:
        err("--job-id is required")

    job = conn.execute(Q.from_(_t_job).select(_t_job.star).where(_t_job.id == P()).get_sql(), (job_id,)).fetchone()
    if not job:
        err(f"Job {job_id} not found")

    q = (Q.from_(_t_pb).select(_t_pb.star)
         .where(_t_pb.job_id == P())
         .where(_t_pb.bill_status != P())
         .orderby(_t_pb.bill_number))
    bills = conn.execute(q.get_sql(), (job_id, "rejected")).fetchall()

    total_billed = Decimal("0")
    total_retention = Decimal("0")
    total_paid = Decimal("0")

    bill_history = []
    for b in bills:
        due = _d(b["current_due"])
        ret = _d(b["total_retention"])
        total_billed += due
        total_retention = ret  # latest retention total
        if b["bill_status"] == "paid":
            total_paid += due
        entry = {
            "bill_number": b["bill_number"],
            "bill_status": b["bill_status"],
            "current_due": str(due.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "period_from": b["period_from"],
            "period_to": b["period_to"],
        }
        # Include linked sales invoice if present
        invoice_id = b["sales_invoice_id"] if "sales_invoice_id" in b.keys() else None
        if invoice_id:
            entry["sales_invoice_id"] = invoice_id
        bill_history.append(entry)

    contract = _d(job["contract_amount"])
    remaining = contract - total_billed - total_retention

    ok({
        "job_id": job_id,
        "job_name": job["name"],
        "contract_amount": str(contract.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "total_billed": str(total_billed.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "total_retention": str(total_retention.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "total_paid": str(total_paid.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "remaining_to_bill": str(remaining.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "bill_count": len(bills),
        "bill_history": bill_history,
    })


# ---------------------------------------------------------------------------
# ACTIONS registry
# ---------------------------------------------------------------------------
ACTIONS = {
    "construction-add-schedule-of-values": add_schedule_of_values,
    "construction-get-schedule-of-values": get_schedule_of_values,
    "construction-list-schedules-of-values": list_schedules_of_values,
    "construction-add-sov-line": add_sov_line,
    "construction-list-sov-lines": list_sov_lines,
    "construction-add-progress-bill": add_progress_bill,
    "construction-get-progress-bill": get_progress_bill,
    "construction-list-progress-bills": list_progress_bills,
    "construction-submit-progress-bill": submit_progress_bill,
    "construction-approve-progress-bill": approve_progress_bill,
    "construction-add-retention": add_retention,
    "construction-list-retentions": list_retentions,
    "construction-release-retention": release_retention,
    "construction-billing-summary": billing_summary,
}
