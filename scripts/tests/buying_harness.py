"""In-process buying bridge for ConstructClaw pay-application tests.

Redirects cross_skill.call_skill_action to the REAL foundation functions so
every assertion stays real (service-item resolution, totals, draft status)
while still recording exactly which action and flags the vertical sent
through the shared library. Shaped like _delegate_selling_in_process in
test_progress_bill_g703.py; copied, not imported.
"""
import argparse
import importlib.util
import io
import json as _json
import os as _os
import sys as _sys
import uuid as _uuid
from unittest.mock import patch as _patch

from construct_helpers import SRC_DIR as _SRC


def _load(domain):
    path = _os.path.join(_SRC, "erpclaw", "scripts", domain, "db_query.py")
    spec = importlib.util.spec_from_file_location("_fnd_%s" % domain, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def delegate_buying_in_process(conn, monkeypatch):
    """Route add-item, list-items and create-purchase-invoice in-process.

    Returns the captured cross-skill calls. Raises CrossSkillError on an
    error result, exactly as the subprocess path would.
    """
    buying = _load("erpclaw-buying")
    inventory = _load("erpclaw-inventory")
    from erpclaw_lib import cross_skill as _cs
    captured = {}

    def _run(fn, args_ns):
        buf = io.StringIO()

        def _fake_exit(code=0):
            raise SystemExit(code)

        try:
            with _patch("sys.stdout", buf), _patch("sys.exit", side_effect=_fake_exit):
                fn(conn, args_ns)
        except SystemExit:
            pass
        return _json.loads(buf.getvalue().strip())

    def _in_process(skill_name, action, args=None, db_path=None, timeout=30):
        flags = dict(args or {})
        captured.setdefault("calls", []).append(
            {"skill": skill_name, "action": action, "args": flags})
        if action == "add-item":
            result = _run(inventory.add_item, argparse.Namespace(
                item_code=flags.get("--item-code"),
                item_name=flags.get("--item-name"),
                item_type=flags.get("--item-type"),
                valuation_method=None, item_group=None, stock_uom=None,
                has_batch=None, has_serial=None, standard_rate=None,
                custom_fields=None))
        elif action == "list-items":
            result = _run(inventory.list_items, argparse.Namespace(
                item_group=None, item_type=None, search=flags.get("--search"),
                limit="20", offset="0", warehouse_id=None, company_id=None))
        elif action == "create-purchase-invoice":
            result = _run(buying.create_purchase_invoice, argparse.Namespace(
                company_id=flags.get("--company-id"),
                supplier_id=flags.get("--supplier-id"),
                items=flags.get("--items"),
                posting_date=flags.get("--posting-date"),
                due_date=flags.get("--due-date"),
                tax_template_id=flags.get("--tax-template-id"),
                purchase_order_id=flags.get("--purchase-order-id"),
                purchase_receipt_id=flags.get("--purchase-receipt-id"),
                cwip_asset_id=flags.get("--cwip-asset-id")))
        else:
            raise AssertionError("unexpected cross-skill action %s" % action)
        if result.get("status") == "error":
            raise _cs.CrossSkillError(
                result.get("message", "%s failed" % action))
        return result

    monkeypatch.setattr(_cs, "call_skill_action", _in_process)
    return captured


def seed_supplier(conn, company_id, name="Test Supplier"):
    """Insert an active company supplier and return its id."""
    supplier_id = str(_uuid.uuid4())
    conn.execute(
        "INSERT INTO supplier (id, name, company_id, status)"
        " VALUES (?, ?, ?, 'active')",
        (supplier_id, name, company_id))
    conn.commit()
    return supplier_id
