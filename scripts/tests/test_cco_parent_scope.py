"""A contract change order cannot link another job's potential change order."""
from uuid import uuid4

import pytest

from construct_helpers import call_action, ns, seed_company
from erpclaw_lib.query import Q, P, Table
from test_jobs_estimates import TestWipReport as _Setup


def parent(conn, company, job):
    pid = str(uuid4())
    values = dict(id=pid, job_id=job, company_id=company, title="Potential scope")
    conn.execute(Q.into(Table("constructclaw_pco")).columns(*values)
                 .insert(*(P() for _ in values)).get_sql(), tuple(values.values()))
    conn.commit()
    return pid


def state(conn):
    return {name: sorted(repr(dict(row)) for row in conn.execute(
        Q.from_(Table(name)).select("*").get_sql()).fetchall())
        for name in ("constructclaw_job", "constructclaw_pco", "constructclaw_cco",
                     "naming_series", "audit_log")}


@pytest.mark.parametrize("boundary", ["other_job", "other_company", "parent_company", "missing"])
def test_parent_must_belong_to_target_job_and_company(conn, env, mod, boundary):
    setup = _Setup()
    job = setup._add_job(conn, env, mod, "1000.00")
    other_job = setup._add_job(conn, env, mod, "1000.00")
    other_company = seed_company(conn, name="Other Builder", abbr="OB")
    if boundary == "missing":
        pid = str(uuid4())
    elif boundary == "parent_company":
        pid = parent(conn, other_company, job)
    elif boundary == "other_company":
        pid = parent(conn, other_company, other_job)
    else:
        pid = parent(conn, env["company_id"], other_job)
    before = state(conn)
    result = call_action(mod.ACTIONS["construction-add-cco"], conn, ns(
        company_id=env["company_id"], job_id=job, pco_id=pid,
        title="Contract scope", cost_change="0.10"))
    assert result["status"] == "error", result
    assert "PCO" in result["message"]
    assert state(conn) == before
    assert not conn.in_transaction


@pytest.mark.parametrize("with_parent", [True, False])
def test_matching_or_absent_parent_remains_available(conn, env, mod, with_parent):
    job = _Setup()._add_job(conn, env, mod, "1000.00")
    pid = parent(conn, env["company_id"], job) if with_parent else None
    result = call_action(mod.ACTIONS["construction-add-cco"], conn, ns(
        company_id=env["company_id"], job_id=job, pco_id=pid,
        title="Contract scope", cost_change="0.10"))
    assert result["status"] == "ok", result
    table = Table("constructclaw_cco")
    row = conn.execute(Q.from_(table).select(table.pco_id, table.cost_change)
                       .where(table.id == P()).get_sql(), (result["cco_id"],)).fetchone()
    assert row["pco_id"] == pid
    assert row["cost_change"] == "0.10"
