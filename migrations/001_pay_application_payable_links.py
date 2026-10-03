"""ConstructClaw migration 001: pay-application payable link columns.

Adds the nullable TEXT ``supplier_id`` column to ``constructclaw_subcontract``
and the nullable TEXT ``purchase_invoice_id`` column to
``constructclaw_pay_application``. Both are bare TEXT pointers with no foreign
key, no index and no default — exactly what the converted installer now
declares (like ``sales_invoice_id`` on the progress bill). An install that
predates this release acquires them here; a fresh install already has them.

money: neither column is a money column; the module's amounts live in the
existing TEXT money columns and are untouched here.

Usage:
    python3 001_pay_application_payable_links.py [--db-path PATH]
"""
import argparse
import importlib.util
import os
import sys

# M102: adds two columns and nothing else. No row is read, rewritten, inserted or
# deleted; before this run each of these columns held nothing on every
# install. That is the "a new column" case of the definition, not a rewrite.
MIGRATION_DATA_CLASS = "none"

# Deployed-lib bootstrap, guarded: production has nothing pre-imported so this
# resolves the installed lib, while a caller that already bound a tree (tests,
# the module runner inside a worktree) keeps its binding (ADR-0034 step 2d).
if importlib.util.find_spec("erpclaw_lib") is None:  # pragma: no cover - env-dependent
    sys.path.insert(0, os.path.join(
        os.path.expanduser(os.environ.get("ERPCLAW_HOME", "~/.openclaw/erpclaw")), "lib"))

from erpclaw_lib import seam  # noqa: E402
from erpclaw_lib.db import get_connection, get_dialect  # noqa: E402
from erpclaw_lib.paths import db_default  # noqa: E402

DEFAULT_DB_PATH = db_default()

# (table, column, statement). Spelled out in full rather than assembled from the
# names, so no name is ever formatted INTO SQL. The type is TEXT and the column is
# nullable with no default on both backends — exactly what the retired
# in-installer loop produced, and what the converted installer now declares.
ADD_COLUMNS = (
    ("constructclaw_subcontract",
     "supplier_id",
     "ALTER TABLE constructclaw_subcontract ADD COLUMN supplier_id TEXT"),
    ("constructclaw_pay_application",
     "purchase_invoice_id",
     "ALTER TABLE constructclaw_pay_application ADD COLUMN purchase_invoice_id TEXT"),
)


def _target(db_path):
    """The database to act on.

    On PostgreSQL the runner passes ``ERPCLAW_DB_URL`` when set, else the
    location it was given (from the module manager, the SQLite default file
    path); ``connect.py`` passes ``None`` or the action's ``--db-path``; a URL
    argument is used as given, anything else yields ``None``.
    """
    if get_dialect() == "postgresql":
        if isinstance(db_path, str) and (
                db_path.startswith("postgresql://")
                or db_path.startswith("postgres://")):
            return db_path
        return None
    return db_path or os.environ.get("ERPCLAW_DB_PATH", DEFAULT_DB_PATH)


def run_migration(db_path=None):
    """Add whichever of the two payable-link columns this install is missing.

    Returns ``{"added": [...], "already_present": [...]}`` so a caller can tell a
    real upgrade from a no-op. The runner discards it; the module's lazy-upgrade
    path in `scripts/connect.py` does not.
    """
    target = _target(db_path)

    present_tables = [table for table, _, _ in ADD_COLUMNS
                      if seam.table_exists(table, target)]
    if not present_tables:
        print("  constructclaw subcontract/pay-application tables absent on this "
              "install. Nothing to migrate.")
        return {"added": [], "already_present": [], "reason": "table absent"}

    added = []
    already = []
    pending = []
    for table, column, statement in ADD_COLUMNS:
        if table not in present_tables:
            continue
        if column in seam.column_names(table, target):
            already.append(column)
        else:
            pending.append((table, column, statement))

    if not pending:
        print("  constructclaw payable-link columns already present "
              "(idempotent no-op).")
        return {"added": [], "already_present": already}

    conn = get_connection(target)
    try:
        for table, column, statement in pending:
            conn.execute(statement)
            print(f"  {table}.{column}: added.")
        conn.commit()
    finally:
        conn.close()

    if already:
        print(f"  constructclaw: {len(already)} column(s) were already present "
              f"({', '.join(already)}).")
    print(f"  constructclaw: {len(pending)} payable-link column(s) added; no row was "
          f"read or written.")
    return {"added": [column for _, column, _ in pending], "already_present": already}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="constructclaw migration 001: add the pay-application "
                    "payable link columns")
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH)
    args = parser.parse_args()
    run_migration(args.db_path)
    print("constructclaw migration 001 complete.")
