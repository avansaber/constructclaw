"""ConstructClaw migration 001: the pay-application payable link columns.

This migration is the only thing that carries an install PREDATING this
release across to the current schema: a fresh provision already ends with
both columns present, so fresh installs prove nothing about the upgrade and
the upgrade gets its own tests.

The properties that matter:

  * an install missing both columns acquires both, and the columns it already
    had keep their identity AND their order;
  * a migrated database and a freshly provisioned one hold the same columns in
    the same order;
  * a second run adds nothing (idempotent), and so does a run against a fresh
    install;
  * an install with a row keeps that row byte-identical, with the two new
    columns NULL (the migration's `MIGRATION_DATA_CLASS = "none"` declaration
    checked at runtime rather than taken on trust);
  * a database without the tables is a clean skip, not a crash.

The pre-release fixture is built by provisioning the CONVERTED installer's
schema and then dropping the two columns, so the shape under test is derived
from the shipped declaration rather than re-typed beside it. The foundation
is provisioned by its own installer for the same reason. Everything reaches
the database through the seam.
"""
import importlib.util
import os
import sys
import uuid

import pytest

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_MODULE_DIR = os.path.dirname(os.path.dirname(_TESTS_DIR))  # constructclaw/
_MIGRATIONS_DIR = os.path.join(_MODULE_DIR, "migrations")
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from construct_helpers import get_conn, init_all_tables  # noqa: E402

from erpclaw_lib import seam  # noqa: E402
from erpclaw_lib.db import get_connection  # noqa: E402

TABLE_SUB = "constructclaw_subcontract"
TABLE_PA = "constructclaw_pay_application"
NEW_COLUMNS = ["supplier_id", "purchase_invoice_id"]

# Fixed statements: no name is formatted into SQL, in the test either.
_DROP_COLUMNS = (
    "ALTER TABLE constructclaw_subcontract DROP COLUMN supplier_id",
    "ALTER TABLE constructclaw_pay_application DROP COLUMN purchase_invoice_id",
)


def _load(name, filename, directory):
    path = os.path.join(directory, filename)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mig = _load("constructclaw_migration_001",
            "001_pay_application_payable_links.py", _MIGRATIONS_DIR)
installer = _load("constructclaw_installer", "init_db.py", _MODULE_DIR)


@pytest.fixture
def mig_db(tmp_path):
    """A database with the CURRENT constructclaw schema."""
    path = str(tmp_path / "construct.sqlite")
    init_all_tables(path)
    return path


@pytest.fixture
def pre_mig_db(mig_db):
    """`mig_db` rewound to the shape that predates this release."""
    conn = get_connection(mig_db)
    try:
        for statement in _DROP_COLUMNS:
            conn.execute(statement)
        conn.commit()
    except Exception as exc:  # noqa: BLE001 — a backend without DROP COLUMN
        pytest.skip("backend cannot rewind the fixture: %s" % exc)
    finally:
        conn.close()
    assert "supplier_id" not in seam.column_names(TABLE_SUB, mig_db)
    assert "purchase_invoice_id" not in seam.column_names(TABLE_PA, mig_db)
    return mig_db


def _seed_company_and_job(db):
    conn = get_conn(db)
    try:
        company_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO company (id, name, abbr) VALUES (?, ?, ?)",
            (company_id, "Fixture Build Co", "FBC"))
        job_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO constructclaw_job (id, name, company_id)"
            " VALUES (?, ?, ?)",
            (job_id, "Fixture Job", company_id))
        conn.commit()
    finally:
        conn.close()
    return company_id, job_id


_SUB_INSERT = (
    "INSERT INTO constructclaw_subcontract "
    "(id, naming_series, subcontract_number, job_id, subcontractor_name,"
    " original_amount, revised_amount, subcontract_status, company_id)"
    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)")
_SUB_ROW = ("sub-0001", "CCSUB-2026-00001", "CCSUB-2026-00001", None,
            "Fixture Mechanical", "100000.00", "100000.00", "draft", None)
_PA_INSERT = (
    "INSERT INTO constructclaw_pay_application "
    "(id, naming_series, subcontract_id, application_number, work_completed,"
    " materials_stored, total_earned, retention_held, previous_payments,"
    " current_payment_due, pay_app_status, company_id)"
    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")
_PA_ROW = ("pa-0001", "CCPA-2026-00001", "sub-0001", 1, "20000.00", "0",
           "20000.00", "2000.00", "0.00", "18000.00", "draft", None)
_SELECT_SUB = (
    "SELECT id, naming_series, subcontract_number, job_id, subcontractor_name,"
    " original_amount, revised_amount, subcontract_status, company_id"
    " FROM constructclaw_subcontract")
_SELECT_PA = (
    "SELECT id, naming_series, subcontract_id, application_number,"
    " work_completed, materials_stored, total_earned, retention_held,"
    " previous_payments, current_payment_due, pay_app_status, company_id"
    " FROM constructclaw_pay_application")


def test_an_install_missing_both_acquires_both(pre_mig_db):
    before_sub = seam.column_names(TABLE_SUB, pre_mig_db)
    before_pa = seam.column_names(TABLE_PA, pre_mig_db)

    result = mig.run_migration(pre_mig_db)

    assert sorted(result["added"]) == sorted(NEW_COLUMNS)
    assert result["already_present"] == []
    after_sub = seam.column_names(TABLE_SUB, pre_mig_db)
    after_pa = seam.column_names(TABLE_PA, pre_mig_db)
    assert "supplier_id" in after_sub
    assert "purchase_invoice_id" in after_pa
    # The columns that were already there keep their identity and their order;
    # the new ones append. Nothing is reordered under an operator's data.
    assert after_sub[:len(before_sub)] == before_sub
    assert after_sub[-1] == "supplier_id"
    assert after_pa[:len(before_pa)] == before_pa
    assert after_pa[-1] == "purchase_invoice_id"


def test_a_migrated_database_matches_a_fresh_one(pre_mig_db, tmp_path):
    fresh = str(tmp_path / "fresh.sqlite")
    init_all_tables(fresh)

    mig.run_migration(pre_mig_db)

    assert (seam.column_names(TABLE_SUB, pre_mig_db)
            == seam.column_names(TABLE_SUB, fresh))
    assert (seam.column_names(TABLE_PA, pre_mig_db)
            == seam.column_names(TABLE_PA, fresh))


def test_a_second_run_adds_nothing(pre_mig_db):
    first = mig.run_migration(pre_mig_db)
    cols_sub = seam.column_names(TABLE_SUB, pre_mig_db)
    cols_pa = seam.column_names(TABLE_PA, pre_mig_db)

    second = mig.run_migration(pre_mig_db)

    assert len(first["added"]) == 2
    assert second["added"] == []
    assert sorted(second["already_present"]) == sorted(NEW_COLUMNS)
    assert seam.column_names(TABLE_SUB, pre_mig_db) == cols_sub
    assert seam.column_names(TABLE_PA, pre_mig_db) == cols_pa


def test_a_fresh_install_is_a_no_op(mig_db):
    """The converted installer declares both, so there is nothing to add."""
    before_sub = seam.column_names(TABLE_SUB, mig_db)
    before_pa = seam.column_names(TABLE_PA, mig_db)

    result = mig.run_migration(mig_db)

    assert result["added"] == []
    assert sorted(result["already_present"]) == sorted(NEW_COLUMNS)
    assert seam.column_names(TABLE_SUB, mig_db) == before_sub
    assert seam.column_names(TABLE_PA, mig_db) == before_pa


def test_it_changes_no_row_it_finds(pre_mig_db):
    """`MIGRATION_DATA_CLASS = "none"`, checked rather than trusted."""
    company_id, job_id = _seed_company_and_job(pre_mig_db)
    sub_row = _SUB_ROW[:3] + (job_id,) + _SUB_ROW[4:8] + (company_id,)
    pa_row = _PA_ROW[:11] + (company_id,)
    conn = get_connection(pre_mig_db)
    try:
        conn.execute(_SUB_INSERT, sub_row)
        conn.execute(_PA_INSERT, pa_row)
        conn.commit()
    finally:
        conn.close()

    mig.run_migration(pre_mig_db)

    conn = get_connection(pre_mig_db)
    try:
        subs = conn.execute(_SELECT_SUB).fetchall()
        pay_apps = conn.execute(_SELECT_PA).fetchall()
        new_sub = conn.execute(
            "SELECT supplier_id FROM constructclaw_subcontract").fetchall()
        new_pa = conn.execute(
            "SELECT purchase_invoice_id FROM constructclaw_pay_application"
        ).fetchall()
    finally:
        conn.close()
    assert len(subs) == 1
    assert tuple(subs[0]) == sub_row
    assert len(pay_apps) == 1
    assert tuple(pay_apps[0]) == pa_row
    # The two arrive empty: a column that held nothing before the run is the
    # "not data-changing" case of the definition.
    assert tuple(new_sub[0]) == (None,)
    assert tuple(new_pa[0]) == (None,)


def test_a_database_without_the_tables_is_a_clean_skip(tmp_path):
    db = str(tmp_path / "no_construct.sqlite")
    get_connection(db).close()  # the file exists; the tables do not

    result = mig.run_migration(db)

    assert result == {"added": [], "already_present": [],
                      "reason": "table absent"}


def test_it_declares_that_it_changes_no_data():
    """The M102 declaration is part of the migration's contract."""
    assert mig.MIGRATION_DATA_CLASS == "none"


def test_both_columns_are_declared_by_the_installer_too():
    """Fresh and migrated cannot diverge if both sources name the same two.

    The installer is the fresh path and this migration is the upgrade path. They
    are two files, so nothing but a test stops one of them growing a third
    column the other never hears about.
    """
    assert "supplier_id" in {c.name for c in installer.SUBCONTRACT.columns}
    assert "purchase_invoice_id" in {
        c.name for c in installer.PAY_APPLICATION.columns}
    assert [column for _, column, _ in mig.ADD_COLUMNS] == NEW_COLUMNS
