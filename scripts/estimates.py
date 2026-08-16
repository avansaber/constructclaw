"""ConstructClaw -- Estimates domain module.

Estimating, bids, and bid comparison.
12 actions exported via ACTIONS dict.
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
from erpclaw_lib.query import Q, P, Table, Field, fn, Order, insert_row, LiteralValue, dynamic_update, now

SKILL = "constructclaw"

_t_est = Table("constructclaw_estimate")
_t_line = Table("constructclaw_estimate_line")
_t_bid = Table("constructclaw_bid")

register_prefix("constructclaw_estimate", "CCEST-")
register_prefix("constructclaw_bid", "CCBID-")

VALID_ESTIMATE_STATUSES = ("draft", "submitted", "won", "lost", "revised", "cancelled")
VALID_BID_STATUSES = ("submitted", "under_review", "awarded", "rejected", "withdrawn")
VALID_LINE_CATEGORIES = ("labor", "material", "equipment", "subcontract", "overhead", "other")


def _d(val, default="0"):
    if val is None:
        return Decimal(default)
    return Decimal(str(val))


# ---------------------------------------------------------------------------
# add-estimate
# ---------------------------------------------------------------------------
def add_estimate(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")
    if not getattr(args, "name", None):
        err("--name is required")

    if not conn.execute(Q.from_(Table("company")).select(Field("id")).where(Field("id") == P()).get_sql(), (args.company_id,)).fetchone():
        err(f"Company {args.company_id} not found")

    est_id = str(uuid.uuid4())
    ns = get_next_name(conn, "constructclaw_estimate", company_id=args.company_id)

    sql, _ = insert_row("constructclaw_estimate", {"id": P(), "naming_series": P(), "estimate_number": P(), "job_id": P(), "name": P(), "client_name": P(), "description": P(), "due_date": P(), "markup_pct": P(), "overhead_pct": P(), "profit_pct": P(), "notes": P(), "company_id": P()})


    conn.execute(sql,
        (
            est_id, ns, ns,
            getattr(args, "job_id", None),
            args.name,
            getattr(args, "client_name", None),
            getattr(args, "description", None),
            getattr(args, "due_date", None),
            getattr(args, "markup_pct", None) or "0",
            getattr(args, "overhead_pct", None) or "0",
            getattr(args, "profit_pct", None) or "0",
            getattr(args, "notes", None),
            args.company_id,
        ),
    )
    audit(conn, SKILL, "construction-add-estimate", "constructclaw_estimate", est_id,
          new_values={"naming_series": ns, "name": args.name})
    conn.commit()
    ok({"estimate_id": est_id, "naming_series": ns, "name": args.name,
        "estimate_status": "draft"})


# ---------------------------------------------------------------------------
# update-estimate
# ---------------------------------------------------------------------------
def update_estimate(conn, args):
    est_id = getattr(args, "estimate_id", None)
    if not est_id:
        err("--estimate-id is required")
    row = conn.execute(Q.from_(_t_est).select(_t_est.star).where(_t_est.id == P()).get_sql(), (est_id,)).fetchone()
    if not row:
        err(f"Estimate {est_id} not found")

    data, changed = {}, []
    for field, attr in [
        ("name", "name"), ("client_name", "client_name"),
        ("description", "description"), ("due_date", "due_date"),
        ("markup_pct", "markup_pct"), ("overhead_pct", "overhead_pct"),
        ("profit_pct", "profit_pct"), ("notes", "notes"),
        ("total_amount", "total_amount"),
    ]:
        val = getattr(args, attr, None)
        if val is not None:
            data[field] = val
            changed.append(field)

    es = getattr(args, "estimate_status", None)
    if es is not None:
        if es not in VALID_ESTIMATE_STATUSES:
            err(f"Invalid estimate-status: {es}")
        data["estimate_status"] = es
        changed.append("estimate_status")

    if not changed:
        err("No fields to update")

    data["updated_at"] = now()
    sql, params = dynamic_update("constructclaw_estimate", data, {"id": est_id})
    conn.execute(sql, params)
    audit(conn, SKILL, "construction-update-estimate", "constructclaw_estimate", est_id,
          new_values={"updated_fields": changed})
    conn.commit()
    ok({"estimate_id": est_id, "updated_fields": changed})


# ---------------------------------------------------------------------------
# get-estimate
# ---------------------------------------------------------------------------
def get_estimate(conn, args):
    est_id = getattr(args, "estimate_id", None)
    if not est_id:
        err("--estimate-id is required")
    row = conn.execute(Q.from_(_t_est).select(_t_est.star).where(_t_est.id == P()).get_sql(), (est_id,)).fetchone()
    if not row:
        err(f"Estimate {est_id} not found")

    data = row_to_dict(row)
    # Attach lines
    q = Q.from_(_t_line).select(_t_line.star).where(_t_line.estimate_id == P()).orderby(_t_line.line_number)
    lines = conn.execute(q.get_sql(), (est_id,)).fetchall()
    data["lines"] = [row_to_dict(l) for l in lines]
    ok(data)


# ---------------------------------------------------------------------------
# list-estimates
# ---------------------------------------------------------------------------
def list_estimates(conn, args):
    t = _t_est
    q_count = Q.from_(t).select(fn.Count("*").as_("cnt"))
    q_rows = Q.from_(t).select(t.star)
    params = []

    cid = getattr(args, "company_id", None)
    if cid:
        q_count = q_count.where(t.company_id == P())
        q_rows = q_rows.where(t.company_id == P())
        params.append(cid)
    es = getattr(args, "estimate_status", None)
    if es:
        q_count = q_count.where(t.estimate_status == P())
        q_rows = q_rows.where(t.estimate_status == P())
        params.append(es)
    search = getattr(args, "search", None)
    if search:
        s = f"%{search}%"
        like_crit = (t.name.like(P()) | t.client_name.like(P()) | t.description.like(P()))
        q_count = q_count.where(like_crit)
        q_rows = q_rows.where(like_crit)
        params.extend([s] * 3)

    limit = getattr(args, "limit", 50) or 50
    offset = getattr(args, "offset", 0) or 0

    total = conn.execute(q_count.get_sql(), params).fetchone()["cnt"]
    q_rows = q_rows.orderby(t.created_at, order=Order.desc).limit(P()).offset(P())
    rows = conn.execute(q_rows.get_sql(), params + [limit, offset]).fetchall()
    ok({"estimates": [row_to_dict(r) for r in rows], "total_count": total, "limit": limit, "offset": offset})


# ---------------------------------------------------------------------------
# add-estimate-line
# ---------------------------------------------------------------------------
def add_estimate_line(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")
    est_id = getattr(args, "estimate_id", None)
    if not est_id:
        err("--estimate-id is required")
    if not getattr(args, "description", None):
        err("--description is required")

    if not conn.execute(Q.from_(Table("constructclaw_estimate")).select(Field("id")).where(Field("id") == P()).get_sql(), (est_id,)).fetchone():
        err(f"Estimate {est_id} not found")

    category = getattr(args, "category", None) or "labor"
    if category not in VALID_LINE_CATEGORIES:
        err(f"Invalid category: {category}")

    quantity = getattr(args, "quantity", None) or "0"
    unit_cost = getattr(args, "unit_cost", None) or "0"
    amount = getattr(args, "amount", None) or "0"

    if amount == "0" and quantity != "0" and unit_cost != "0":
        amount = str((_d(quantity) * _d(unit_cost)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    line_id = str(uuid.uuid4())
    # Get next line number
    q = Q.from_(_t_line).select(fn.Coalesce(fn.Max(_t_line.line_number), 0).as_("mx")).where(_t_line.estimate_id == P())
    max_row = conn.execute(q.get_sql(), (est_id,)).fetchone()
    line_number = (max_row["mx"] or 0) + 1

    sql, _ = insert_row("constructclaw_estimate_line", {"id": P(), "estimate_id": P(), "line_number": P(), "description": P(), "category": P(), "quantity": P(), "unit": P(), "unit_cost": P(), "amount": P(), "notes": P(), "company_id": P()})


    conn.execute(sql,
        (
            line_id, est_id, line_number,
            args.description, category, quantity,
            getattr(args, "unit", None) or "ea",
            unit_cost, amount,
            getattr(args, "notes", None),
            args.company_id,
        ),
    )

    # Recalculate estimate total
    # PyPika: skipped — CAST inside COALESCE/SUM aggregate
    total_row = conn.execute(
        "SELECT COALESCE(SUM(CAST(amount AS NUMERIC)), 0) as total FROM constructclaw_estimate_line WHERE estimate_id = ?",
        (est_id,),
    ).fetchone()
    new_total = str(_d(total_row["total"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    sql_upd, params_upd = dynamic_update("constructclaw_estimate",
        {"total_amount": new_total, "updated_at": now()},
        {"id": est_id})
    conn.execute(sql_upd, params_upd)

    conn.commit()
    ok({"line_id": line_id, "estimate_id": est_id, "line_number": line_number,
        "amount": amount, "estimate_total": new_total})


# ---------------------------------------------------------------------------
# update-estimate-line
# ---------------------------------------------------------------------------
def update_estimate_line(conn, args):
    line_id = getattr(args, "line_id", None)
    if not line_id:
        err("--line-id is required")
    row = conn.execute(Q.from_(_t_line).select(_t_line.star).where(_t_line.id == P()).get_sql(), (line_id,)).fetchone()
    if not row:
        err(f"Estimate line {line_id} not found")

    data, changed = {}, []
    for field, attr in [
        ("description", "description"), ("quantity", "quantity"),
        ("unit", "unit"), ("unit_cost", "unit_cost"),
        ("amount", "amount"), ("notes", "notes"),
    ]:
        val = getattr(args, attr, None)
        if val is not None:
            data[field] = val
            changed.append(field)

    cat = getattr(args, "category", None)
    if cat is not None:
        if cat not in VALID_LINE_CATEGORIES:
            err(f"Invalid category: {cat}")
        data["category"] = cat
        changed.append("category")

    if not changed:
        err("No fields to update")

    sql, params = dynamic_update("constructclaw_estimate_line", data, {"id": line_id})
    conn.execute(sql, params)

    # Recalculate estimate total
    est_id = row["estimate_id"]
    # PyPika: skipped — CAST inside COALESCE/SUM aggregate
    total_row = conn.execute(
        "SELECT COALESCE(SUM(CAST(amount AS NUMERIC)), 0) as total FROM constructclaw_estimate_line WHERE estimate_id = ?",
        (est_id,),
    ).fetchone()
    new_total = str(_d(total_row["total"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    sql_upd, params_upd = dynamic_update("constructclaw_estimate",
        {"total_amount": new_total, "updated_at": now()},
        {"id": est_id})
    conn.execute(sql_upd, params_upd)

    conn.commit()
    ok({"line_id": line_id, "updated_fields": changed, "estimate_total": new_total})


# ---------------------------------------------------------------------------
# list-estimate-lines
# ---------------------------------------------------------------------------
def list_estimate_lines(conn, args):
    est_id = getattr(args, "estimate_id", None)
    if not est_id:
        err("--estimate-id is required")

    q = Q.from_(_t_line).select(_t_line.star).where(_t_line.estimate_id == P()).orderby(_t_line.line_number)
    rows = conn.execute(q.get_sql(), (est_id,)).fetchall()
    ok({"lines": [row_to_dict(r) for r in rows], "total_count": len(rows)})


# ---------------------------------------------------------------------------
# submit-estimate
# ---------------------------------------------------------------------------
def submit_estimate(conn, args):
    est_id = getattr(args, "estimate_id", None)
    if not est_id:
        err("--estimate-id is required")
    row = conn.execute(Q.from_(_t_est).select(_t_est.star).where(_t_est.id == P()).get_sql(), (est_id,)).fetchone()
    if not row:
        err(f"Estimate {est_id} not found")
    if row["estimate_status"] != "draft":
        err(f"Estimate must be in draft status to submit (current: {row['estimate_status']})")

    sql, params = dynamic_update("constructclaw_estimate",
        {"estimate_status": "submitted", "updated_at": now()},
        {"id": est_id})
    conn.execute(sql, params)
    audit(conn, SKILL, "construction-submit-estimate", "constructclaw_estimate", est_id,
          new_values={"estimate_status": "submitted"})
    conn.commit()
    ok({"estimate_id": est_id, "estimate_status": "submitted"})


# ---------------------------------------------------------------------------
# add-bid
# ---------------------------------------------------------------------------
def add_bid(conn, args):
    if not getattr(args, "company_id", None):
        err("--company-id is required")
    if not getattr(args, "bidder_name", None):
        err("--bidder-name is required")

    bid_id = str(uuid.uuid4())
    ns = get_next_name(conn, "constructclaw_bid", company_id=args.company_id)

    sql, _ = insert_row("constructclaw_bid", {"id": P(), "naming_series": P(), "bid_number": P(), "estimate_id": P(), "job_id": P(), "bidder_name": P(), "bid_amount": P(), "scope_description": P(), "exclusions": P(), "notes": P(), "company_id": P()})


    conn.execute(sql,
        (
            bid_id, ns, ns,
            getattr(args, "estimate_id", None),
            getattr(args, "job_id", None),
            args.bidder_name,
            getattr(args, "bid_amount", None) or "0",
            getattr(args, "scope_description", None),
            getattr(args, "exclusions", None),
            getattr(args, "notes", None),
            args.company_id,
        ),
    )
    audit(conn, SKILL, "construction-add-bid", "constructclaw_bid", bid_id,
          new_values={"naming_series": ns, "bidder_name": args.bidder_name})
    conn.commit()
    ok({"bid_id": bid_id, "naming_series": ns, "bidder_name": args.bidder_name,
        "bid_status": "submitted"})


# ---------------------------------------------------------------------------
# list-bids
# ---------------------------------------------------------------------------
def list_bids(conn, args):
    t = _t_bid
    q = Q.from_(t).select(t.star)
    params = []

    cid = getattr(args, "company_id", None)
    if cid:
        q = q.where(t.company_id == P())
        params.append(cid)
    est_id = getattr(args, "estimate_id", None)
    if est_id:
        q = q.where(t.estimate_id == P())
        params.append(est_id)
    job_id = getattr(args, "job_id", None)
    if job_id:
        q = q.where(t.job_id == P())
        params.append(job_id)
    bs = getattr(args, "bid_status", None)
    if bs:
        q = q.where(t.bid_status == P())
        params.append(bs)

    q = q.orderby(t.bid_date, order=Order.desc)
    rows = conn.execute(q.get_sql(), params).fetchall()
    ok({"bids": [row_to_dict(r) for r in rows], "total_count": len(rows)})


# ---------------------------------------------------------------------------
# award-bid
# ---------------------------------------------------------------------------
def award_bid(conn, args):
    bid_id = getattr(args, "bid_id", None)
    if not bid_id:
        err("--bid-id is required")
    row = conn.execute(Q.from_(_t_bid).select(_t_bid.star).where(_t_bid.id == P()).get_sql(), (bid_id,)).fetchone()
    if not row:
        err(f"Bid {bid_id} not found")
    if row["bid_status"] not in ("submitted", "under_review"):
        err(f"Bid must be submitted or under_review to award (current: {row['bid_status']})")

    sql, params = dynamic_update("constructclaw_bid",
        {"bid_status": "awarded", "updated_at": now()},
        {"id": bid_id})
    conn.execute(sql, params)
    audit(conn, SKILL, "construction-award-bid", "constructclaw_bid", bid_id,
          new_values={"bid_status": "awarded"})
    conn.commit()
    ok({"bid_id": bid_id, "bid_status": "awarded", "bidder_name": row["bidder_name"]})


# ---------------------------------------------------------------------------
# compare-bids
# ---------------------------------------------------------------------------
def compare_bids(conn, args):
    est_id = getattr(args, "estimate_id", None)
    job_id = getattr(args, "job_id", None)
    if not est_id and not job_id:
        err("--estimate-id or --job-id is required")

    t = _t_bid
    q = Q.from_(t).select(t.star)
    params = []

    if est_id:
        q = q.where(t.estimate_id == P())
        params.append(est_id)
    if job_id:
        q = q.where(t.job_id == P())
        params.append(job_id)

    # PyPika: skipped — ORDER BY CAST(bid_amount AS NUMERIC) not cleanly expressible
    q = q.orderby(LiteralValue("CAST(bid_amount AS NUMERIC)"), order=Order.asc)
    bids = conn.execute(q.get_sql(), params).fetchall()

    if not bids:
        ok({"bids": [], "total_count": 0, "message": "No bids found"})
        return

    comparison = []
    lowest = _d(bids[0]["bid_amount"])
    for b in bids:
        amt = _d(b["bid_amount"])
        spread = amt - lowest
        comparison.append({
            "bid_id": b["id"],
            "bidder_name": b["bidder_name"],
            "bid_amount": str(amt.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "bid_status": b["bid_status"],
            "spread_from_low": str(spread.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        })

    ok({
        "bids": comparison,
        "total_count": len(comparison),
        "lowest_bid": str(lowest.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "highest_bid": str(_d(bids[-1]["bid_amount"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
    })


# ---------------------------------------------------------------------------
# estimate-summary
# ---------------------------------------------------------------------------
def estimate_summary(conn, args):
    est_id = getattr(args, "estimate_id", None)
    if not est_id:
        err("--estimate-id is required")
    row = conn.execute(Q.from_(_t_est).select(_t_est.star).where(_t_est.id == P()).get_sql(), (est_id,)).fetchone()
    if not row:
        err(f"Estimate {est_id} not found")

    q = Q.from_(_t_line).select(_t_line.star).where(_t_line.estimate_id == P()).orderby(_t_line.line_number)
    lines = conn.execute(q.get_sql(), (est_id,)).fetchall()

    by_category = {}
    total = Decimal("0")
    for l in lines:
        cat = l["category"]
        amt = _d(l["amount"])
        total += amt
        if cat not in by_category:
            by_category[cat] = Decimal("0")
        by_category[cat] += amt

    category_breakdown = {
        k: str(v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        for k, v in by_category.items()
    }

    markup = _d(row["markup_pct"])
    overhead = _d(row["overhead_pct"])
    profit = _d(row["profit_pct"])

    base_cost = total
    overhead_amount = (base_cost * overhead / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    markup_amount = (base_cost * markup / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    subtotal = base_cost + overhead_amount + markup_amount
    profit_amount = (subtotal * profit / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    grand_total = subtotal + profit_amount

    ok({
        "estimate_id": est_id,
        "name": row["name"],
        "line_count": len(lines),
        "base_cost": str(base_cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "by_category": category_breakdown,
        "overhead_pct": str(overhead),
        "overhead_amount": str(overhead_amount),
        "markup_pct": str(markup),
        "markup_amount": str(markup_amount),
        "profit_pct": str(profit),
        "profit_amount": str(profit_amount),
        "grand_total": str(grand_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
    })


# ---------------------------------------------------------------------------
# ACTIONS registry
# ---------------------------------------------------------------------------
ACTIONS = {
    "construction-add-estimate": add_estimate,
    "construction-update-estimate": update_estimate,
    "construction-get-estimate": get_estimate,
    "construction-list-estimates": list_estimates,
    "construction-add-estimate-line": add_estimate_line,
    "construction-update-estimate-line": update_estimate_line,
    "construction-list-estimate-lines": list_estimate_lines,
    "construction-submit-estimate": submit_estimate,
    "construction-add-bid": add_bid,
    "construction-list-bids": list_bids,
    "construction-award-bid": award_bid,
    "construction-compare-bids": compare_bids,
    "construction-estimate-summary": estimate_summary,
}
