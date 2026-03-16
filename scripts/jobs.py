"""ConstructClaw -- Jobs domain module.

Job costing: jobs, cost codes, cost entries, commitments, and reports.
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
from erpclaw_lib.query import Q, P, Table, Field, fn, Order, insert_row, LiteralValue, dynamic_update

SKILL = "constructclaw"

_t_job = Table("constructclaw_job")
_t_cc = Table("constructclaw_cost_code")
_t_ce = Table("constructclaw_cost_entry")
_t_cm = Table("constructclaw_commitment")
_t_pb = Table("constructclaw_progress_bill")
_t_cco = Table("constructclaw_cco")

register_prefix("constructclaw_job", "CCJOB-")
register_prefix("constructclaw_cost_code", "CCCC-")
register_prefix("constructclaw_cost_entry", "CCCE-")
register_prefix("constructclaw_commitment", "CCCM-")

VALID_JOB_TYPES = (
    "general", "residential", "commercial", "industrial",
    "infrastructure", "renovation", "other",
)
VALID_CONTRACT_TYPES = (
    "lump_sum", "cost_plus", "time_and_material",
    "unit_price", "gmp", "design_build",
)
VALID_JOB_STATUSES = (
    "planning", "bidding", "awarded", "active",
    "on_hold", "substantially_complete", "closed", "cancelled",
)
VALID_COMMITMENT_STATUSES = ("draft", "approved", "open", "closed", "cancelled")
VALID_COST_CATEGORIES = ("labor", "material", "equipment", "subcontract", "overhead", "other")


def _d(val, default="0"):
    """Safely convert to Decimal."""
    if val is None:
        return Decimal(default)
    return Decimal(str(val))


# ---------------------------------------------------------------------------
# add-job
# ---------------------------------------------------------------------------
def add_job(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")
    if not getattr(args, "name", None):
        err("--name is required")

    if not conn.execute(Q.from_(Table("company")).select(Field("id")).where(Field("id") == P()).get_sql(), (args.company_id,)).fetchone():
        err(f"Company {args.company_id} not found")

    job_type = getattr(args, "job_type", None) or "general"
    if job_type not in VALID_JOB_TYPES:
        err(f"Invalid job-type: {job_type}")

    contract_type = getattr(args, "contract_type", None) or "lump_sum"
    if contract_type not in VALID_CONTRACT_TYPES:
        err(f"Invalid contract-type: {contract_type}")

    job_id = str(uuid.uuid4())
    ns = get_next_name(conn, "constructclaw_job", company_id=args.company_id)

    sql, _ = insert_row("constructclaw_job", {"id": P(), "naming_series": P(), "job_number": P(), "name": P(), "description": P(), "client_name": P(), "client_id": P(), "project_manager": P(), "superintendent": P(), "job_type": P(), "contract_type": P(), "contract_amount": P(), "start_date": P(), "end_date": P(), "address": P(), "city": P(), "state": P(), "zip_code": P(), "notes": P(), "company_id": P()})


    conn.execute(sql,
        (
            job_id, ns, ns,
            args.name,
            getattr(args, "description", None),
            getattr(args, "client_name", None),
            getattr(args, "client_id", None),
            getattr(args, "project_manager", None),
            getattr(args, "superintendent", None),
            job_type,
            contract_type,
            getattr(args, "contract_amount", None) or "0",
            getattr(args, "start_date", None),
            getattr(args, "end_date", None),
            getattr(args, "address", None),
            getattr(args, "city", None),
            getattr(args, "state", None),
            getattr(args, "zip_code", None),
            getattr(args, "notes", None),
            args.company_id,
        ),
    )
    audit(conn, SKILL, "construction-add-job", "constructclaw_job", job_id,
          new_values={"naming_series": ns, "name": args.name})
    conn.commit()
    ok({"job_id": job_id, "naming_series": ns, "name": args.name,
        "job_status": "planning", "job_type": job_type})


# ---------------------------------------------------------------------------
# update-job
# ---------------------------------------------------------------------------
def update_job(conn, args):
    job_id = getattr(args, "job_id", None)
    if not job_id:
        err("--job-id is required")
    row = conn.execute(Q.from_(_t_job).select(_t_job.star).where(_t_job.id == P()).get_sql(), (job_id,)).fetchone()
    if not row:
        err(f"Job {job_id} not found")

    data, changed = {}, []

    for field, attr in [
        ("name", "name"), ("description", "description"),
        ("client_name", "client_name"), ("client_id", "client_id"),
        ("project_manager", "project_manager"), ("superintendent", "superintendent"),
        ("contract_amount", "contract_amount"),
        ("start_date", "start_date"), ("end_date", "end_date"),
        ("actual_start_date", "actual_start_date"), ("actual_end_date", "actual_end_date"),
        ("address", "address"), ("city", "city"), ("state", "state"),
        ("zip_code", "zip_code"), ("percent_complete", "percent_complete"),
        ("notes", "notes"),
    ]:
        val = getattr(args, attr, None)
        if val is not None:
            data[field] = val
            changed.append(field)

    jt = getattr(args, "job_type", None)
    if jt is not None:
        if jt not in VALID_JOB_TYPES:
            err(f"Invalid job-type: {jt}")
        data["job_type"] = jt
        changed.append("job_type")

    ct = getattr(args, "contract_type", None)
    if ct is not None:
        if ct not in VALID_CONTRACT_TYPES:
            err(f"Invalid contract-type: {ct}")
        data["contract_type"] = ct
        changed.append("contract_type")

    js = getattr(args, "job_status", None)
    if js is not None:
        if js not in VALID_JOB_STATUSES:
            err(f"Invalid job-status: {js}")
        data["job_status"] = js
        changed.append("job_status")

    if not changed:
        err("No fields to update")

    data["updated_at"] = LiteralValue("datetime('now')")
    sql, params = dynamic_update("constructclaw_job", data, {"id": job_id})
    conn.execute(sql, params)
    audit(conn, SKILL, "construction-update-job", "constructclaw_job", job_id,
          new_values={"updated_fields": changed})
    conn.commit()
    ok({"job_id": job_id, "updated_fields": changed})


# ---------------------------------------------------------------------------
# get-job
# ---------------------------------------------------------------------------
def get_job(conn, args):
    job_id = getattr(args, "job_id", None)
    if not job_id:
        err("--job-id is required")
    row = conn.execute(Q.from_(_t_job).select(_t_job.star).where(_t_job.id == P()).get_sql(), (job_id,)).fetchone()
    if not row:
        err(f"Job {job_id} not found")
    ok(row_to_dict(row))


# ---------------------------------------------------------------------------
# list-jobs
# ---------------------------------------------------------------------------
def list_jobs(conn, args):
    t = _t_job
    q_count = Q.from_(t).select(fn.Count("*").as_("cnt"))
    q_rows = Q.from_(t).select(t.star)
    params = []

    cid = getattr(args, "company_id", None)
    if cid:
        q_count = q_count.where(t.company_id == P())
        q_rows = q_rows.where(t.company_id == P())
        params.append(cid)
    js = getattr(args, "job_status", None)
    if js:
        q_count = q_count.where(t.job_status == P())
        q_rows = q_rows.where(t.job_status == P())
        params.append(js)
    jt = getattr(args, "job_type", None)
    if jt:
        q_count = q_count.where(t.job_type == P())
        q_rows = q_rows.where(t.job_type == P())
        params.append(jt)
    search = getattr(args, "search", None)
    if search:
        s = f"%{search}%"
        like_crit = (t.name.like(P()) | t.description.like(P()) | t.client_name.like(P()) | t.job_number.like(P()))
        q_count = q_count.where(like_crit)
        q_rows = q_rows.where(like_crit)
        params.extend([s] * 4)

    limit = getattr(args, "limit", 50) or 50
    offset = getattr(args, "offset", 0) or 0

    total = conn.execute(q_count.get_sql(), params).fetchone()["cnt"]
    q_rows = q_rows.orderby(t.created_at, order=Order.desc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [limit, offset]).fetchall()

    ok({"jobs": [row_to_dict(r) for r in rows], "total_count": total, "limit": limit, "offset": offset})


# ---------------------------------------------------------------------------
# add-cost-code
# ---------------------------------------------------------------------------
def add_cost_code(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")
    job_id = getattr(args, "job_id", None)
    if not job_id:
        err("--job-id is required")
    code = getattr(args, "code", None)
    if not code:
        err("--code is required")

    if not conn.execute(Q.from_(Table("constructclaw_job")).select(Field("id")).where(Field("id") == P()).get_sql(), (job_id,)).fetchone():
        err(f"Job {job_id} not found")

    # Check duplicate code within job
    q = Q.from_(_t_cc).select(_t_cc.id).where(_t_cc.job_id == P()).where(_t_cc.code == P())
    if conn.execute(q.get_sql(), (job_id, code)).fetchone():
        err(f"Cost code {code} already exists for this job")

    category = getattr(args, "category", None) or "labor"
    if category not in VALID_COST_CATEGORIES:
        err(f"Invalid category: {category}")

    cc_id = str(uuid.uuid4())
    sql, _ = insert_row("constructclaw_cost_code", {"id": P(), "job_id": P(), "code": P(), "description": P(), "category": P(), "budget_amount": P(), "budget_hours": P(), "company_id": P()})

    conn.execute(sql,
        (
            cc_id, job_id, code,
            getattr(args, "description", None),
            category,
            getattr(args, "budget_amount", None) or "0",
            getattr(args, "budget_hours", None) or "0",
            args.company_id,
        ),
    )
    audit(conn, SKILL, "construction-add-cost-code", "constructclaw_cost_code", cc_id,
          new_values={"code": code, "job_id": job_id})
    conn.commit()
    ok({"cost_code_id": cc_id, "code": code, "job_id": job_id, "category": category})


# ---------------------------------------------------------------------------
# batch-add-cost-codes
# ---------------------------------------------------------------------------
def batch_add_cost_codes(conn, args):
    """Create multiple cost codes for a job in a single transaction.

    Required: --company-id, --job-id, --codes-json (JSON array of objects)
    Each object: {"code": "01-100", "description": "...", "category": "labor", "budget_amount": "5000", "budget_hours": "100"}
    """
    import json as _json

    if not getattr(args, "company_id", None):
        err("--company-id is required")
    job_id = getattr(args, "job_id", None)
    if not job_id:
        err("--job-id is required")
    codes_json = getattr(args, "codes_json", None)
    if not codes_json:
        err("--codes-json is required (JSON array of cost code objects)")

    if not conn.execute(Q.from_(Table("constructclaw_job")).select(Field("id")).where(Field("id") == P()).get_sql(), (job_id,)).fetchone():
        err(f"Job {job_id} not found")

    try:
        codes_list = _json.loads(codes_json) if isinstance(codes_json, str) else codes_json
    except (TypeError, _json.JSONDecodeError) as e:
        err(f"Invalid JSON for --codes-json: {e}")

    if not isinstance(codes_list, list) or len(codes_list) == 0:
        err("--codes-json must be a non-empty JSON array")

    created = []
    for idx, item in enumerate(codes_list):
        code = item.get("code")
        if not code:
            err(f"Cost code at index {idx} missing 'code' field")

        q = Q.from_(_t_cc).select(_t_cc.id).where(_t_cc.job_id == P()).where(_t_cc.code == P())
        if conn.execute(q.get_sql(), (job_id, code)).fetchone():
            err(f"Cost code {code} already exists for this job")

        category = item.get("category", "labor")
        if category not in VALID_COST_CATEGORIES:
            err(f"Invalid category '{category}' for cost code {code}")

        cc_id = str(uuid.uuid4())
        sql, _ = insert_row("constructclaw_cost_code", {"id": P(), "job_id": P(), "code": P(), "description": P(), "category": P(), "budget_amount": P(), "budget_hours": P(), "company_id": P()})

        conn.execute(sql,
            (
                cc_id, job_id, code,
                item.get("description"),
                category,
                item.get("budget_amount", "0"),
                item.get("budget_hours", "0"),
                args.company_id,
            ),
        )
        created.append({"cost_code_id": cc_id, "code": code, "category": category})

    audit(conn, SKILL, "construction-batch-add-cost-codes", "constructclaw_cost_code", job_id,
          new_values={"count": len(created)})
    conn.commit()
    ok({"job_id": job_id, "created_count": len(created), "cost_codes": created})


# ---------------------------------------------------------------------------
# list-cost-codes
# ---------------------------------------------------------------------------
def list_cost_codes(conn, args):
    t = _t_cc
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
    category = getattr(args, "category", None)
    if category:
        q = q.where(t.category == P())
        params.append(category)

    q = q.orderby(t.code, order=Order.asc)
    rows = conn.execute(q.get_sql(), params).fetchall()
    ok({"cost_codes": [row_to_dict(r) for r in rows], "total_count": len(rows)})


# ---------------------------------------------------------------------------
# add-cost-entry
# ---------------------------------------------------------------------------
def add_cost_entry(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")
    job_id = getattr(args, "job_id", None)
    if not job_id:
        err("--job-id is required")

    if not conn.execute(Q.from_(Table("constructclaw_job")).select(Field("id")).where(Field("id") == P()).get_sql(), (job_id,)).fetchone():
        err(f"Job {job_id} not found")

    cost_code_id = getattr(args, "cost_code_id", None)
    if cost_code_id:
        if not conn.execute(Q.from_(Table("constructclaw_cost_code")).select(Field("id")).where(Field("id") == P()).get_sql(), (cost_code_id,)).fetchone():
            err(f"Cost code {cost_code_id} not found")

    category = getattr(args, "category", None) or "labor"
    if category not in VALID_COST_CATEGORIES:
        err(f"Invalid category: {category}")

    amount = getattr(args, "amount", None) or "0"
    quantity = getattr(args, "quantity", None) or "0"
    unit_cost = getattr(args, "unit_cost", None) or "0"

    # Auto-calculate amount if quantity and unit_cost given
    if amount == "0" and quantity != "0" and unit_cost != "0":
        amount = str((_d(quantity) * _d(unit_cost)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    ce_id = str(uuid.uuid4())
    from datetime import date as _date
    entry_date = getattr(args, "entry_date", None) or _date.today().isoformat()

    sql, _ = insert_row("constructclaw_cost_entry", {"id": P(), "job_id": P(), "cost_code_id": P(), "entry_date": P(), "category": P(), "description": P(), "vendor": P(), "reference": P(), "quantity": P(), "unit_cost": P(), "amount": P(), "hours": P(), "company_id": P()})


    conn.execute(sql,
        (
            ce_id, job_id, cost_code_id,
            entry_date,
            category,
            getattr(args, "description", None),
            getattr(args, "vendor", None),
            getattr(args, "reference", None),
            quantity, unit_cost, amount,
            getattr(args, "hours", None) or "0",
            args.company_id,
        ),
    )
    audit(conn, SKILL, "construction-add-cost-entry", "constructclaw_cost_entry", ce_id,
          new_values={"job_id": job_id, "amount": amount})
    conn.commit()
    ok({"cost_entry_id": ce_id, "job_id": job_id, "amount": amount, "category": category})


# ---------------------------------------------------------------------------
# list-cost-entries
# ---------------------------------------------------------------------------
def list_cost_entries(conn, args):
    t = _t_ce
    q_count = Q.from_(t).select(fn.Count("*").as_("cnt"))
    q_rows = Q.from_(t).select(t.star)
    params = []

    job_id = getattr(args, "job_id", None)
    if job_id:
        q_count = q_count.where(t.job_id == P())
        q_rows = q_rows.where(t.job_id == P())
        params.append(job_id)
    cid = getattr(args, "company_id", None)
    if cid:
        q_count = q_count.where(t.company_id == P())
        q_rows = q_rows.where(t.company_id == P())
        params.append(cid)
    cost_code_id = getattr(args, "cost_code_id", None)
    if cost_code_id:
        q_count = q_count.where(t.cost_code_id == P())
        q_rows = q_rows.where(t.cost_code_id == P())
        params.append(cost_code_id)
    category = getattr(args, "category", None)
    if category:
        q_count = q_count.where(t.category == P())
        q_rows = q_rows.where(t.category == P())
        params.append(category)

    limit = getattr(args, "limit", 50) or 50
    offset = getattr(args, "offset", 0) or 0

    total = conn.execute(q_count.get_sql(), params).fetchone()["cnt"]
    q_rows = q_rows.orderby(t.entry_date, order=Order.desc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [limit, offset]).fetchall()
    ok({"cost_entries": [row_to_dict(r) for r in rows], "total_count": total, "limit": limit, "offset": offset})


# ---------------------------------------------------------------------------
# add-commitment
# ---------------------------------------------------------------------------
def add_commitment(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")
    job_id = getattr(args, "job_id", None)
    if not job_id:
        err("--job-id is required")

    if not conn.execute(Q.from_(Table("constructclaw_job")).select(Field("id")).where(Field("id") == P()).get_sql(), (job_id,)).fetchone():
        err(f"Job {job_id} not found")

    commitment_type = getattr(args, "commitment_type", None) or "purchase_order"
    cm_id = str(uuid.uuid4())

    original_amount = getattr(args, "original_amount", None) or "0"

    sql, _ = insert_row("constructclaw_commitment", {"id": P(), "job_id": P(), "cost_code_id": P(), "commitment_type": P(), "vendor": P(), "description": P(), "original_amount": P(), "revised_amount": P(), "company_id": P()})


    conn.execute(sql,
        (
            cm_id, job_id,
            getattr(args, "cost_code_id", None),
            commitment_type,
            getattr(args, "vendor", None),
            getattr(args, "description", None),
            original_amount,
            original_amount,  # revised starts same as original
            args.company_id,
        ),
    )
    audit(conn, SKILL, "construction-add-commitment", "constructclaw_commitment", cm_id,
          new_values={"job_id": job_id, "original_amount": original_amount})
    conn.commit()
    ok({"commitment_id": cm_id, "job_id": job_id, "original_amount": original_amount,
        "commitment_status": "draft"})


# ---------------------------------------------------------------------------
# update-commitment
# ---------------------------------------------------------------------------
def update_commitment(conn, args):
    cm_id = getattr(args, "commitment_id", None)
    if not cm_id:
        err("--commitment-id is required")
    row = conn.execute(Q.from_(_t_cm).select(_t_cm.star).where(_t_cm.id == P()).get_sql(), (cm_id,)).fetchone()
    if not row:
        err(f"Commitment {cm_id} not found")

    data, changed = {}, []

    for field, attr in [
        ("vendor", "vendor"), ("description", "description"),
        ("original_amount", "original_amount"), ("revised_amount", "revised_amount"),
        ("invoiced_amount", "invoiced_amount"), ("paid_amount", "paid_amount"),
    ]:
        val = getattr(args, attr, None)
        if val is not None:
            data[field] = val
            changed.append(field)

    cs = getattr(args, "commitment_status", None)
    if cs is not None:
        if cs not in VALID_COMMITMENT_STATUSES:
            err(f"Invalid commitment-status: {cs}")
        data["commitment_status"] = cs
        changed.append("commitment_status")

    if not changed:
        err("No fields to update")

    data["updated_at"] = LiteralValue("datetime('now')")
    sql, params = dynamic_update("constructclaw_commitment", data, {"id": cm_id})
    conn.execute(sql, params)
    audit(conn, SKILL, "construction-update-commitment", "constructclaw_commitment", cm_id,
          new_values={"updated_fields": changed})
    conn.commit()
    ok({"commitment_id": cm_id, "updated_fields": changed})


# ---------------------------------------------------------------------------
# list-commitments
# ---------------------------------------------------------------------------
def list_commitments(conn, args):
    t = _t_cm
    q_count = Q.from_(t).select(fn.Count("*").as_("cnt"))
    q_rows = Q.from_(t).select(t.star)
    params = []

    job_id = getattr(args, "job_id", None)
    if job_id:
        q_count = q_count.where(t.job_id == P())
        q_rows = q_rows.where(t.job_id == P())
        params.append(job_id)
    cid = getattr(args, "company_id", None)
    if cid:
        q_count = q_count.where(t.company_id == P())
        q_rows = q_rows.where(t.company_id == P())
        params.append(cid)
    cs = getattr(args, "commitment_status", None)
    if cs:
        q_count = q_count.where(t.commitment_status == P())
        q_rows = q_rows.where(t.commitment_status == P())
        params.append(cs)

    limit = getattr(args, "limit", 50) or 50
    offset = getattr(args, "offset", 0) or 0

    total = conn.execute(q_count.get_sql(), params).fetchone()["cnt"]
    q_rows = q_rows.orderby(t.created_at, order=Order.desc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [limit, offset]).fetchall()
    ok({"commitments": [row_to_dict(r) for r in rows], "total_count": total, "limit": limit, "offset": offset})


# ---------------------------------------------------------------------------
# job-cost-summary -- budget vs actual vs committed by cost code
# ---------------------------------------------------------------------------
def job_cost_summary(conn, args):
    job_id = getattr(args, "job_id", None)
    if not job_id:
        err("--job-id is required")

    job = conn.execute(Q.from_(_t_job).select(_t_job.star).where(_t_job.id == P()).get_sql(), (job_id,)).fetchone()
    if not job:
        err(f"Job {job_id} not found")

    q = Q.from_(_t_cc).select(_t_cc.star).where(_t_cc.job_id == P()).orderby(_t_cc.code)
    codes = conn.execute(q.get_sql(), (job_id,)).fetchall()

    summary = []
    total_budget = Decimal("0")
    total_actual = Decimal("0")
    total_committed = Decimal("0")

    for cc in codes:
        budget = _d(cc["budget_amount"])
        total_budget += budget

        # PyPika: skipped — CAST(amount AS REAL) inside COALESCE/SUM
        actual_row = conn.execute(
            "SELECT COALESCE(SUM(CAST(amount AS REAL)), 0) as total FROM constructclaw_cost_entry WHERE cost_code_id = ?",
            (cc["id"],),
        ).fetchone()
        actual = _d(actual_row["total"])
        total_actual += actual

        # PyPika: skipped — CAST + NOT IN inside aggregate
        committed_row = conn.execute(
            "SELECT COALESCE(SUM(CAST(revised_amount AS REAL)), 0) as total FROM constructclaw_commitment WHERE cost_code_id = ? AND commitment_status NOT IN ('cancelled','closed')",
            (cc["id"],),
        ).fetchone()
        committed = _d(committed_row["total"])
        total_committed += committed

        variance = budget - actual - committed
        summary.append({
            "cost_code": cc["code"],
            "description": cc["description"],
            "category": cc["category"],
            "budget": str(budget.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "actual": str(actual.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "committed": str(committed.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "variance": str(variance.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        })

    ok({
        "job_id": job_id,
        "job_name": job["name"],
        "cost_codes": summary,
        "total_budget": str(total_budget.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "total_actual": str(total_actual.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "total_committed": str(total_committed.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "total_variance": str((total_budget - total_actual - total_committed).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
    })


# ---------------------------------------------------------------------------
# job-profitability -- revenue vs cost
# ---------------------------------------------------------------------------
def job_profitability(conn, args):
    job_id = getattr(args, "job_id", None)
    if not job_id:
        err("--job-id is required")

    job = conn.execute(Q.from_(_t_job).select(_t_job.star).where(_t_job.id == P()).get_sql(), (job_id,)).fetchone()
    if not job:
        err(f"Job {job_id} not found")

    contract = _d(job["contract_amount"])

    # PyPika: skipped — CAST inside COALESCE/SUM aggregate
    # Total billed
    billed_row = conn.execute(
        "SELECT COALESCE(SUM(CAST(current_due AS REAL)), 0) as total FROM constructclaw_progress_bill WHERE job_id = ? AND bill_status != 'rejected'",
        (job_id,),
    ).fetchone()
    total_billed = _d(billed_row["total"])

    # Total cost
    cost_row = conn.execute(
        "SELECT COALESCE(SUM(CAST(amount AS REAL)), 0) as total FROM constructclaw_cost_entry WHERE job_id = ?",
        (job_id,),
    ).fetchone()
    total_cost = _d(cost_row["total"])

    # Change orders
    co_row = conn.execute(
        "SELECT COALESCE(SUM(CAST(cost_change AS REAL)), 0) as total FROM constructclaw_cco WHERE job_id = ? AND cco_status IN ('approved','executed')",
        (job_id,),
    ).fetchone()
    total_cos = _d(co_row["total"])

    revised_contract = contract + total_cos
    gross_profit = revised_contract - total_cost
    margin = Decimal("0")
    if revised_contract > 0:
        margin = (gross_profit / revised_contract * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    ok({
        "job_id": job_id,
        "job_name": job["name"],
        "original_contract": str(contract.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "change_orders": str(total_cos.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "revised_contract": str(revised_contract.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "total_cost": str(total_cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "gross_profit": str(gross_profit.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "margin_pct": str(margin),
        "total_billed": str(total_billed.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
    })


# ---------------------------------------------------------------------------
# wip-report -- work in progress
# ---------------------------------------------------------------------------
def wip_report(conn, args):
    job_id = getattr(args, "job_id", None)
    if not job_id:
        err("--job-id is required")

    job = conn.execute(Q.from_(_t_job).select(_t_job.star).where(_t_job.id == P()).get_sql(), (job_id,)).fetchone()
    if not job:
        err(f"Job {job_id} not found")

    contract = _d(job["contract_amount"])
    pct_complete = _d(job["percent_complete"])

    # PyPika: skipped — CAST inside COALESCE/SUM aggregate
    # Total cost
    cost_row = conn.execute(
        "SELECT COALESCE(SUM(CAST(amount AS REAL)), 0) as total FROM constructclaw_cost_entry WHERE job_id = ?",
        (job_id,),
    ).fetchone()
    total_cost = _d(cost_row["total"])

    # Total billed
    billed_row = conn.execute(
        "SELECT COALESCE(SUM(CAST(current_due AS REAL)), 0) as total FROM constructclaw_progress_bill WHERE job_id = ? AND bill_status != 'rejected'",
        (job_id,),
    ).fetchone()
    total_billed = _d(billed_row["total"])

    # Earned revenue = contract * pct_complete / 100
    earned_revenue = (contract * pct_complete / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # Over/under billing
    over_under = total_billed - earned_revenue

    ok({
        "job_id": job_id,
        "job_name": job["name"],
        "contract_amount": str(contract.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "percent_complete": str(pct_complete),
        "earned_revenue": str(earned_revenue),
        "total_cost": str(total_cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "total_billed": str(total_billed.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "over_under_billing": str(over_under.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "billing_status": "overbilled" if over_under > 0 else ("underbilled" if over_under < 0 else "balanced"),
    })


# ---------------------------------------------------------------------------
# job-status-report
# ---------------------------------------------------------------------------
def job_status_report(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")

    q = Q.from_(_t_job).select(_t_job.star).where(_t_job.company_id == P()).orderby(_t_job.created_at, order=Order.desc)
    jobs = conn.execute(q.get_sql(), (args.company_id,)).fetchall()

    report = []
    for j in jobs:
        # PyPika: skipped — CAST inside COALESCE/SUM aggregate
        cost_row = conn.execute(
            "SELECT COALESCE(SUM(CAST(amount AS REAL)), 0) as total FROM constructclaw_cost_entry WHERE job_id = ?",
            (j["id"],),
        ).fetchone()
        report.append({
            "job_id": j["id"],
            "job_number": j["job_number"],
            "name": j["name"],
            "job_status": j["job_status"],
            "contract_amount": j["contract_amount"],
            "total_cost": str(_d(cost_row["total"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "percent_complete": j["percent_complete"],
        })

    ok({"company_id": args.company_id, "jobs": report, "total_count": len(report)})


# ---------------------------------------------------------------------------
# ACTIONS registry
# ---------------------------------------------------------------------------
ACTIONS = {
    "construction-add-job": add_job,
    "construction-update-job": update_job,
    "construction-get-job": get_job,
    "construction-list-jobs": list_jobs,
    "construction-add-cost-code": add_cost_code,
    "construction-batch-add-cost-codes": batch_add_cost_codes,
    "construction-list-cost-codes": list_cost_codes,
    "construction-add-cost-entry": add_cost_entry,
    "construction-list-cost-entries": list_cost_entries,
    "construction-add-commitment": add_commitment,
    "construction-update-commitment": update_commitment,
    "construction-list-commitments": list_commitments,
    "construction-job-cost-summary": job_cost_summary,
    "construction-job-profitability": job_profitability,
    "construction-wip-report": wip_report,
    "construction-job-status-report": job_status_report,
}
