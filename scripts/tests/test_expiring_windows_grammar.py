"""ConstructClaw's expiring-insurance and expiring-warranty windows are portable.

Both actions bounded their window with SQLite's date('now', '+N days'), which
PostgreSQL has no function for. The window end is now rendered by
erpclaw_lib.query.date_add_days from the same `today` the action already uses
to split expired from expiring rows.
"""
from datetime import date, timedelta

import pytest
from construct_helpers import call_action, is_ok, load_db_query, ns


@pytest.fixture
def mod():
    return load_db_query()


class _Cursor:
    def fetchall(self):
        return []


class _RecordingConn:
    def __init__(self):
        self.statements = []

    def execute(self, sql, params=None):
        self.statements.append((sql, params))
        return _Cursor()


def _only_statement(rec):
    assert len(rec.statements) == 1, rec.statements
    return rec.statements[0]


@pytest.mark.parametrize("action,column,days", [
    ("construction-check-expiring-insurance", "expiration_date", 30),
    ("construction-check-expiring-warranties", "end_date", 60),
])
def test_window_on_postgresql_has_no_sqlite_date_function(mod, monkeypatch, action, column, days):
    monkeypatch.setenv("ERPCLAW_DB_DIALECT", "postgresql")
    rec = _RecordingConn()
    call_action(mod.ACTIONS[action], rec, ns(company_id="C1"))
    sql, params = _only_statement(rec)
    assert "date('now'" not in sql
    assert f"{column} <= (CAST(? AS date) + CAST({days} AS integer))::text" in sql
    assert params == ("C1", date.today().isoformat())


@pytest.mark.parametrize("action,column,days", [
    ("construction-check-expiring-insurance", "expiration_date", 30),
    ("construction-check-expiring-warranties", "end_date", 60),
])
def test_window_on_sqlite_is_the_same_date_arithmetic(mod, monkeypatch, action, column, days):
    monkeypatch.setenv("ERPCLAW_DB_DIALECT", "sqlite")
    rec = _RecordingConn()
    call_action(mod.ACTIONS[action], rec, ns(company_id="C1"))
    sql, _params = _only_statement(rec)
    assert f"{column} <= date(?, '+' || {days} || ' days')" in sql


def _add_job(conn, env, mod):
    r = call_action(mod.ACTIONS["construction-add-job"], conn, ns(
        company_id=env["company_id"], name="Window Job",
        job_type=None, contract_type=None, contract_amount="500000",
        client_name="Acme Corp", client_id=None, description=None,
        project_manager=None, superintendent=None,
        start_date=None, end_date=None, address=None,
        city=None, state=None, zip_code=None, notes=None,
    ))
    assert is_ok(r), r
    return r["job_id"]


def test_insurance_window_includes_day_30_and_excludes_day_31(conn, env, mod, monkeypatch):
    monkeypatch.setenv("ERPCLAW_DB_DIALECT", "sqlite")
    today = date.today()
    for offset in (30, 31):
        r = call_action(mod.ACTIONS["construction-add-insurance-bond"], conn, ns(
            company_id=env["company_id"], job_id=None, subcontractor_id=None,
            document_type="builders_risk", carrier=f"Carrier {offset}",
            policy_number=None, coverage_amount="1000000",
            effective_date=None,
            expiration_date=(today + timedelta(days=offset)).isoformat()))
        assert is_ok(r), r
    r = call_action(mod.ACTIONS["construction-check-expiring-insurance"], conn,
                    ns(company_id=env["company_id"]))
    assert is_ok(r), r
    assert [b["expiration_date"] for b in r["expiring_within_30_days"]] == [
        (today + timedelta(days=30)).isoformat()]


def test_warranty_window_includes_day_60_and_excludes_day_61(conn, env, mod, monkeypatch):
    monkeypatch.setenv("ERPCLAW_DB_DIALECT", "sqlite")
    today = date.today()
    job_id = _add_job(conn, env, mod)
    for offset in (60, 61):
        r = call_action(mod.ACTIONS["construction-add-warranty"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            trade="HVAC", system=f"Unit {offset}", subcontractor_id=None,
            start_date=today.isoformat(),
            end_date=(today + timedelta(days=offset)).isoformat(),
            warranty_type="standard", description=None, contact_info=None,
            warranty_status=None))
        assert is_ok(r), r
    r = call_action(mod.ACTIONS["construction-check-expiring-warranties"], conn,
                    ns(company_id=env["company_id"]))
    assert is_ok(r), r
    assert [w["end_date"] for w in r["expiring_within_60_days"]] == [
        (today + timedelta(days=60)).isoformat()]
