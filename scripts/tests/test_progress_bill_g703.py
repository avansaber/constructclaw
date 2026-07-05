"""L1 tests for ConstructClaw -- G703 continuation-sheet line derivation.

Covers M33 Item 3 (B9): when construction-add-progress-bill is linked to an
SOV that has line items, it derives one constructclaw_progress_bill_line per
constructclaw_sov_line and rolls the header totals up from those lines.

Pins:
  - derivation writes one line per SOV line
  - header total_completed / total_retention == exact Decimal roll-up
  - BDFL condition 3: derived totals WIN; caller flat totals are ignored AND
    reported as overridden in the response
  - no-SOV path unchanged (backward compatibility)
  - SOV linked but with no lines falls back to the header-only path
  - get-progress-bill returns the derived lines
"""
import uuid
from decimal import Decimal

import pytest
from construct_helpers import call_action, ns, is_ok, is_error, load_db_query, _uuid


@pytest.fixture
def mod():
    return load_db_query()


def _add_job(conn, env, mod, name="G703 Job", contract_amount="1000000"):
    r = call_action(mod.ACTIONS["construction-add-job"], conn, ns(
        company_id=env["company_id"], name=name,
        job_type=None, contract_type=None, contract_amount=contract_amount,
        client_name=None, client_id=env["customer_id"], description=None,
        project_manager=None, superintendent=None,
        start_date=None, end_date=None, address=None,
        city=None, state=None, zip_code=None, notes=None,
    ))
    assert is_ok(r)
    return r["job_id"]


def _add_sov(conn, env, mod, job_id, name="Main SOV", total_contract="1000000"):
    r = call_action(mod.ACTIONS["construction-add-schedule-of-values"], conn, ns(
        company_id=env["company_id"], job_id=job_id,
        name=name, total_contract=total_contract, notes=None,
    ))
    assert is_ok(r)
    return r["sov_id"]


def _seed_sov_line(conn, company_id, sov_id, item_number, description,
                   scheduled_value, previous_completed, this_period,
                   materials_stored, retention_pct):
    """Seed a SOV line directly with progress columns populated.

    add-sov-line only sets scheduled_value (progress columns default to 0 and
    have no update action yet), so the tests seed the feeder state a future
    update path would produce, then exercise the derivation.
    """
    conn.execute(
        """INSERT INTO constructclaw_sov_line
           (id, sov_id, item_number, description, scheduled_value,
            previous_completed, this_period, materials_stored,
            balance_to_finish, retention_pct, company_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (str(uuid.uuid4()), sov_id, item_number, description, scheduled_value,
         previous_completed, this_period, materials_stored,
         scheduled_value, retention_pct, company_id),
    )
    conn.commit()


def _seed_three_lines(conn, env, sov_id):
    """Three canonical G703 lines with clean, exact-Decimal roll-ups.

    L1: 20000 + 30000 + 5000 = 55000 completed; 10% retention = 5500.00
    L2: 50000 + 25000 +     0 = 75000 completed; 10% retention = 7500.00
    L3: 10000 + 15000 + 2500 = 27500 completed;  5% retention = 1375.00
    Header roll-up: completed = 157500.00 ; retention = 14375.00
    """
    _seed_sov_line(conn, env["company_id"], sov_id, "1", "Foundations",
                   "100000", "20000", "30000", "5000", "10")
    _seed_sov_line(conn, env["company_id"], sov_id, "2", "Framing",
                   "200000", "50000", "25000", "0", "10")
    _seed_sov_line(conn, env["company_id"], sov_id, "3", "Roofing",
                   "50000", "10000", "15000", "2500", "5")


class TestG703LineDerivation:
    def test_derives_one_line_per_sov_line(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        sov_id = _add_sov(conn, env, mod, job_id)
        _seed_three_lines(conn, env, sov_id)

        r = call_action(mod.ACTIONS["construction-add-progress-bill"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            sov_id=sov_id, total_completed=None, total_retention=None,
            period_from="2026-03-01", period_to="2026-03-31", notes=None,
        ))
        assert is_ok(r)
        assert r["totals_source"] == "sov_lines"
        assert r["line_count"] == 3

        pb_id = r["progress_bill_id"]
        rows = conn.execute(
            "SELECT COUNT(*) AS c FROM constructclaw_progress_bill_line WHERE bill_id = ?",
            (pb_id,),
        ).fetchone()
        assert rows["c"] == 3

    def test_header_totals_equal_line_rollup(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        sov_id = _add_sov(conn, env, mod, job_id)
        _seed_three_lines(conn, env, sov_id)

        r = call_action(mod.ACTIONS["construction-add-progress-bill"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            sov_id=sov_id, total_completed=None, total_retention=None,
            period_from=None, period_to=None, notes=None,
        ))
        assert is_ok(r)
        # Exact Decimal roll-up asserts (money is TEXT/Decimal, never float).
        assert r["total_completed"] == "157500.00"
        assert r["total_retention"] == "14375.00"
        assert r["total_previous"] == "0.00"
        # current_due = 157500.00 - 14375.00 - 0.00
        assert r["current_due"] == "143125.00"

        # The persisted header row must carry the same roll-up.
        pb_id = r["progress_bill_id"]
        hdr = conn.execute(
            "SELECT total_completed, total_retention, current_due "
            "FROM constructclaw_progress_bill WHERE id = ?", (pb_id,),
        ).fetchone()
        assert hdr["total_completed"] == "157500.00"
        assert hdr["total_retention"] == "14375.00"
        assert hdr["current_due"] == "143125.00"

    def test_line_values_are_exact_g703_columns(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        sov_id = _add_sov(conn, env, mod, job_id)
        _seed_three_lines(conn, env, sov_id)

        r = call_action(mod.ACTIONS["construction-add-progress-bill"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            sov_id=sov_id, total_completed=None, total_retention=None,
            period_from=None, period_to=None, notes=None,
        ))
        pb_id = r["progress_bill_id"]
        lines = conn.execute(
            "SELECT item_number, total_completed, pct_complete, "
            "balance_to_finish, retention_amount "
            "FROM constructclaw_progress_bill_line WHERE bill_id = ? "
            "ORDER BY item_number", (pb_id,),
        ).fetchall()
        assert len(lines) == 3

        l1, l2, l3 = lines
        # L1: 55000 completed, 55% complete, 45000 balance, 5500 retention
        assert l1["total_completed"] == "55000.00"
        assert l1["pct_complete"] == "55.00"
        assert l1["balance_to_finish"] == "45000.00"
        assert l1["retention_amount"] == "5500.00"
        # L2: 75000 completed, 37.5% complete, 125000 balance, 7500 retention
        assert l2["total_completed"] == "75000.00"
        assert l2["pct_complete"] == "37.50"
        assert l2["balance_to_finish"] == "125000.00"
        assert l2["retention_amount"] == "7500.00"
        # L3: 27500 completed, 55% complete, 22500 balance, 1375 retention
        assert l3["total_completed"] == "27500.00"
        assert l3["pct_complete"] == "55.00"
        assert l3["balance_to_finish"] == "22500.00"
        assert l3["retention_amount"] == "1375.00"

    def test_get_progress_bill_returns_derived_lines(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        sov_id = _add_sov(conn, env, mod, job_id)
        _seed_three_lines(conn, env, sov_id)

        r = call_action(mod.ACTIONS["construction-add-progress-bill"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            sov_id=sov_id, total_completed=None, total_retention=None,
            period_from=None, period_to=None, notes=None,
        ))
        pb_id = r["progress_bill_id"]

        g = call_action(mod.ACTIONS["construction-get-progress-bill"], conn, ns(
            progress_bill_id=pb_id,
        ))
        assert is_ok(g)
        assert len(g["lines"]) == 3
        item_numbers = {ln["item_number"] for ln in g["lines"]}
        assert item_numbers == {"1", "2", "3"}
        by_item = {ln["item_number"]: ln for ln in g["lines"]}
        assert by_item["1"]["total_completed"] == "55000.00"
        assert by_item["2"]["retention_amount"] == "7500.00"


class TestG703OverridePin:
    """BDFL condition 3 -- derived totals WIN; caller flat totals overridden."""

    def test_derived_totals_override_caller_flat_totals(self, conn, env, mod):
        job_id = _add_job(conn, env, mod)
        sov_id = _add_sov(conn, env, mod, job_id)
        _seed_three_lines(conn, env, sov_id)

        # Caller supplies flat totals that DISAGREE with the SOV roll-up.
        r = call_action(mod.ACTIONS["construction-add-progress-bill"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            sov_id=sov_id,
            total_completed="999999", total_retention="888888",
            period_from=None, period_to=None, notes=None,
        ))
        assert is_ok(r)

        # Derived roll-up WINS -- the caller's flat values are NOT used.
        assert r["total_completed"] == "157500.00"
        assert r["total_retention"] == "14375.00"
        assert r["total_completed"] != "999999"
        assert r["total_retention"] != "888888"
        assert r["totals_source"] == "sov_lines"

        # Override is reported so it is observable to the existing caller class.
        assert r["caller_totals_overridden"] is True
        assert r["overridden_totals"]["total_completed"] == "999999"
        assert r["overridden_totals"]["total_retention"] == "888888"

        # And the persisted header reflects the derived totals, not the caller's.
        hdr = conn.execute(
            "SELECT total_completed, total_retention "
            "FROM constructclaw_progress_bill WHERE id = ?", (r["progress_bill_id"],),
        ).fetchone()
        assert hdr["total_completed"] == "157500.00"
        assert hdr["total_retention"] == "14375.00"


class TestG703BackwardCompatibility:
    def test_no_sov_path_unchanged(self, conn, env, mod):
        """No --sov-id: legacy header-only path, caller totals honored."""
        job_id = _add_job(conn, env, mod)
        r = call_action(mod.ACTIONS["construction-add-progress-bill"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            sov_id=None, total_completed="200000",
            total_retention="20000", period_from="2026-03-01",
            period_to="2026-03-31", notes=None,
        ))
        assert is_ok(r)
        assert r["bill_number"] == 1
        assert r["bill_status"] == "draft"
        # current_due = 200000 - 20000 - 0 = 180000
        assert r["current_due"] == "180000.00"
        assert r["total_completed"] == "200000"
        assert r["total_retention"] == "20000"
        assert r["totals_source"] == "caller"
        assert "caller_totals_overridden" not in r
        assert "line_count" not in r

        # No progress_bill_line rows written on the header-only path.
        cnt = conn.execute(
            "SELECT COUNT(*) AS c FROM constructclaw_progress_bill_line WHERE bill_id = ?",
            (r["progress_bill_id"],),
        ).fetchone()
        assert cnt["c"] == 0

    def test_g702_header_foots_to_g703_lines_with_subcent_values(self, conn, env, mod):
        """QA repro: the G702 header MUST foot exactly to its G703 lines.

        With dirty per-line values that carry a sub-cent (retention_pct% of
        total_completed routinely yields >2dp), a round-then-sum header would
        drift from the sum-then-round persisted lines. Here each line rounds
        retention 10.005 -> 10.01; three lines sum to 30.03, while a naive
        _q2(sum-of-raw) header would report 30.02. The header must equal the
        sum of the persisted line values, to the cent, string-for-string.
        """
        job_id = _add_job(conn, env, mod)
        sov_id = _add_sov(conn, env, mod, job_id)
        # 3 identical lines, each total_completed = 100.05 (all in prev), 10% retention.
        for i in (1, 2, 3):
            _seed_sov_line(conn, env["company_id"], sov_id, str(i), f"Dirty {i}",
                           "1000", "100.05", "0", "0", "10")

        r = call_action(mod.ACTIONS["construction-add-progress-bill"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            sov_id=sov_id, total_completed=None, total_retention=None,
            period_from=None, period_to=None, notes=None,
        ))
        assert is_ok(r)
        pb_id = r["progress_bill_id"]

        lines = conn.execute(
            "SELECT total_completed, retention_amount "
            "FROM constructclaw_progress_bill_line WHERE bill_id = ?", (pb_id,),
        ).fetchall()
        assert len(lines) == 3
        # Per-line retention rounds 10.005 -> 10.01 (HALF_UP).
        for ln in lines:
            assert ln["retention_amount"] == "10.01"
            assert ln["total_completed"] == "100.05"

        sum_completed = sum((Decimal(ln["total_completed"]) for ln in lines), Decimal("0"))
        sum_retention = sum((Decimal(ln["retention_amount"]) for ln in lines), Decimal("0"))

        # The G702 header must foot to its own G703 lines exactly.
        assert r["total_completed"] == str(sum_completed)   # "300.15"
        assert r["total_retention"] == str(sum_retention)   # "30.03"
        # Concrete guard against the round-then-sum drift (would be 30.02).
        assert r["total_retention"] == "30.03"

        # And the persisted header row foots to the lines too.
        hdr = conn.execute(
            "SELECT total_completed, total_retention "
            "FROM constructclaw_progress_bill WHERE id = ?", (pb_id,),
        ).fetchone()
        assert hdr["total_completed"] == str(sum_completed)
        assert hdr["total_retention"] == str(sum_retention)

    def test_sov_with_no_lines_falls_back_to_header_only(self, conn, env, mod):
        """--sov-id given but the SOV has no lines: header-only path, no rows."""
        job_id = _add_job(conn, env, mod)
        sov_id = _add_sov(conn, env, mod, job_id)  # no lines added

        r = call_action(mod.ACTIONS["construction-add-progress-bill"], conn, ns(
            company_id=env["company_id"], job_id=job_id,
            sov_id=sov_id, total_completed="120000",
            total_retention="12000", period_from=None,
            period_to=None, notes=None,
        ))
        assert is_ok(r)
        assert r["totals_source"] == "caller"
        # current_due = 120000 - 12000 - 0
        assert r["current_due"] == "108000.00"
        assert "caller_totals_overridden" not in r
        cnt = conn.execute(
            "SELECT COUNT(*) AS c FROM constructclaw_progress_bill_line WHERE bill_id = ?",
            (r["progress_bill_id"],),
        ).fetchone()
        assert cnt["c"] == 0
