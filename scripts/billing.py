"""ConstructClaw -- Billing domain module.

AIA progress billing: schedule of values, progress bills, retention.
14 actions exported via ACTIONS dict (includes approve-progress-bill with cross_skill invoice).
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
from erpclaw_lib.cross_skill import create_invoice, submit_invoice, CrossSkillError
from erpclaw_lib.query import Q, P, Table, Field, fn, Order, insert_row, dynamic_update, now, today

SKILL = "constructclaw"

_t_sov = Table("constructclaw_schedule_of_values")
_t_sov_line = Table("constructclaw_sov_line")
_t_pb = Table("constructclaw_progress_bill")
_t_pb_line = Table("constructclaw_progress_bill_line")
_t_ret = Table("constructclaw_retention")
_t_job = Table("constructclaw_job")
_t_cco = Table("constructclaw_cco")

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


def _q2(val):
    """Quantize a value to 2 decimal places (HALF_UP); return its string form."""
    return str(_d(val).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


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
# record-sov-progress
# ---------------------------------------------------------------------------
def record_sov_progress(conn, args):
    line_id = getattr(args, "sov_line_id", None)
    if not line_id:
        err("--sov-line-id is required")
    c_raw = getattr(args, "completed_to_date", None)
    if c_raw is None or (isinstance(c_raw, str) and c_raw == ""):
        err("--completed-to-date is required")
    row = conn.execute(Q.from_(_t_sov_line).select(_t_sov_line.star).where(_t_sov_line.id == P()).get_sql(), (line_id,)).fetchone()
    if not row:
        err(f"SOV line {line_id} not found")
    item_number = row["item_number"]
    try:
        c_val = Decimal(str(c_raw))
    except Exception:
        err("--completed-to-date must be a non-negative amount")
    if not c_val.is_finite() or c_val < 0:
        err("--completed-to-date must be a non-negative amount")
    m_raw = getattr(args, "materials_stored", None)
    if m_raw is None:
        m_raw = row["materials_stored"]
    try:
        m_val = Decimal(str(m_raw))
    except Exception:
        err("--materials-stored must be a non-negative amount")
    if not m_val.is_finite() or m_val < 0:
        err("--materials-stored must be a non-negative amount")
    c_str = _q2(c_val)
    m_str = _q2(m_val)
    p_str = _q2(row["previous_completed"])
    s_str = _q2(row["scheduled_value"])
    if Decimal(c_str) < Decimal(p_str):
        err(f"Completed to date {c_str} is below the {p_str} already billed on SOV line {item_number}")
    if Decimal(c_str) + Decimal(m_str) > Decimal(s_str):
        err(f"Completed to date {c_str} plus materials stored {m_str} exceeds the scheduled value {s_str} of SOV line {item_number}")
    new_this = _q2(Decimal(c_str) - Decimal(p_str))
    new_bal = _q2(Decimal(s_str) - Decimal(c_str) - Decimal(m_str))
    old_this = _q2(row["this_period"])
    old_mat = _q2(row["materials_stored"])
    guard_prev = row["previous_completed"]
    uq = (Q.update(_t_sov_line).set(_t_sov_line.this_period, P()).set(_t_sov_line.materials_stored, P()).set(_t_sov_line.balance_to_finish, P()).where(_t_sov_line.id == P()).where(_t_sov_line.previous_completed == P()))
    cur = conn.execute(uq.get_sql(), (new_this, m_str, new_bal, line_id, guard_prev))
    if cur.rowcount != 1:
        conn.rollback()
        err(f"SOV line {item_number} changed while progress was being recorded; nothing was written")
    audit(conn, SKILL, "construction-record-sov-progress", "constructclaw_sov_line", line_id,
          old_values={"this_period": old_this, "materials_stored": old_mat},
          new_values={"this_period": new_this, "materials_stored": m_str, "completed_to_date": c_str})
    conn.commit()
    ok({"sov_line_id": line_id, "item_number": item_number, "previous_completed": p_str,
        "this_period": new_this, "materials_stored": m_str, "balance_to_finish": new_bal})


# ---------------------------------------------------------------------------
# add-progress-bill
# ---------------------------------------------------------------------------
def _derive_progress_bill_lines(sov_lines):
    """Derive AIA G703 continuation-sheet line values from SOV line rows.

    For each ``constructclaw_sov_line`` compute the G703 columns:
      total_completed  = previous_completed + this_period + materials_stored (Col G)
      pct_complete     = total_completed / scheduled_value * 100 (Col G / C)
      balance_to_finish= scheduled_value - total_completed (Col C - G)
      retention_amount = retention_pct% of total_completed
    total_completed is recomputed from its components so each derived line is
    self-consistent even if the feeder SOV line carries a stale roll-up value.

    Returns (rows, header_total_completed, header_total_retention). The two
    header totals are footed from the QUANTIZED per-line values that are
    persisted (sum-then-store, not store-then-sum), so the G702 header always
    foots to its G703 lines to the cent — a raw-sum-then-quantize header would
    drift when a per-line value (e.g. retention_pct% of total_completed) carries
    a sub-cent that ROUND_HALF_UP resolves differently line-by-line vs in bulk.
    """
    rows = []
    sum_completed = Decimal("0")
    sum_retention = Decimal("0")
    for sl in sov_lines:
        scheduled_value = _d(sl["scheduled_value"])
        previous_completed = _d(sl["previous_completed"])
        this_period = _d(sl["this_period"])
        materials_stored = _d(sl["materials_stored"])
        retention_pct = _d(sl["retention_pct"])

        line_total_completed = previous_completed + this_period + materials_stored
        retention_amount = (retention_pct / Decimal("100")) * line_total_completed
        balance_to_finish = scheduled_value - line_total_completed
        if scheduled_value > 0:
            pct_complete = (line_total_completed / scheduled_value) * Decimal("100")
        else:
            pct_complete = Decimal("0")

        # Quantize each column to the cent BEFORE it is both persisted and
        # rolled up, so the header footing == the sum of the stored line values.
        q_total_completed = _q2(line_total_completed)
        q_retention_amount = _q2(retention_amount)
        sum_completed += Decimal(q_total_completed)
        sum_retention += Decimal(q_retention_amount)

        rows.append({
            "id": str(uuid.uuid4()),
            "sov_line_id": sl["id"],
            "item_number": sl["item_number"],
            "description": sl["description"],
            "scheduled_value": _q2(scheduled_value),
            "previous_completed": _q2(previous_completed),
            "this_period": _q2(this_period),
            "materials_stored": _q2(materials_stored),
            "total_completed": q_total_completed,
            "pct_complete": _q2(pct_complete),
            "balance_to_finish": _q2(balance_to_finish),
            "retention_amount": q_retention_amount,
        })
    return rows, _q2(sum_completed), _q2(sum_retention)


def add_progress_bill(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")
    job_id = getattr(args, "job_id", None)
    if not job_id:
        err("--job-id is required")

    if not conn.execute(Q.from_(Table("constructclaw_job")).select(Field("id")).where(Field("id") == P()).get_sql(), (job_id,)).fetchone():
        err(f"Job {job_id} not found")

    sov_id = getattr(args, "sov_id", None)

    # G703 continuation-sheet derivation: when the bill is linked to an SOV
    # that carries line items, derive one progress_bill_line per SOV line and
    # roll the header totals up from those derived lines. The derived totals
    # WIN over any caller-supplied flat --total-completed/--total-retention
    # (which are reported back as overridden). With no SOV, or an SOV that has
    # no lines, the legacy header-only path is preserved unchanged.
    sov_lines = []
    if sov_id:
        sov_lines = conn.execute(
            Q.from_(_t_sov_line).select(_t_sov_line.star)
             .where(_t_sov_line.sov_id == P())
             .orderby(_t_sov_line.item_number).get_sql(),
            (sov_id,),
        ).fetchall()
    derived = bool(sov_lines)

    caller_total_completed = getattr(args, "total_completed", None)
    caller_total_retention = getattr(args, "total_retention", None)

    line_rows = []
    if derived:
        line_rows, total_completed, total_retention = _derive_progress_bill_lines(sov_lines)
    else:
        total_completed = caller_total_completed or "0"
        total_retention = caller_total_retention or "0"

    job_row = conn.execute(
        Q.from_(_t_job).select(_t_job.contract_amount, _t_job.contract_type).where(_t_job.id == P()).get_sql(),
        (job_id,),
    ).fetchone()
    contract_type = job_row["contract_type"] if job_row else None
    if contract_type not in ("cost_plus", "time_and_material"):
        base_amount = _d(job_row["contract_amount"]) if job_row else Decimal("0")
        cco_rows = conn.execute(
            Q.from_(_t_cco).select(_t_cco.cost_change).where(_t_cco.job_id == P()).where(_t_cco.cco_status.isin([P(), P()])).get_sql(),
            (job_id, "approved", "executed"),
        ).fetchall()
        approved_total = Decimal("0")
        for cco_row in cco_rows:
            approved_total += _d(cco_row["cost_change"])
        revised = base_amount + approved_total
        tc_capped = _d(total_completed).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        rev_capped = revised.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if tc_capped > rev_capped:
            err(f"Completed to date {_q2(tc_capped)} exceeds the contract amount {_q2(rev_capped)} for job {job_id}; approve a change order to bill more")

    # Get next bill number
    q = Q.from_(_t_pb).select(fn.Coalesce(fn.Max(_t_pb.bill_number), 0).as_("mx")).where(_t_pb.job_id == P())
    max_row = conn.execute(q.get_sql(), (job_id,)).fetchone()
    bill_number = (max_row["mx"] or 0) + 1

    pb_id = str(uuid.uuid4())
    ns = get_next_name(conn, "constructclaw_progress_bill", company_id=args.company_id)

    # Get previous bills total
    # PyPika: skipped — CAST inside COALESCE/SUM aggregate
    prev_row = conn.execute(
        "SELECT COALESCE(SUM(CAST(current_due AS NUMERIC)), 0) as total FROM constructclaw_progress_bill WHERE job_id = ? AND bill_status != 'rejected'",
        (job_id,),
    ).fetchone()
    total_previous = _q2(prev_row["total"])

    current_due = _d(total_completed) - _d(total_retention) - _d(total_previous)
    current_due_str = _q2(current_due)

    sql, _ = insert_row("constructclaw_progress_bill", {"id": P(), "naming_series": P(), "job_id": P(), "sov_id": P(), "bill_number": P(), "period_from": P(), "period_to": P(), "total_completed": P(), "total_retention": P(), "total_previous": P(), "current_due": P(), "notes": P(), "company_id": P()})


    conn.execute(sql,
        (
            pb_id, ns, job_id,
            sov_id,
            bill_number,
            getattr(args, "period_from", None),
            getattr(args, "period_to", None),
            total_completed, total_retention, total_previous,
            current_due_str,
            getattr(args, "notes", None),
            args.company_id,
        ),
    )

    # Write the derived G703 continuation-sheet lines in the same transaction.
    if line_rows:
        line_sql, _ = insert_row("constructclaw_progress_bill_line", {
            "id": P(), "bill_id": P(), "sov_line_id": P(), "item_number": P(),
            "description": P(), "scheduled_value": P(), "previous_completed": P(),
            "this_period": P(), "materials_stored": P(), "total_completed": P(),
            "pct_complete": P(), "balance_to_finish": P(), "retention_amount": P(),
            "company_id": P()})
        for lr in line_rows:
            conn.execute(line_sql, (
                lr["id"], pb_id, lr["sov_line_id"], lr["item_number"],
                lr["description"], lr["scheduled_value"], lr["previous_completed"],
                lr["this_period"], lr["materials_stored"], lr["total_completed"],
                lr["pct_complete"], lr["balance_to_finish"], lr["retention_amount"],
                args.company_id,
            ))

    if derived:
        for sl in sov_lines:
            new_prev = _q2(_d(sl["previous_completed"]) + _d(sl["this_period"]))
            guard_prev = sl["previous_completed"]
            guard_this = sl["this_period"]
            ruq = (Q.update(_t_sov_line).set(_t_sov_line.previous_completed, P()).set(_t_sov_line.this_period, P()).where(_t_sov_line.id == P()).where(_t_sov_line.previous_completed == P()).where(_t_sov_line.this_period == P()))
            rcur = conn.execute(ruq.get_sql(), (new_prev, "0", sl["id"], guard_prev, guard_this))
            if rcur.rowcount != 1:
                conn.rollback()
                err(f"SOV line {sl['item_number']} changed while the bill was being derived; nothing was written")

    if derived:
        audit(conn, SKILL, "construction-add-progress-bill", "constructclaw_progress_bill", pb_id,
              new_values={"bill_number": bill_number, "current_due": current_due_str, "rolled_sov_lines": len(sov_lines)})
    else:
        audit(conn, SKILL, "construction-add-progress-bill", "constructclaw_progress_bill", pb_id,
              new_values={"bill_number": bill_number, "current_due": current_due_str})
    conn.commit()

    result = {
        "progress_bill_id": pb_id, "naming_series": ns,
        "bill_number": bill_number,
        "total_completed": total_completed,
        "total_retention": total_retention,
        "total_previous": total_previous,
        "current_due": current_due_str,
        "bill_status": "draft",
        "totals_source": "sov_lines" if derived else "caller",
    }
    if derived:
        result["line_count"] = len(line_rows)
        # BDFL condition 3: when SOV lines drive the header totals, any flat
        # totals the caller supplied are ignored — surface that explicitly so
        # the override is observable to the existing caller class.
        if caller_total_completed is not None or caller_total_retention is not None:
            result["caller_totals_overridden"] = True
            result["overridden_totals"] = {
                "total_completed": caller_total_completed if caller_total_completed is not None else "0",
                "total_retention": caller_total_retention if caller_total_retention is not None else "0",
            }
    ok(result)


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
_POSTED_SALES_INVOICE_STATUSES = ("submitted", "partially_paid", "paid", "overdue")


def _invoice_status(conn, si_id):
    """Return the status of a sales_invoice row, or None when it is missing."""
    t = Table("sales_invoice")
    found = conn.execute(Q.from_(t).select(t.status).where(t.id == P()).get_sql(), (si_id,)).fetchone()
    if not found:
        return None
    return found["status"]


def approve_progress_bill(conn, args):
    """Approve a submitted progress bill and create a sales invoice.

    Transitions bill from 'submitted' -> 'approved' only when its sales
    invoice exists and is posted. Looks up the job's customer (client_id)
    and creates a real sales_invoice via erpclaw-selling cross_skill
    integration, then auto-submits it to post GL entries. A create or submit
    refusal leaves the bill 'submitted' and names the cause; a draft invoice
    the selling module already committed is linked so a retry submits it
    instead of creating a second one.
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

    q = Q.from_(_t_pb_line).select(_t_pb_line.star).where(_t_pb_line.bill_id == P()).orderby(_t_pb_line.item_number)
    bill_lines = conn.execute(q.get_sql(), (pb_id,)).fetchall()

    linked_si_id = row["sales_invoice_id"] if "sales_invoice_id" in row.keys() else None
    linked_status = _invoice_status(conn, linked_si_id) if linked_si_id else None

    if bill_lines and linked_status not in _POSTED_SALES_INVOICE_STATUSES:
        sum_completed = sum((_d(bl["total_completed"]) for bl in bill_lines), Decimal("0"))
        sum_retention = sum((_d(bl["retention_amount"]) for bl in bill_lines), Decimal("0"))
        if sum_completed != _d(row["total_completed"]) or sum_retention != _d(row["total_retention"]):
            err(f"Progress bill {bill_number} does not foot to its G703 lines; it cannot be invoiced")

    current_due_str = str(current_due.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    description = f"Progress Bill #{bill_number} - {job_name}"
    if bill_lines:
        description = f"{description} (G703: {len(bill_lines)} lines)"
    items = [{
        "description": description,
        "qty": "1",
        "rate": current_due_str,
    }]

    # Create and submit the sales invoice via cross_skill
    db_path = getattr(args, "db_path", None)

    def _refuse_with_draft_link(si_id, cause):
        sql, params = dynamic_update("constructclaw_progress_bill",
            {"sales_invoice_id": si_id, "updated_at": now()},
            {"id": pb_id})
        conn.execute(sql, params)
        audit(conn, SKILL, "construction-approve-progress-bill", "constructclaw_progress_bill", pb_id,
              old_values={"sales_invoice_id": row["sales_invoice_id"]},
              new_values={"sales_invoice_id": si_id})
        conn.commit()
        err(f"Sales invoice {si_id} was created but could not be submitted: {cause}. The progress bill stays submitted and is linked to the draft invoice; approve it again once the cause is fixed.")

    def _submit_or_refuse(si_id):
        try:
            submit_invoice(invoice_id=si_id, db_path=db_path)
        except CrossSkillError as e:
            if _invoice_status(conn, si_id) in _POSTED_SALES_INVOICE_STATUSES:
                return si_id
            _refuse_with_draft_link(si_id, e)
        return si_id

    def _create_and_submit_invoice():
        try:
            inv_result = create_invoice(
                customer_id=customer_id,
                items=items,
                company_id=company_id,
                db_path=db_path,
            )
        except CrossSkillError as e:
            err(f"Sales invoice could not be created for progress bill {bill_number}: {e}")
        # Extract the invoice ID from the response
        inv_data = inv_result.get("sales_invoice", inv_result)
        sales_invoice_id = inv_data.get("id") or inv_data.get("sales_invoice_id")
        if not sales_invoice_id:
            err(f"Sales invoice could not be created for progress bill {bill_number}: the selling module returned no sales_invoice_id")
        return _submit_or_refuse(sales_invoice_id)

    if linked_si_id:
        if linked_status in _POSTED_SALES_INVOICE_STATUSES:
            sales_invoice_id = linked_si_id
        elif linked_status == "draft":
            t_si = Table("sales_invoice")
            si_row = conn.execute(Q.from_(t_si).select(t_si.grand_total).where(t_si.id == P()).get_sql(), (linked_si_id,)).fetchone()
            linked_total = _q2(si_row["grand_total"]) if si_row else _q2("0")
            if linked_total != current_due_str:
                err(f"Progress bill {bill_number} is linked to draft sales invoice {linked_si_id} for {linked_total}, not its current due {current_due_str}; delete that draft and approve again")
            sales_invoice_id = _submit_or_refuse(linked_si_id)
        elif linked_status is None:
            sales_invoice_id = _create_and_submit_invoice()
        else:
            err(f"Progress bill {bill_number} is linked to sales invoice {linked_si_id} in status '{linked_status}'; it cannot be approved against that invoice.")
    else:
        sales_invoice_id = _create_and_submit_invoice()

    # Update the progress bill status and link the invoice
    sql, params = dynamic_update("constructclaw_progress_bill",
        {"bill_status": "approved", "sales_invoice_id": sales_invoice_id,
         "updated_at": now()},
        {"id": pb_id})
    conn.execute(sql, params)

    audit(conn, SKILL, "construction-approve-progress-bill", "constructclaw_progress_bill", pb_id,
          new_values={"bill_status": "approved", "sales_invoice_id": sales_invoice_id})
    conn.commit()

    ok({
        "progress_bill_id": pb_id,
        "bill_status": "approved",
        "current_due": str(current_due.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "sales_invoice_id": sales_invoice_id,
    })


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

    _t_pa = Table("payment_allocation")
    _t_pe = Table("payment_entry")
    _t_si = Table("sales_invoice")

    total_billed = Decimal("0")
    total_retention = Decimal("0")
    total_paid = Decimal("0")

    bill_history = []
    for b in bills:
        due = _d(b["current_due"])
        ret = _d(b["total_retention"])
        total_billed += due
        total_retention = ret  # latest retention total
        # Include linked sales invoice if present
        invoice_id = b["sales_invoice_id"] if "sales_invoice_id" in b.keys() else None
        amount_paid = Decimal("0")
        invoice_status = None
        if invoice_id:
            inv = conn.execute(
                Q.from_(_t_si).select(_t_si.status).where(_t_si.id == P()).get_sql(),
                (invoice_id,)).fetchone()
            if inv is not None:
                invoice_status = inv["status"]
            aq = (Q.from_(_t_pa).join(_t_pe).on(_t_pa.payment_entry_id == _t_pe.id)
                  .select(_t_pa.allocated_amount)
                  .where(_t_pa.voucher_type == P())
                  .where(_t_pa.voucher_id == P())
                  .where(_t_pa.delinked == P())
                  .where(_t_pe.status == P()))
            for ar in conn.execute(
                    aq.get_sql(),
                    ("sales_invoice", invoice_id, 0, "submitted")).fetchall():
                amount_paid += _d(ar["allocated_amount"])
            total_paid += amount_paid
        entry = {
            "bill_number": b["bill_number"],
            "bill_status": b["bill_status"],
            "current_due": str(due.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "period_from": b["period_from"],
            "period_to": b["period_to"],
        }
        if invoice_id:
            entry["sales_invoice_id"] = invoice_id
            entry["amount_paid"] = str(amount_paid.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
            entry["invoice_status"] = invoice_status
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
    "construction-record-sov-progress": record_sov_progress,
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
