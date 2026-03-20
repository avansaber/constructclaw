"""ConstructClaw -- schema initialization.

Creates 31 tables for construction project management
in the shared ERPClaw database.
Requires company table to exist (erpclaw-setup).
"""
import os
import sqlite3
import sys

DB_PATH = os.environ.get(
    "ERPCLAW_DB_PATH",
    os.path.expanduser("~/.openclaw/erpclaw/data.sqlite"),
)


def init_constructclaw_schema(db_path: str = DB_PATH) -> dict:
    """Create construction management tables and indexes."""
    conn = sqlite3.connect(db_path)
    from erpclaw_lib.db import setup_pragmas
    setup_pragmas(conn)

    tables_created = 0
    indexes_created = 0

    # -------------------------------------------------------------------
    # 1. constructclaw_job -- construction jobs / projects
    # -------------------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS constructclaw_job (
            id                  TEXT PRIMARY KEY,
            naming_series       TEXT,
            job_number          TEXT,
            name                TEXT NOT NULL,
            description         TEXT,
            client_name         TEXT,
            client_id           TEXT,
            project_manager     TEXT,
            superintendent      TEXT,
            job_type            TEXT NOT NULL DEFAULT 'general'
                                CHECK(job_type IN ('general','residential','commercial','industrial','infrastructure','renovation','other')),
            contract_type       TEXT NOT NULL DEFAULT 'lump_sum'
                                CHECK(contract_type IN ('lump_sum','cost_plus','time_and_material','unit_price','gmp','design_build')),
            contract_amount     TEXT NOT NULL DEFAULT '0',
            start_date          TEXT,
            end_date            TEXT,
            actual_start_date   TEXT,
            actual_end_date     TEXT,
            address             TEXT,
            city                TEXT,
            state               TEXT,
            zip_code            TEXT,
            job_status          TEXT NOT NULL DEFAULT 'planning'
                                CHECK(job_status IN ('planning','bidding','awarded','active','on_hold','substantially_complete','closed','cancelled')),
            percent_complete    TEXT DEFAULT '0',
            notes               TEXT,
            company_id          TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccjob_company ON constructclaw_job(company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccjob_status ON constructclaw_job(job_status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccjob_type ON constructclaw_job(job_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccjob_number ON constructclaw_job(job_number)")
    indexes_created += 4

    # -------------------------------------------------------------------
    # 2. constructclaw_cost_code -- cost code master for WBS
    # -------------------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS constructclaw_cost_code (
            id                  TEXT PRIMARY KEY,
            job_id              TEXT NOT NULL REFERENCES constructclaw_job(id) ON DELETE CASCADE,
            code                TEXT NOT NULL,
            description         TEXT,
            category            TEXT NOT NULL DEFAULT 'labor'
                                CHECK(category IN ('labor','material','equipment','subcontract','overhead','other')),
            budget_amount       TEXT NOT NULL DEFAULT '0',
            budget_hours        TEXT DEFAULT '0',
            is_active           INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
            company_id          TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cccc_job ON constructclaw_cost_code(job_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cccc_code ON constructclaw_cost_code(code)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cccc_company ON constructclaw_cost_code(company_id)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_cccc_job_code ON constructclaw_cost_code(job_id, code)")
    indexes_created += 4

    # -------------------------------------------------------------------
    # 3. constructclaw_cost_entry -- actual cost transactions
    # -------------------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS constructclaw_cost_entry (
            id                  TEXT PRIMARY KEY,
            job_id              TEXT NOT NULL REFERENCES constructclaw_job(id) ON DELETE RESTRICT,
            cost_code_id        TEXT REFERENCES constructclaw_cost_code(id) ON DELETE SET NULL,
            entry_date          TEXT NOT NULL DEFAULT CURRENT_DATE,
            category            TEXT NOT NULL DEFAULT 'labor'
                                CHECK(category IN ('labor','material','equipment','subcontract','overhead','other')),
            description         TEXT,
            vendor              TEXT,
            reference           TEXT,
            quantity            TEXT DEFAULT '0',
            unit_cost           TEXT DEFAULT '0',
            amount              TEXT NOT NULL DEFAULT '0',
            hours               TEXT DEFAULT '0',
            company_id          TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccce_job ON constructclaw_cost_entry(job_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccce_code ON constructclaw_cost_entry(cost_code_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccce_date ON constructclaw_cost_entry(entry_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccce_company ON constructclaw_cost_entry(company_id)")
    indexes_created += 4

    # -------------------------------------------------------------------
    # 4. constructclaw_commitment -- purchase commitments (POs, subcontracts)
    # -------------------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS constructclaw_commitment (
            id                  TEXT PRIMARY KEY,
            job_id              TEXT NOT NULL REFERENCES constructclaw_job(id) ON DELETE RESTRICT,
            cost_code_id        TEXT REFERENCES constructclaw_cost_code(id) ON DELETE SET NULL,
            commitment_type     TEXT NOT NULL DEFAULT 'purchase_order'
                                CHECK(commitment_type IN ('purchase_order','subcontract','change_order','other')),
            vendor              TEXT,
            description         TEXT,
            original_amount     TEXT NOT NULL DEFAULT '0',
            revised_amount      TEXT NOT NULL DEFAULT '0',
            invoiced_amount     TEXT NOT NULL DEFAULT '0',
            paid_amount         TEXT NOT NULL DEFAULT '0',
            commitment_status   TEXT NOT NULL DEFAULT 'draft'
                                CHECK(commitment_status IN ('draft','approved','open','closed','cancelled')),
            company_id          TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cccm_job ON constructclaw_commitment(job_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cccm_company ON constructclaw_commitment(company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cccm_status ON constructclaw_commitment(commitment_status)")
    indexes_created += 3

    # -------------------------------------------------------------------
    # 5. constructclaw_estimate -- project estimates / bids
    # -------------------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS constructclaw_estimate (
            id                  TEXT PRIMARY KEY,
            naming_series       TEXT,
            job_id              TEXT REFERENCES constructclaw_job(id) ON DELETE SET NULL,
            estimate_number     TEXT,
            name                TEXT NOT NULL,
            client_name         TEXT,
            description         TEXT,
            estimate_date       TEXT NOT NULL DEFAULT CURRENT_DATE,
            due_date            TEXT,
            total_amount        TEXT NOT NULL DEFAULT '0',
            markup_pct          TEXT DEFAULT '0',
            overhead_pct        TEXT DEFAULT '0',
            profit_pct          TEXT DEFAULT '0',
            estimate_status     TEXT NOT NULL DEFAULT 'draft'
                                CHECK(estimate_status IN ('draft','submitted','won','lost','revised','cancelled')),
            notes               TEXT,
            company_id          TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccest_company ON constructclaw_estimate(company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccest_status ON constructclaw_estimate(estimate_status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccest_job ON constructclaw_estimate(job_id)")
    indexes_created += 3

    # -------------------------------------------------------------------
    # 6. constructclaw_estimate_line -- line items within an estimate
    # -------------------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS constructclaw_estimate_line (
            id                  TEXT PRIMARY KEY,
            estimate_id         TEXT NOT NULL REFERENCES constructclaw_estimate(id) ON DELETE CASCADE,
            line_number         INTEGER NOT NULL DEFAULT 0,
            description         TEXT NOT NULL,
            category            TEXT NOT NULL DEFAULT 'labor'
                                CHECK(category IN ('labor','material','equipment','subcontract','overhead','other')),
            quantity            TEXT NOT NULL DEFAULT '0',
            unit                TEXT DEFAULT 'ea',
            unit_cost           TEXT NOT NULL DEFAULT '0',
            amount              TEXT NOT NULL DEFAULT '0',
            notes               TEXT,
            company_id          TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccel_estimate ON constructclaw_estimate_line(estimate_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccel_company ON constructclaw_estimate_line(company_id)")
    indexes_created += 2

    # -------------------------------------------------------------------
    # 7. constructclaw_bid -- bid submissions
    # -------------------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS constructclaw_bid (
            id                  TEXT PRIMARY KEY,
            naming_series       TEXT,
            estimate_id         TEXT REFERENCES constructclaw_estimate(id) ON DELETE SET NULL,
            job_id              TEXT REFERENCES constructclaw_job(id) ON DELETE SET NULL,
            bid_number          TEXT,
            bidder_name         TEXT NOT NULL,
            bid_amount          TEXT NOT NULL DEFAULT '0',
            bid_date            TEXT NOT NULL DEFAULT CURRENT_DATE,
            scope_description   TEXT,
            exclusions          TEXT,
            bid_status          TEXT NOT NULL DEFAULT 'submitted'
                                CHECK(bid_status IN ('submitted','under_review','awarded','rejected','withdrawn')),
            notes               TEXT,
            company_id          TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccbid_company ON constructclaw_bid(company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccbid_estimate ON constructclaw_bid(estimate_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccbid_status ON constructclaw_bid(bid_status)")
    indexes_created += 3

    # -------------------------------------------------------------------
    # 8. constructclaw_subcontract -- subcontractor agreements
    # -------------------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS constructclaw_subcontract (
            id                  TEXT PRIMARY KEY,
            naming_series       TEXT,
            job_id              TEXT NOT NULL REFERENCES constructclaw_job(id) ON DELETE RESTRICT,
            subcontract_number  TEXT,
            subcontractor_name  TEXT NOT NULL,
            trade               TEXT,
            scope_of_work       TEXT,
            original_amount     TEXT NOT NULL DEFAULT '0',
            revised_amount      TEXT NOT NULL DEFAULT '0',
            retention_pct       TEXT DEFAULT '10',
            insurance_expiry    TEXT,
            license_number      TEXT,
            start_date          TEXT,
            end_date            TEXT,
            subcontract_status  TEXT NOT NULL DEFAULT 'draft'
                                CHECK(subcontract_status IN ('draft','pending_approval','approved','active','on_hold','complete','terminated','cancelled')),
            notes               TEXT,
            company_id          TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccsub_company ON constructclaw_subcontract(company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccsub_job ON constructclaw_subcontract(job_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccsub_status ON constructclaw_subcontract(subcontract_status)")
    indexes_created += 3

    # -------------------------------------------------------------------
    # 9. constructclaw_subcontract_line -- line items within a subcontract
    # -------------------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS constructclaw_subcontract_line (
            id                  TEXT PRIMARY KEY,
            subcontract_id      TEXT NOT NULL REFERENCES constructclaw_subcontract(id) ON DELETE CASCADE,
            line_number         INTEGER NOT NULL DEFAULT 0,
            description         TEXT NOT NULL,
            quantity            TEXT NOT NULL DEFAULT '0',
            unit                TEXT DEFAULT 'ls',
            unit_cost           TEXT NOT NULL DEFAULT '0',
            amount              TEXT NOT NULL DEFAULT '0',
            company_id          TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccsl_sub ON constructclaw_subcontract_line(subcontract_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccsl_company ON constructclaw_subcontract_line(company_id)")
    indexes_created += 2

    # -------------------------------------------------------------------
    # 10. constructclaw_pay_application -- subcontractor pay apps
    # -------------------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS constructclaw_pay_application (
            id                  TEXT PRIMARY KEY,
            naming_series       TEXT,
            subcontract_id      TEXT NOT NULL REFERENCES constructclaw_subcontract(id) ON DELETE RESTRICT,
            application_number  INTEGER NOT NULL DEFAULT 1,
            period_from         TEXT,
            period_to           TEXT,
            work_completed      TEXT NOT NULL DEFAULT '0',
            materials_stored    TEXT NOT NULL DEFAULT '0',
            total_earned        TEXT NOT NULL DEFAULT '0',
            retention_held      TEXT NOT NULL DEFAULT '0',
            previous_payments   TEXT NOT NULL DEFAULT '0',
            current_payment_due TEXT NOT NULL DEFAULT '0',
            pay_app_status      TEXT NOT NULL DEFAULT 'draft'
                                CHECK(pay_app_status IN ('draft','submitted','approved','rejected','paid')),
            notes               TEXT,
            company_id          TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccpa_sub ON constructclaw_pay_application(subcontract_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccpa_company ON constructclaw_pay_application(company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccpa_status ON constructclaw_pay_application(pay_app_status)")
    indexes_created += 3

    # -------------------------------------------------------------------
    # 11. constructclaw_lien_waiver -- lien waiver tracking
    # -------------------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS constructclaw_lien_waiver (
            id                  TEXT PRIMARY KEY,
            subcontract_id      TEXT NOT NULL REFERENCES constructclaw_subcontract(id) ON DELETE RESTRICT,
            pay_application_id  TEXT REFERENCES constructclaw_pay_application(id) ON DELETE SET NULL,
            waiver_type         TEXT NOT NULL DEFAULT 'conditional_progress'
                                CHECK(waiver_type IN ('conditional_progress','unconditional_progress','conditional_final','unconditional_final')),
            amount              TEXT NOT NULL DEFAULT '0',
            through_date        TEXT,
            received_date       TEXT,
            waiver_status       TEXT NOT NULL DEFAULT 'pending'
                                CHECK(waiver_status IN ('pending','received','verified')),
            notes               TEXT,
            company_id          TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cclw_sub ON constructclaw_lien_waiver(subcontract_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cclw_company ON constructclaw_lien_waiver(company_id)")
    indexes_created += 2

    # -------------------------------------------------------------------
    # 12. constructclaw_schedule_of_values -- SOV header (AIA G702/G703)
    # -------------------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS constructclaw_schedule_of_values (
            id                  TEXT PRIMARY KEY,
            naming_series       TEXT,
            job_id              TEXT NOT NULL REFERENCES constructclaw_job(id) ON DELETE RESTRICT,
            sov_number          TEXT,
            name                TEXT NOT NULL,
            total_contract      TEXT NOT NULL DEFAULT '0',
            total_change_orders TEXT NOT NULL DEFAULT '0',
            revised_contract    TEXT NOT NULL DEFAULT '0',
            sov_status          TEXT NOT NULL DEFAULT 'draft'
                                CHECK(sov_status IN ('draft','approved','active','closed')),
            notes               TEXT,
            company_id          TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccsov_job ON constructclaw_schedule_of_values(job_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccsov_company ON constructclaw_schedule_of_values(company_id)")
    indexes_created += 2

    # -------------------------------------------------------------------
    # 13. constructclaw_sov_line -- SOV line items
    # -------------------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS constructclaw_sov_line (
            id                  TEXT PRIMARY KEY,
            sov_id              TEXT NOT NULL REFERENCES constructclaw_schedule_of_values(id) ON DELETE CASCADE,
            item_number         TEXT NOT NULL,
            description         TEXT NOT NULL,
            scheduled_value     TEXT NOT NULL DEFAULT '0',
            previous_completed  TEXT NOT NULL DEFAULT '0',
            this_period         TEXT NOT NULL DEFAULT '0',
            materials_stored    TEXT NOT NULL DEFAULT '0',
            total_completed     TEXT NOT NULL DEFAULT '0',
            pct_complete        TEXT DEFAULT '0',
            balance_to_finish   TEXT NOT NULL DEFAULT '0',
            retention_pct       TEXT DEFAULT '10',
            company_id          TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccsvl_sov ON constructclaw_sov_line(sov_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccsvl_company ON constructclaw_sov_line(company_id)")
    indexes_created += 2

    # -------------------------------------------------------------------
    # 14. constructclaw_progress_bill -- AIA G702 pay application header
    # -------------------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS constructclaw_progress_bill (
            id                  TEXT PRIMARY KEY,
            naming_series       TEXT,
            job_id              TEXT NOT NULL REFERENCES constructclaw_job(id) ON DELETE RESTRICT,
            sov_id              TEXT REFERENCES constructclaw_schedule_of_values(id) ON DELETE SET NULL,
            bill_number         INTEGER NOT NULL DEFAULT 1,
            period_from         TEXT,
            period_to           TEXT,
            total_completed     TEXT NOT NULL DEFAULT '0',
            total_retention     TEXT NOT NULL DEFAULT '0',
            total_previous      TEXT NOT NULL DEFAULT '0',
            current_due         TEXT NOT NULL DEFAULT '0',
            bill_status         TEXT NOT NULL DEFAULT 'draft'
                                CHECK(bill_status IN ('draft','submitted','approved','paid','rejected')),
            sales_invoice_id    TEXT,
            notes               TEXT,
            company_id          TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccpb_job ON constructclaw_progress_bill(job_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccpb_sov ON constructclaw_progress_bill(sov_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccpb_company ON constructclaw_progress_bill(company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccpb_status ON constructclaw_progress_bill(bill_status)")
    indexes_created += 4

    # -------------------------------------------------------------------
    # 15. constructclaw_progress_bill_line -- AIA G703 line items per bill
    # -------------------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS constructclaw_progress_bill_line (
            id                  TEXT PRIMARY KEY,
            bill_id             TEXT NOT NULL REFERENCES constructclaw_progress_bill(id) ON DELETE CASCADE,
            sov_line_id         TEXT REFERENCES constructclaw_sov_line(id) ON DELETE SET NULL,
            item_number         TEXT,
            description         TEXT NOT NULL,
            scheduled_value     TEXT NOT NULL DEFAULT '0',
            previous_completed  TEXT NOT NULL DEFAULT '0',
            this_period         TEXT NOT NULL DEFAULT '0',
            materials_stored    TEXT NOT NULL DEFAULT '0',
            total_completed     TEXT NOT NULL DEFAULT '0',
            pct_complete        TEXT DEFAULT '0',
            balance_to_finish   TEXT NOT NULL DEFAULT '0',
            retention_amount    TEXT NOT NULL DEFAULT '0',
            company_id          TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccpbl_bill ON constructclaw_progress_bill_line(bill_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccpbl_company ON constructclaw_progress_bill_line(company_id)")
    indexes_created += 2

    # -------------------------------------------------------------------
    # 16. constructclaw_retention -- retention tracking
    # -------------------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS constructclaw_retention (
            id                  TEXT PRIMARY KEY,
            job_id              TEXT NOT NULL REFERENCES constructclaw_job(id) ON DELETE RESTRICT,
            subcontract_id      TEXT REFERENCES constructclaw_subcontract(id) ON DELETE SET NULL,
            retention_type      TEXT NOT NULL DEFAULT 'owner'
                                CHECK(retention_type IN ('owner','subcontractor')),
            amount_held         TEXT NOT NULL DEFAULT '0',
            amount_released     TEXT NOT NULL DEFAULT '0',
            balance             TEXT NOT NULL DEFAULT '0',
            release_date        TEXT,
            retention_status    TEXT NOT NULL DEFAULT 'held'
                                CHECK(retention_status IN ('held','partial_release','released')),
            notes               TEXT,
            company_id          TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccret_job ON constructclaw_retention(job_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccret_company ON constructclaw_retention(company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccret_status ON constructclaw_retention(retention_status)")
    indexes_created += 3

    # -------------------------------------------------------------------
    # 17. constructclaw_daily_report -- daily field reports
    # -------------------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS constructclaw_daily_report (
            id                  TEXT PRIMARY KEY,
            naming_series       TEXT,
            job_id              TEXT NOT NULL REFERENCES constructclaw_job(id) ON DELETE RESTRICT,
            report_date         TEXT NOT NULL DEFAULT CURRENT_DATE,
            superintendent      TEXT,
            weather             TEXT,
            temperature_high    TEXT,
            temperature_low     TEXT,
            work_description    TEXT,
            delays              TEXT,
            visitors            TEXT,
            report_status       TEXT NOT NULL DEFAULT 'draft'
                                CHECK(report_status IN ('draft','submitted','approved')),
            notes               TEXT,
            company_id          TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccdr_job ON constructclaw_daily_report(job_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccdr_date ON constructclaw_daily_report(report_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccdr_company ON constructclaw_daily_report(company_id)")
    indexes_created += 3

    # -------------------------------------------------------------------
    # 18. constructclaw_daily_labor -- labor entries for daily reports
    # -------------------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS constructclaw_daily_labor (
            id                  TEXT PRIMARY KEY,
            daily_report_id     TEXT NOT NULL REFERENCES constructclaw_daily_report(id) ON DELETE CASCADE,
            trade               TEXT NOT NULL,
            headcount           INTEGER NOT NULL DEFAULT 0,
            hours               TEXT NOT NULL DEFAULT '0',
            description         TEXT,
            company_id          TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccdl_report ON constructclaw_daily_labor(daily_report_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccdl_company ON constructclaw_daily_labor(company_id)")
    indexes_created += 2

    # -------------------------------------------------------------------
    # 19. constructclaw_daily_material -- material deliveries for daily reports
    # -------------------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS constructclaw_daily_material (
            id                  TEXT PRIMARY KEY,
            daily_report_id     TEXT NOT NULL REFERENCES constructclaw_daily_report(id) ON DELETE CASCADE,
            material_name       TEXT NOT NULL,
            quantity            TEXT NOT NULL DEFAULT '0',
            unit                TEXT DEFAULT 'ea',
            supplier            TEXT,
            delivery_ticket     TEXT,
            company_id          TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccdm_report ON constructclaw_daily_material(daily_report_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccdm_company ON constructclaw_daily_material(company_id)")
    indexes_created += 2

    # -------------------------------------------------------------------
    # 20. constructclaw_pco -- potential change order
    # -------------------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS constructclaw_pco (
            id                  TEXT PRIMARY KEY,
            naming_series       TEXT,
            job_id              TEXT NOT NULL REFERENCES constructclaw_job(id) ON DELETE RESTRICT,
            pco_number          TEXT,
            title               TEXT NOT NULL,
            description         TEXT,
            reason              TEXT,
            cost_impact         TEXT NOT NULL DEFAULT '0',
            time_impact_days    INTEGER DEFAULT 0,
            requested_by        TEXT,
            pco_status          TEXT NOT NULL DEFAULT 'identified'
                                CHECK(pco_status IN ('identified','pricing','submitted','approved','rejected','void')),
            notes               TEXT,
            company_id          TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccpco_job ON constructclaw_pco(job_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccpco_company ON constructclaw_pco(company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccpco_status ON constructclaw_pco(pco_status)")
    indexes_created += 3

    # -------------------------------------------------------------------
    # 21. constructclaw_cco -- contract change order (approved change)
    # -------------------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS constructclaw_cco (
            id                  TEXT PRIMARY KEY,
            naming_series       TEXT,
            job_id              TEXT NOT NULL REFERENCES constructclaw_job(id) ON DELETE RESTRICT,
            pco_id              TEXT REFERENCES constructclaw_pco(id) ON DELETE SET NULL,
            cco_number          TEXT,
            title               TEXT NOT NULL,
            description         TEXT,
            cost_change         TEXT NOT NULL DEFAULT '0',
            time_change_days    INTEGER DEFAULT 0,
            new_contract_amount TEXT DEFAULT '0',
            cco_status          TEXT NOT NULL DEFAULT 'draft'
                                CHECK(cco_status IN ('draft','pending','approved','executed','rejected','void')),
            approved_by         TEXT,
            approved_date       TEXT,
            notes               TEXT,
            company_id          TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cccco_job ON constructclaw_cco(job_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cccco_company ON constructclaw_cco(company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cccco_pco ON constructclaw_cco(pco_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cccco_status ON constructclaw_cco(cco_status)")
    indexes_created += 4

    # -------------------------------------------------------------------
    # 22. constructclaw_rfi -- request for information
    # -------------------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS constructclaw_rfi (
            id                  TEXT PRIMARY KEY,
            naming_series       TEXT,
            job_id              TEXT NOT NULL REFERENCES constructclaw_job(id) ON DELETE RESTRICT,
            rfi_number          TEXT,
            subject             TEXT NOT NULL,
            question            TEXT NOT NULL,
            response            TEXT,
            initiated_by        TEXT,
            assigned_to         TEXT,
            priority            TEXT NOT NULL DEFAULT 'normal'
                                CHECK(priority IN ('critical','high','normal','low')),
            date_sent           TEXT NOT NULL DEFAULT CURRENT_DATE,
            date_required       TEXT,
            date_responded      TEXT,
            cost_impact         TEXT DEFAULT '0',
            schedule_impact_days INTEGER DEFAULT 0,
            rfi_status          TEXT NOT NULL DEFAULT 'open'
                                CHECK(rfi_status IN ('open','responded','closed','void')),
            notes               TEXT,
            company_id          TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccrfi_job ON constructclaw_rfi(job_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccrfi_company ON constructclaw_rfi(company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccrfi_status ON constructclaw_rfi(rfi_status)")
    indexes_created += 3

    # -------------------------------------------------------------------
    # 23. constructclaw_submittal -- submittal tracking
    # -------------------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS constructclaw_submittal (
            id                  TEXT PRIMARY KEY,
            naming_series       TEXT,
            job_id              TEXT NOT NULL REFERENCES constructclaw_job(id) ON DELETE RESTRICT,
            submittal_number    TEXT,
            spec_section        TEXT,
            title               TEXT NOT NULL,
            description         TEXT,
            submitted_by        TEXT,
            submitted_to        TEXT,
            date_submitted      TEXT NOT NULL DEFAULT CURRENT_DATE,
            date_required       TEXT,
            date_returned       TEXT,
            submittal_status    TEXT NOT NULL DEFAULT 'pending'
                                CHECK(submittal_status IN ('pending','under_review','approved','approved_as_noted','revise_resubmit','rejected')),
            review_comments     TEXT,
            notes               TEXT,
            company_id          TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccsubm_job ON constructclaw_submittal(job_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccsubm_company ON constructclaw_submittal(company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccsubm_status ON constructclaw_submittal(submittal_status)")
    indexes_created += 3

    # -------------------------------------------------------------------
    # 24. constructclaw_incident -- safety incidents
    # -------------------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS constructclaw_incident (
            id                  TEXT PRIMARY KEY,
            naming_series       TEXT,
            job_id              TEXT NOT NULL REFERENCES constructclaw_job(id) ON DELETE RESTRICT,
            incident_number     TEXT,
            incident_date       TEXT NOT NULL DEFAULT CURRENT_DATE,
            incident_time       TEXT,
            incident_type       TEXT NOT NULL DEFAULT 'near_miss'
                                CHECK(incident_type IN ('near_miss','first_aid','recordable','lost_time','fatality','property_damage','environmental','other')),
            severity            TEXT NOT NULL DEFAULT 'minor'
                                CHECK(severity IN ('minor','moderate','serious','critical','fatal')),
            location            TEXT,
            description         TEXT NOT NULL,
            injured_party       TEXT,
            witnesses           TEXT,
            root_cause          TEXT,
            corrective_action   TEXT,
            osha_recordable     INTEGER NOT NULL DEFAULT 0 CHECK(osha_recordable IN (0,1)),
            days_lost           INTEGER DEFAULT 0,
            incident_status     TEXT NOT NULL DEFAULT 'open'
                                CHECK(incident_status IN ('open','investigating','corrective_action','closed')),
            notes               TEXT,
            company_id          TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccinc_job ON constructclaw_incident(job_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccinc_company ON constructclaw_incident(company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccinc_type ON constructclaw_incident(incident_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccinc_status ON constructclaw_incident(incident_status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccinc_date ON constructclaw_incident(incident_date)")
    indexes_created += 5

    # -------------------------------------------------------------------
    # 25. constructclaw_toolbox_talk -- safety meetings
    # -------------------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS constructclaw_toolbox_talk (
            id                  TEXT PRIMARY KEY,
            job_id              TEXT NOT NULL REFERENCES constructclaw_job(id) ON DELETE RESTRICT,
            talk_date           TEXT NOT NULL DEFAULT CURRENT_DATE,
            topic               TEXT NOT NULL,
            presenter           TEXT,
            attendee_count      INTEGER NOT NULL DEFAULT 0,
            attendees           TEXT,
            duration_minutes    INTEGER DEFAULT 0,
            notes               TEXT,
            company_id          TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cctt_job ON constructclaw_toolbox_talk(job_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cctt_company ON constructclaw_toolbox_talk(company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cctt_date ON constructclaw_toolbox_talk(talk_date)")
    indexes_created += 3

    # -------------------------------------------------------------------
    # 26. constructclaw_safety_cert -- safety certifications for workers
    # -------------------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS constructclaw_safety_cert (
            id                  TEXT PRIMARY KEY,
            job_id              TEXT REFERENCES constructclaw_job(id) ON DELETE SET NULL,
            worker_name         TEXT NOT NULL,
            cert_type           TEXT NOT NULL,
            cert_number         TEXT,
            issued_date         TEXT,
            expiry_date         TEXT,
            issuing_authority   TEXT,
            cert_status         TEXT NOT NULL DEFAULT 'active'
                                CHECK(cert_status IN ('active','expiring_soon','expired','revoked')),
            company_id          TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccsc_company ON constructclaw_safety_cert(company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccsc_worker ON constructclaw_safety_cert(worker_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccsc_expiry ON constructclaw_safety_cert(expiry_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccsc_status ON constructclaw_safety_cert(cert_status)")
    indexes_created += 4

    # -------------------------------------------------------------------
    # 27. constructclaw_earned_value -- earned value management data points
    # -------------------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS constructclaw_earned_value (
            id                  TEXT PRIMARY KEY,
            job_id              TEXT NOT NULL REFERENCES constructclaw_job(id) ON DELETE RESTRICT,
            period_date         TEXT NOT NULL DEFAULT CURRENT_DATE,
            planned_value       TEXT NOT NULL DEFAULT '0',
            earned_value        TEXT NOT NULL DEFAULT '0',
            actual_cost         TEXT NOT NULL DEFAULT '0',
            budget_at_completion TEXT NOT NULL DEFAULT '0',
            notes               TEXT,
            company_id          TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccev_job ON constructclaw_earned_value(job_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccev_company ON constructclaw_earned_value(company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccev_date ON constructclaw_earned_value(period_date)")
    indexes_created += 3

    # -------------------------------------------------------------------
    # 28. constructclaw_equipment_assignment -- equipment scheduling per job
    # -------------------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS constructclaw_equipment_assignment (
            id                  TEXT PRIMARY KEY,
            job_id              TEXT NOT NULL REFERENCES constructclaw_job(id) ON DELETE RESTRICT,
            equipment_name      TEXT NOT NULL,
            equipment_type      TEXT,
            start_date          TEXT NOT NULL,
            end_date            TEXT,
            daily_rate          TEXT DEFAULT '0',
            mobilization_cost   TEXT DEFAULT '0',
            demobilization_cost TEXT DEFAULT '0',
            actual_hours        TEXT DEFAULT '0',
            notes               TEXT,
            status              TEXT NOT NULL DEFAULT 'scheduled'
                                CHECK(status IN ('scheduled','active','completed','cancelled')),
            company_id          TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccea_job ON constructclaw_equipment_assignment(job_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccea_company ON constructclaw_equipment_assignment(company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccea_status ON constructclaw_equipment_assignment(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccea_dates ON constructclaw_equipment_assignment(start_date, end_date)")
    indexes_created += 4

    # -------------------------------------------------------------------
    # 29. constructclaw_prevailing_wage_rate -- Davis-Bacon prevailing wage rates
    # -------------------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS constructclaw_prevailing_wage_rate (
            id                          TEXT PRIMARY KEY,
            job_id                      TEXT NOT NULL REFERENCES constructclaw_job(id) ON DELETE RESTRICT,
            trade                       TEXT NOT NULL,
            classification              TEXT NOT NULL,
            basic_rate                  TEXT NOT NULL,
            fringe_rate                 TEXT NOT NULL DEFAULT '0',
            total_rate                  TEXT NOT NULL,
            overtime_rate               TEXT,
            wage_determination_number   TEXT,
            effective_date              TEXT,
            status                      TEXT DEFAULT 'active'
                                        CHECK(status IN ('active','expired')),
            company_id                  TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at                  TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccpwr_job ON constructclaw_prevailing_wage_rate(job_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccpwr_company ON constructclaw_prevailing_wage_rate(company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccpwr_trade ON constructclaw_prevailing_wage_rate(trade, classification)")
    indexes_created += 3

    # -------------------------------------------------------------------
    # 30. constructclaw_certified_payroll_entry -- WH-347 payroll entries
    # -------------------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS constructclaw_certified_payroll_entry (
            id                  TEXT PRIMARY KEY,
            job_id              TEXT NOT NULL REFERENCES constructclaw_job(id) ON DELETE RESTRICT,
            week_ending         TEXT NOT NULL,
            employee_name       TEXT NOT NULL,
            employee_id         TEXT,
            trade               TEXT NOT NULL,
            classification      TEXT NOT NULL,
            mon_hours           TEXT DEFAULT '0',
            tue_hours           TEXT DEFAULT '0',
            wed_hours           TEXT DEFAULT '0',
            thu_hours           TEXT DEFAULT '0',
            fri_hours           TEXT DEFAULT '0',
            sat_hours           TEXT DEFAULT '0',
            sun_hours           TEXT DEFAULT '0',
            total_hours         TEXT DEFAULT '0',
            overtime_hours      TEXT DEFAULT '0',
            hourly_rate         TEXT NOT NULL,
            gross_pay           TEXT NOT NULL,
            fica                TEXT DEFAULT '0',
            federal_tax         TEXT DEFAULT '0',
            state_tax           TEXT DEFAULT '0',
            other_deductions    TEXT DEFAULT '0',
            net_pay             TEXT NOT NULL,
            fringe_paid         TEXT DEFAULT '0',
            fringe_method       TEXT DEFAULT 'cash'
                                CHECK(fringe_method IN ('cash','plan')),
            company_id          TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cccpe_job ON constructclaw_certified_payroll_entry(job_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cccpe_company ON constructclaw_certified_payroll_entry(company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cccpe_week ON constructclaw_certified_payroll_entry(week_ending)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cccpe_employee ON constructclaw_certified_payroll_entry(employee_name)")
    indexes_created += 4

    # -------------------------------------------------------------------
    # 31. constructclaw_time_entry -- individual labor time tracking
    # -------------------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS constructclaw_time_entry (
            id                  TEXT PRIMARY KEY,
            job_id              TEXT NOT NULL REFERENCES constructclaw_job(id) ON DELETE RESTRICT,
            cost_code_id        TEXT,
            employee_name       TEXT NOT NULL,
            employee_id         TEXT,
            trade               TEXT,
            work_date           TEXT NOT NULL,
            regular_hours       TEXT DEFAULT '0',
            overtime_hours      TEXT DEFAULT '0',
            double_time_hours   TEXT DEFAULT '0',
            total_hours         TEXT DEFAULT '0',
            hourly_rate         TEXT DEFAULT '0',
            total_cost          TEXT DEFAULT '0',
            description         TEXT,
            approved_by         TEXT,
            approved_at         TEXT,
            status              TEXT DEFAULT 'draft'
                                CHECK(status IN ('draft','submitted','approved','rejected')),
            company_id          TEXT NOT NULL REFERENCES company(id) ON DELETE RESTRICT,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccte_job ON constructclaw_time_entry(job_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccte_company ON constructclaw_time_entry(company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccte_date ON constructclaw_time_entry(work_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccte_employee ON constructclaw_time_entry(employee_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ccte_status ON constructclaw_time_entry(status)")
    indexes_created += 5

    conn.commit()
    conn.close()

    return {
        "database": db_path,
        "tables": tables_created,
        "indexes": indexes_created,
    }


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else DB_PATH
    result = init_constructclaw_schema(path)
    print(f"ConstructClaw schema created in {result['database']}")
    print(f"  Tables: {result['tables']}")
    print(f"  Indexes: {result['indexes']}")
