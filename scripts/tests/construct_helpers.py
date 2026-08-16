"""Shared helper functions for ConstructClaw unit tests.

Provides:
  - DB bootstrap via init_schema.init_db() + init_constructclaw_schema()
  - call_action() / ns() / is_error() / is_ok()
  - Seed functions for company, customer, naming series
  - load_db_query() for explicit module loading
"""
import argparse
import importlib.util
import io
import json
import os
import sqlite3
import sys
import uuid
from decimal import Decimal
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
MODULE_DIR = os.path.dirname(TESTS_DIR)          # constructclaw/scripts/
ROOT_DIR = os.path.dirname(MODULE_DIR)            # constructclaw/
SRC_DIR = os.path.dirname(ROOT_DIR)               # source/
SETUP_DIR = os.path.join(SRC_DIR, "erpclaw", "scripts", "erpclaw-setup")
INIT_SCHEMA_PATH = os.path.join(SETUP_DIR, "init_schema.py")
VERTICAL_INIT_PATH = os.path.join(ROOT_DIR, "init_db.py")

# M54: bind erpclaw_lib to the tree under test, never the deployed
# ~/.openclaw/erpclaw/lib symlink — the last install to run wins that symlink,
# so with several worktrees in flight it resolves to a tree nobody is testing
# (and DANGLES once that worktree is removed). The deployed install stays as
# the fallback for a published module repo, which ships no source/erpclaw/.
_IN_TREE_LIB = os.path.join(SETUP_DIR, "lib")
ERPCLAW_LIB = (_IN_TREE_LIB if os.path.isdir(os.path.join(_IN_TREE_LIB, "erpclaw_lib"))
               else os.path.join(os.path.expanduser(
                   os.environ.get("ERPCLAW_HOME", "~/.openclaw/erpclaw")), "lib"))
if ERPCLAW_LIB not in sys.path:
    if importlib.util.find_spec("erpclaw_lib") is None:
        sys.path.insert(0, ERPCLAW_LIB)

from erpclaw_lib.db import setup_pragmas


def load_db_query():
    """Load constructclaw db_query.py explicitly to avoid sys.path collisions."""
    db_query_path = os.path.join(MODULE_DIR, "db_query.py")
    spec = importlib.util.spec_from_file_location("db_query_construct", db_query_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # Attach action functions as attributes (kebab -> underscore)
    for action_name, fn in mod.ACTIONS.items():
        setattr(mod, action_name.replace("-", "_"), fn)
    return mod


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def init_all_tables(db_path: str):
    """Create all ERPClaw core tables + constructclaw vertical tables."""
    # 1. Foundation schema (company, account, naming_series, etc.)
    spec = importlib.util.spec_from_file_location("init_schema", INIT_SCHEMA_PATH)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.init_db(db_path)

    # 2. ConstructClaw vertical schema (31 tables)
    spec2 = importlib.util.spec_from_file_location("construct_init", VERTICAL_INIT_PATH)
    m2 = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(m2)
    m2.init_constructclaw_schema(db_path)


class _ConnWrapper:
    """Wraps sqlite3.Connection with company_id attribute for action functions."""
    def __init__(self, conn, company_id=None):
        self._conn = conn
        self.company_id = company_id

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def execute(self, *a, **kw):
        return self._conn.execute(*a, **kw)

    def executemany(self, *a, **kw):
        return self._conn.executemany(*a, **kw)

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        return self._conn.close()


def get_conn(db_path: str) -> sqlite3.Connection:
    """Return a sqlite3.Connection with FK enabled and Row factory."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    setup_pragmas(conn)
    return conn


# ---------------------------------------------------------------------------
# Action invocation helpers
# ---------------------------------------------------------------------------

def call_action(fn, conn, args) -> dict:
    """Invoke a domain function, capture stdout JSON, return parsed dict."""
    buf = io.StringIO()

    def _fake_exit(code=0):
        raise SystemExit(code)

    try:
        with patch("sys.stdout", buf), patch("sys.exit", side_effect=_fake_exit):
            fn(conn, args)
    except SystemExit:
        pass

    output = buf.getvalue().strip()
    if not output:
        return {"status": "error", "message": "no output captured"}
    return json.loads(output)


def ns(**kwargs) -> argparse.Namespace:
    """Build an argparse.Namespace from keyword args (mimics CLI flags)."""
    return argparse.Namespace(**kwargs)


def is_error(result: dict) -> bool:
    """Check if a call_action result is an error response."""
    return result.get("status") == "error"


def is_ok(result: dict) -> bool:
    """Check if a call_action result is a success response."""
    return result.get("status") == "ok"


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def seed_company(conn, name="Test Construction Co", abbr="TCC") -> str:
    """Insert a test company via direct SQL and return its ID."""
    cid = _uuid()
    conn.execute(
        """INSERT INTO company (id, name, abbr, default_currency, country,
           fiscal_year_start_month)
           VALUES (?, ?, ?, 'USD', 'United States', 1)""",
        (cid, f"{name} {cid[:6]}", f"{abbr}{cid[:4]}")
    )
    conn.commit()
    return cid


def seed_customer(conn, company_id: str, name="Test Customer") -> str:
    """Insert a customer and return its ID."""
    cid = _uuid()
    conn.execute(
        """INSERT INTO customer (id, name, company_id, customer_type, status, credit_limit)
           VALUES (?, ?, ?, 'company', 'active', '0')""",
        (cid, name, company_id)
    )
    conn.commit()
    return cid


def seed_naming_series(conn, company_id: str):
    """Seed naming series for constructclaw entity types."""
    series = [
        ("constructclaw_job", "CCJOB-", 0),
        ("constructclaw_cost_code", "CCCC-", 0),
        ("constructclaw_cost_entry", "CCCE-", 0),
        ("constructclaw_commitment", "CCCM-", 0),
        ("constructclaw_estimate", "CCEST-", 0),
        ("constructclaw_bid", "CCBID-", 0),
        ("constructclaw_subcontract", "CCSUB-", 0),
        ("constructclaw_pay_application", "CCPA-", 0),
        ("constructclaw_schedule_of_values", "CCSOV-", 0),
        ("constructclaw_progress_bill", "CCPB-", 0),
        ("constructclaw_daily_report", "CCDR-", 0),
        ("constructclaw_pco", "CCPCO-", 0),
        ("constructclaw_cco", "CCCCO-", 0),
        ("constructclaw_rfi", "CCRFI-", 0),
        ("constructclaw_submittal", "CCSUBM-", 0),
        ("constructclaw_incident", "CCINC-", 0),
    ]
    for entity_type, prefix, current in series:
        conn.execute(
            """INSERT OR IGNORE INTO naming_series
               (id, entity_type, prefix, current_value, company_id)
               VALUES (?, ?, ?, ?, ?)""",
            (_uuid(), entity_type, prefix, current, company_id)
        )
    conn.commit()


def build_env(conn) -> dict:
    """Create a full constructclaw test environment.

    Returns dict with company_id, customer_id, and all naming series seeded.
    """
    cid = seed_company(conn)
    seed_naming_series(conn, cid)
    cust = seed_customer(conn, cid, "Acme Builders Client")
    return {
        "company_id": cid,
        "customer_id": cust,
    }
