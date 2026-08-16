"""ConstructClaw -- schema initialization.

Creates 36 tables for construction project management
in the shared ERPClaw database.
Requires company table to exist (erpclaw-setup).

ADR-0034 phase 2 bulk-39. The schema is declared as `erpclaw_lib` metadata and
provisioned through the seam, which emits dialect-correct DDL, replacing a
hand-written ``CREATE TABLE`` block opened with ``sqlite3.connect`` that could not
run on PostgreSQL at all. Money stays TEXT throughout (ADR-0034 dec. 1): contract
amounts, change orders, progress billing and retainage are all exact Decimal
strings, never Integer and never Numeric.

(The docstring said 31 tables before the conversion; the file has declared 36
since the permit/punch-list/bond/warranty/milestone block was added.)
"""
import importlib.util
import os
import sys

# Bootstrap the shared lib only when it is not already reachable -- an
# unconditional insert at position 0 overrides a caller that deliberately bound a
# different tree (ADR-0034 phase 2 step 2d).
if importlib.util.find_spec("erpclaw_lib") is None:
    sys.path.insert(0, os.path.join(os.path.expanduser(
        os.environ.get("ERPCLAW_HOME", "~/.openclaw/erpclaw")), "lib"))

from erpclaw_lib.seam import (  # noqa: E402
    CheckConstraint, Column, ForeignKey, Index, Integer, MetaData, Table, Text,
    now_default, provision, reference_table, text,
)

DB_PATH = os.environ.get(
    "ERPCLAW_DB_PATH",
    os.path.join(os.path.expanduser(os.environ.get("ERPCLAW_HOME", "~/.openclaw/erpclaw")), "data.sqlite"),
)

METADATA = MetaData()

# Foundation table this module points at but does not own -- declared so the
# foreign keys resolve, never created here.
reference_table("company", METADATA)


# -------------------------------------------------------------------
# 1. constructclaw_job -- construction jobs / projects
# -------------------------------------------------------------------
JOB = Table(
    "constructclaw_job", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("naming_series", Text),
    Column("job_number", Text),
    Column("name", Text, nullable=False),
    Column("description", Text),
    Column("client_name", Text),
    Column("client_id", Text),
    Column("project_manager", Text),
    Column("superintendent", Text),
    Column("job_type", Text, nullable=False, server_default=text("'general'")),
    Column("contract_type", Text, nullable=False, server_default=text("'lump_sum'")),
    Column("contract_amount", Text, nullable=False, server_default=text("'0'")),
    Column("start_date", Text),
    Column("end_date", Text),
    Column("actual_start_date", Text),
    Column("actual_end_date", Text),
    Column("address", Text),
    Column("city", Text),
    Column("state", Text),
    Column("zip_code", Text),
    Column("job_status", Text, nullable=False, server_default=text("'planning'")),
    Column("percent_complete", Text, server_default=text("'0'")),
    Column("notes", Text),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "job_type IN ('general','residential','commercial','industrial',"
        "'infrastructure','renovation','other')",
        name="ck_constructclaw_job_job_type"),
    CheckConstraint(
        "contract_type IN ('lump_sum','cost_plus','time_and_material',"
        "'unit_price','gmp','design_build')",
        name="ck_constructclaw_job_contract_type"),
    CheckConstraint(
        "job_status IN ('planning','bidding','awarded','active','on_hold',"
        "'substantially_complete','closed','cancelled')",
        name="ck_constructclaw_job_job_status"),
)

Index("idx_ccjob_company", JOB.c.company_id)
Index("idx_ccjob_status", JOB.c.job_status)
Index("idx_ccjob_type", JOB.c.job_type)
Index("idx_ccjob_number", JOB.c.job_number)


# -------------------------------------------------------------------
# 2. constructclaw_cost_code -- cost code master for WBS
# -------------------------------------------------------------------
COST_CODE = Table(
    "constructclaw_cost_code", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("job_id", Text,
           ForeignKey("constructclaw_job.id", ondelete="CASCADE"), nullable=False),
    Column("code", Text, nullable=False),
    Column("description", Text),
    Column("category", Text, nullable=False, server_default=text("'labor'")),
    Column("budget_amount", Text, nullable=False, server_default=text("'0'")),
    Column("budget_hours", Text, server_default=text("'0'")),
    Column("is_active", Integer, nullable=False, server_default=text("1")),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "category IN ('labor','material','equipment','subcontract','overhead',"
        "'other')",
        name="ck_constructclaw_cost_code_category"),
    CheckConstraint("is_active IN (0,1)",
                    name="ck_constructclaw_cost_code_is_active"),
)

Index("idx_cccc_job", COST_CODE.c.job_id)
Index("idx_cccc_code", COST_CODE.c.code)
Index("idx_cccc_company", COST_CODE.c.company_id)
# Idempotency key: one cost code per job. Unique, not a plain lookup index.
Index("idx_cccc_job_code", COST_CODE.c.job_id, COST_CODE.c.code, unique=True)


# -------------------------------------------------------------------
# 3. constructclaw_cost_entry -- actual cost transactions
# -------------------------------------------------------------------
COST_ENTRY = Table(
    "constructclaw_cost_entry", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("job_id", Text,
           ForeignKey("constructclaw_job.id", ondelete="RESTRICT"), nullable=False),
    Column("cost_code_id", Text,
           ForeignKey("constructclaw_cost_code.id", ondelete="SET NULL")),
    Column("entry_date", Text, nullable=False, server_default=text("CURRENT_DATE")),
    Column("category", Text, nullable=False, server_default=text("'labor'")),
    Column("description", Text),
    Column("vendor", Text),
    Column("reference", Text),
    Column("quantity", Text, server_default=text("'0'")),
    Column("unit_cost", Text, server_default=text("'0'")),
    Column("amount", Text, nullable=False, server_default=text("'0'")),
    Column("hours", Text, server_default=text("'0'")),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "category IN ('labor','material','equipment','subcontract','overhead',"
        "'other')",
        name="ck_constructclaw_cost_entry_category"),
)

Index("idx_ccce_job", COST_ENTRY.c.job_id)
Index("idx_ccce_code", COST_ENTRY.c.cost_code_id)
Index("idx_ccce_date", COST_ENTRY.c.entry_date)
Index("idx_ccce_company", COST_ENTRY.c.company_id)


# -------------------------------------------------------------------
# 4. constructclaw_commitment -- purchase commitments (POs, subcontracts)
# -------------------------------------------------------------------
COMMITMENT = Table(
    "constructclaw_commitment", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("job_id", Text,
           ForeignKey("constructclaw_job.id", ondelete="RESTRICT"), nullable=False),
    Column("cost_code_id", Text,
           ForeignKey("constructclaw_cost_code.id", ondelete="SET NULL")),
    Column("commitment_type", Text, nullable=False,
           server_default=text("'purchase_order'")),
    Column("vendor", Text),
    Column("description", Text),
    Column("original_amount", Text, nullable=False, server_default=text("'0'")),
    Column("revised_amount", Text, nullable=False, server_default=text("'0'")),
    Column("invoiced_amount", Text, nullable=False, server_default=text("'0'")),
    Column("paid_amount", Text, nullable=False, server_default=text("'0'")),
    Column("commitment_status", Text, nullable=False, server_default=text("'draft'")),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "commitment_type IN ('purchase_order','subcontract','change_order',"
        "'other')",
        name="ck_constructclaw_commitment_commitment_type"),
    CheckConstraint(
        "commitment_status IN ('draft','approved','open','closed','cancelled')",
        name="ck_constructclaw_commitment_commitment_status"),
)

Index("idx_cccm_job", COMMITMENT.c.job_id)
Index("idx_cccm_company", COMMITMENT.c.company_id)
Index("idx_cccm_status", COMMITMENT.c.commitment_status)


# -------------------------------------------------------------------
# 5. constructclaw_estimate -- project estimates / bids
# -------------------------------------------------------------------
ESTIMATE = Table(
    "constructclaw_estimate", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("naming_series", Text),
    Column("job_id", Text,
           ForeignKey("constructclaw_job.id", ondelete="SET NULL")),
    Column("estimate_number", Text),
    Column("name", Text, nullable=False),
    Column("client_name", Text),
    Column("description", Text),
    Column("estimate_date", Text, nullable=False,
           server_default=text("CURRENT_DATE")),
    Column("due_date", Text),
    Column("total_amount", Text, nullable=False, server_default=text("'0'")),
    Column("markup_pct", Text, server_default=text("'0'")),
    Column("overhead_pct", Text, server_default=text("'0'")),
    Column("profit_pct", Text, server_default=text("'0'")),
    Column("estimate_status", Text, nullable=False, server_default=text("'draft'")),
    Column("notes", Text),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "estimate_status IN ('draft','submitted','won','lost','revised',"
        "'cancelled')",
        name="ck_constructclaw_estimate_estimate_status"),
)

Index("idx_ccest_company", ESTIMATE.c.company_id)
Index("idx_ccest_status", ESTIMATE.c.estimate_status)
Index("idx_ccest_job", ESTIMATE.c.job_id)


# -------------------------------------------------------------------
# 6. constructclaw_estimate_line -- line items within an estimate
# -------------------------------------------------------------------
ESTIMATE_LINE = Table(
    "constructclaw_estimate_line", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("estimate_id", Text,
           ForeignKey("constructclaw_estimate.id", ondelete="CASCADE"),
           nullable=False),
    Column("line_number", Integer, nullable=False, server_default=text("0")),
    Column("description", Text, nullable=False),
    Column("category", Text, nullable=False, server_default=text("'labor'")),
    Column("quantity", Text, nullable=False, server_default=text("'0'")),
    Column("unit", Text, server_default=text("'ea'")),
    Column("unit_cost", Text, nullable=False, server_default=text("'0'")),
    Column("amount", Text, nullable=False, server_default=text("'0'")),
    Column("notes", Text),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "category IN ('labor','material','equipment','subcontract','overhead',"
        "'other')",
        name="ck_constructclaw_estimate_line_category"),
)

Index("idx_ccel_estimate", ESTIMATE_LINE.c.estimate_id)
Index("idx_ccel_company", ESTIMATE_LINE.c.company_id)


# -------------------------------------------------------------------
# 7. constructclaw_bid -- bid submissions
# -------------------------------------------------------------------
BID = Table(
    "constructclaw_bid", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("naming_series", Text),
    Column("estimate_id", Text,
           ForeignKey("constructclaw_estimate.id", ondelete="SET NULL")),
    Column("job_id", Text,
           ForeignKey("constructclaw_job.id", ondelete="SET NULL")),
    Column("bid_number", Text),
    Column("bidder_name", Text, nullable=False),
    Column("bid_amount", Text, nullable=False, server_default=text("'0'")),
    Column("bid_date", Text, nullable=False, server_default=text("CURRENT_DATE")),
    Column("scope_description", Text),
    Column("exclusions", Text),
    Column("bid_status", Text, nullable=False, server_default=text("'submitted'")),
    Column("notes", Text),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "bid_status IN ('submitted','under_review','awarded','rejected',"
        "'withdrawn')",
        name="ck_constructclaw_bid_bid_status"),
)

Index("idx_ccbid_company", BID.c.company_id)
Index("idx_ccbid_estimate", BID.c.estimate_id)
Index("idx_ccbid_status", BID.c.bid_status)


# -------------------------------------------------------------------
# 8. constructclaw_subcontract -- subcontractor agreements
# -------------------------------------------------------------------
SUBCONTRACT = Table(
    "constructclaw_subcontract", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("naming_series", Text),
    Column("job_id", Text,
           ForeignKey("constructclaw_job.id", ondelete="RESTRICT"), nullable=False),
    Column("subcontract_number", Text),
    Column("subcontractor_name", Text, nullable=False),
    Column("trade", Text),
    Column("scope_of_work", Text),
    Column("original_amount", Text, nullable=False, server_default=text("'0'")),
    Column("revised_amount", Text, nullable=False, server_default=text("'0'")),
    Column("retention_pct", Text, server_default=text("'10'")),
    Column("insurance_expiry", Text),
    Column("license_number", Text),
    Column("start_date", Text),
    Column("end_date", Text),
    Column("subcontract_status", Text, nullable=False, server_default=text("'draft'")),
    Column("notes", Text),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "subcontract_status IN ('draft','pending_approval','approved','active',"
        "'on_hold','complete','terminated','cancelled')",
        name="ck_constructclaw_subcontract_subcontract_status"),
)

Index("idx_ccsub_company", SUBCONTRACT.c.company_id)
Index("idx_ccsub_job", SUBCONTRACT.c.job_id)
Index("idx_ccsub_status", SUBCONTRACT.c.subcontract_status)


# -------------------------------------------------------------------
# 9. constructclaw_subcontract_line -- line items within a subcontract
# -------------------------------------------------------------------
SUBCONTRACT_LINE = Table(
    "constructclaw_subcontract_line", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("subcontract_id", Text,
           ForeignKey("constructclaw_subcontract.id", ondelete="CASCADE"),
           nullable=False),
    Column("line_number", Integer, nullable=False, server_default=text("0")),
    Column("description", Text, nullable=False),
    Column("quantity", Text, nullable=False, server_default=text("'0'")),
    Column("unit", Text, server_default=text("'ls'")),
    Column("unit_cost", Text, nullable=False, server_default=text("'0'")),
    Column("amount", Text, nullable=False, server_default=text("'0'")),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
)

Index("idx_ccsl_sub", SUBCONTRACT_LINE.c.subcontract_id)
Index("idx_ccsl_company", SUBCONTRACT_LINE.c.company_id)


# -------------------------------------------------------------------
# 10. constructclaw_pay_application -- subcontractor pay apps
# -------------------------------------------------------------------
PAY_APPLICATION = Table(
    "constructclaw_pay_application", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("naming_series", Text),
    Column("subcontract_id", Text,
           ForeignKey("constructclaw_subcontract.id", ondelete="RESTRICT"),
           nullable=False),
    Column("application_number", Integer, nullable=False, server_default=text("1")),
    Column("period_from", Text),
    Column("period_to", Text),
    Column("work_completed", Text, nullable=False, server_default=text("'0'")),
    Column("materials_stored", Text, nullable=False, server_default=text("'0'")),
    Column("total_earned", Text, nullable=False, server_default=text("'0'")),
    Column("retention_held", Text, nullable=False, server_default=text("'0'")),
    Column("previous_payments", Text, nullable=False, server_default=text("'0'")),
    Column("current_payment_due", Text, nullable=False, server_default=text("'0'")),
    Column("pay_app_status", Text, nullable=False, server_default=text("'draft'")),
    Column("notes", Text),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "pay_app_status IN ('draft','submitted','approved','rejected','paid')",
        name="ck_constructclaw_pay_application_pay_app_status"),
)

Index("idx_ccpa_sub", PAY_APPLICATION.c.subcontract_id)
Index("idx_ccpa_company", PAY_APPLICATION.c.company_id)
Index("idx_ccpa_status", PAY_APPLICATION.c.pay_app_status)


# -------------------------------------------------------------------
# 11. constructclaw_lien_waiver -- lien waiver tracking
# -------------------------------------------------------------------
LIEN_WAIVER = Table(
    "constructclaw_lien_waiver", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("subcontract_id", Text,
           ForeignKey("constructclaw_subcontract.id", ondelete="RESTRICT"),
           nullable=False),
    Column("pay_application_id", Text,
           ForeignKey("constructclaw_pay_application.id", ondelete="SET NULL")),
    Column("waiver_type", Text, nullable=False,
           server_default=text("'conditional_progress'")),
    Column("amount", Text, nullable=False, server_default=text("'0'")),
    Column("through_date", Text),
    Column("received_date", Text),
    Column("waiver_status", Text, nullable=False, server_default=text("'pending'")),
    Column("notes", Text),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "waiver_type IN ('conditional_progress','unconditional_progress',"
        "'conditional_final','unconditional_final')",
        name="ck_constructclaw_lien_waiver_waiver_type"),
    CheckConstraint("waiver_status IN ('pending','received','verified')",
                    name="ck_constructclaw_lien_waiver_waiver_status"),
)

Index("idx_cclw_sub", LIEN_WAIVER.c.subcontract_id)
Index("idx_cclw_company", LIEN_WAIVER.c.company_id)


# -------------------------------------------------------------------
# 12. constructclaw_schedule_of_values -- SOV header (AIA G702/G703)
# -------------------------------------------------------------------
SCHEDULE_OF_VALUES = Table(
    "constructclaw_schedule_of_values", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("naming_series", Text),
    Column("job_id", Text,
           ForeignKey("constructclaw_job.id", ondelete="RESTRICT"), nullable=False),
    Column("sov_number", Text),
    Column("name", Text, nullable=False),
    Column("total_contract", Text, nullable=False, server_default=text("'0'")),
    Column("total_change_orders", Text, nullable=False, server_default=text("'0'")),
    Column("revised_contract", Text, nullable=False, server_default=text("'0'")),
    Column("sov_status", Text, nullable=False, server_default=text("'draft'")),
    Column("notes", Text),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint("sov_status IN ('draft','approved','active','closed')",
                    name="ck_constructclaw_schedule_of_values_sov_status"),
)

Index("idx_ccsov_job", SCHEDULE_OF_VALUES.c.job_id)
Index("idx_ccsov_company", SCHEDULE_OF_VALUES.c.company_id)


# -------------------------------------------------------------------
# 13. constructclaw_sov_line -- SOV line items
# -------------------------------------------------------------------
SOV_LINE = Table(
    "constructclaw_sov_line", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("sov_id", Text,
           ForeignKey("constructclaw_schedule_of_values.id", ondelete="CASCADE"),
           nullable=False),
    Column("item_number", Text, nullable=False),
    Column("description", Text, nullable=False),
    Column("scheduled_value", Text, nullable=False, server_default=text("'0'")),
    Column("previous_completed", Text, nullable=False, server_default=text("'0'")),
    Column("this_period", Text, nullable=False, server_default=text("'0'")),
    Column("materials_stored", Text, nullable=False, server_default=text("'0'")),
    Column("total_completed", Text, nullable=False, server_default=text("'0'")),
    Column("pct_complete", Text, server_default=text("'0'")),
    Column("balance_to_finish", Text, nullable=False, server_default=text("'0'")),
    Column("retention_pct", Text, server_default=text("'10'")),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
)

Index("idx_ccsvl_sov", SOV_LINE.c.sov_id)
Index("idx_ccsvl_company", SOV_LINE.c.company_id)


# -------------------------------------------------------------------
# 14. constructclaw_progress_bill -- AIA G702 pay application header
# -------------------------------------------------------------------
PROGRESS_BILL = Table(
    "constructclaw_progress_bill", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("naming_series", Text),
    Column("job_id", Text,
           ForeignKey("constructclaw_job.id", ondelete="RESTRICT"), nullable=False),
    Column("sov_id", Text,
           ForeignKey("constructclaw_schedule_of_values.id", ondelete="SET NULL")),
    Column("bill_number", Integer, nullable=False, server_default=text("1")),
    Column("period_from", Text),
    Column("period_to", Text),
    Column("total_completed", Text, nullable=False, server_default=text("'0'")),
    Column("total_retention", Text, nullable=False, server_default=text("'0'")),
    Column("total_previous", Text, nullable=False, server_default=text("'0'")),
    Column("current_due", Text, nullable=False, server_default=text("'0'")),
    Column("bill_status", Text, nullable=False, server_default=text("'draft'")),
    # No foreign key: the shipped DDL leaves this a bare TEXT pointer into the
    # core ledger. Preserved as-is (rule 12) rather than tightened in passing.
    Column("sales_invoice_id", Text),
    Column("notes", Text),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "bill_status IN ('draft','submitted','approved','paid','rejected')",
        name="ck_constructclaw_progress_bill_bill_status"),
)

Index("idx_ccpb_job", PROGRESS_BILL.c.job_id)
Index("idx_ccpb_sov", PROGRESS_BILL.c.sov_id)
Index("idx_ccpb_company", PROGRESS_BILL.c.company_id)
Index("idx_ccpb_status", PROGRESS_BILL.c.bill_status)


# -------------------------------------------------------------------
# 15. constructclaw_progress_bill_line -- AIA G703 line items per bill
# -------------------------------------------------------------------
PROGRESS_BILL_LINE = Table(
    "constructclaw_progress_bill_line", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("bill_id", Text,
           ForeignKey("constructclaw_progress_bill.id", ondelete="CASCADE"),
           nullable=False),
    Column("sov_line_id", Text,
           ForeignKey("constructclaw_sov_line.id", ondelete="SET NULL")),
    Column("item_number", Text),
    Column("description", Text, nullable=False),
    Column("scheduled_value", Text, nullable=False, server_default=text("'0'")),
    Column("previous_completed", Text, nullable=False, server_default=text("'0'")),
    Column("this_period", Text, nullable=False, server_default=text("'0'")),
    Column("materials_stored", Text, nullable=False, server_default=text("'0'")),
    Column("total_completed", Text, nullable=False, server_default=text("'0'")),
    Column("pct_complete", Text, server_default=text("'0'")),
    Column("balance_to_finish", Text, nullable=False, server_default=text("'0'")),
    Column("retention_amount", Text, nullable=False, server_default=text("'0'")),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
)

Index("idx_ccpbl_bill", PROGRESS_BILL_LINE.c.bill_id)
Index("idx_ccpbl_company", PROGRESS_BILL_LINE.c.company_id)


# -------------------------------------------------------------------
# 16. constructclaw_retention -- retention tracking
# -------------------------------------------------------------------
RETENTION = Table(
    "constructclaw_retention", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("job_id", Text,
           ForeignKey("constructclaw_job.id", ondelete="RESTRICT"), nullable=False),
    Column("subcontract_id", Text,
           ForeignKey("constructclaw_subcontract.id", ondelete="SET NULL")),
    Column("retention_type", Text, nullable=False, server_default=text("'owner'")),
    Column("amount_held", Text, nullable=False, server_default=text("'0'")),
    Column("amount_released", Text, nullable=False, server_default=text("'0'")),
    Column("balance", Text, nullable=False, server_default=text("'0'")),
    Column("release_date", Text),
    Column("retention_status", Text, nullable=False, server_default=text("'held'")),
    Column("notes", Text),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint("retention_type IN ('owner','subcontractor')",
                    name="ck_constructclaw_retention_retention_type"),
    CheckConstraint(
        "retention_status IN ('held','partial_release','released')",
        name="ck_constructclaw_retention_retention_status"),
)

Index("idx_ccret_job", RETENTION.c.job_id)
Index("idx_ccret_company", RETENTION.c.company_id)
Index("idx_ccret_status", RETENTION.c.retention_status)


# -------------------------------------------------------------------
# 17. constructclaw_daily_report -- daily field reports
# -------------------------------------------------------------------
DAILY_REPORT = Table(
    "constructclaw_daily_report", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("naming_series", Text),
    Column("job_id", Text,
           ForeignKey("constructclaw_job.id", ondelete="RESTRICT"), nullable=False),
    Column("report_date", Text, nullable=False, server_default=text("CURRENT_DATE")),
    Column("superintendent", Text),
    Column("weather", Text),
    Column("temperature_high", Text),
    Column("temperature_low", Text),
    Column("work_description", Text),
    Column("delays", Text),
    Column("visitors", Text),
    Column("report_status", Text, nullable=False, server_default=text("'draft'")),
    Column("notes", Text),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint("report_status IN ('draft','submitted','approved')",
                    name="ck_constructclaw_daily_report_report_status"),
)

Index("idx_ccdr_job", DAILY_REPORT.c.job_id)
Index("idx_ccdr_date", DAILY_REPORT.c.report_date)
Index("idx_ccdr_company", DAILY_REPORT.c.company_id)


# -------------------------------------------------------------------
# 18. constructclaw_daily_labor -- labor entries for daily reports
# -------------------------------------------------------------------
DAILY_LABOR = Table(
    "constructclaw_daily_labor", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("daily_report_id", Text,
           ForeignKey("constructclaw_daily_report.id", ondelete="CASCADE"),
           nullable=False),
    Column("trade", Text, nullable=False),
    Column("headcount", Integer, nullable=False, server_default=text("0")),
    Column("hours", Text, nullable=False, server_default=text("'0'")),
    Column("description", Text),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
)

Index("idx_ccdl_report", DAILY_LABOR.c.daily_report_id)
Index("idx_ccdl_company", DAILY_LABOR.c.company_id)


# -------------------------------------------------------------------
# 19. constructclaw_daily_material -- material deliveries for daily reports
# -------------------------------------------------------------------
DAILY_MATERIAL = Table(
    "constructclaw_daily_material", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("daily_report_id", Text,
           ForeignKey("constructclaw_daily_report.id", ondelete="CASCADE"),
           nullable=False),
    Column("material_name", Text, nullable=False),
    Column("quantity", Text, nullable=False, server_default=text("'0'")),
    Column("unit", Text, server_default=text("'ea'")),
    Column("supplier", Text),
    Column("delivery_ticket", Text),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
)

Index("idx_ccdm_report", DAILY_MATERIAL.c.daily_report_id)
Index("idx_ccdm_company", DAILY_MATERIAL.c.company_id)


# -------------------------------------------------------------------
# 20. constructclaw_pco -- potential change order
# -------------------------------------------------------------------
PCO = Table(
    "constructclaw_pco", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("naming_series", Text),
    Column("job_id", Text,
           ForeignKey("constructclaw_job.id", ondelete="RESTRICT"), nullable=False),
    Column("pco_number", Text),
    Column("title", Text, nullable=False),
    Column("description", Text),
    Column("reason", Text),
    Column("cost_impact", Text, nullable=False, server_default=text("'0'")),
    Column("time_impact_days", Integer, server_default=text("0")),
    Column("requested_by", Text),
    Column("pco_status", Text, nullable=False, server_default=text("'identified'")),
    Column("notes", Text),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "pco_status IN ('identified','pricing','submitted','approved','rejected',"
        "'void')",
        name="ck_constructclaw_pco_pco_status"),
)

Index("idx_ccpco_job", PCO.c.job_id)
Index("idx_ccpco_company", PCO.c.company_id)
Index("idx_ccpco_status", PCO.c.pco_status)


# -------------------------------------------------------------------
# 21. constructclaw_cco -- contract change order (approved change)
# -------------------------------------------------------------------
CCO = Table(
    "constructclaw_cco", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("naming_series", Text),
    Column("job_id", Text,
           ForeignKey("constructclaw_job.id", ondelete="RESTRICT"), nullable=False),
    Column("pco_id", Text,
           ForeignKey("constructclaw_pco.id", ondelete="SET NULL")),
    Column("cco_number", Text),
    Column("title", Text, nullable=False),
    Column("description", Text),
    Column("cost_change", Text, nullable=False, server_default=text("'0'")),
    Column("time_change_days", Integer, server_default=text("0")),
    Column("new_contract_amount", Text, server_default=text("'0'")),
    Column("cco_status", Text, nullable=False, server_default=text("'draft'")),
    Column("approved_by", Text),
    Column("approved_date", Text),
    Column("notes", Text),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "cco_status IN ('draft','pending','approved','executed','rejected',"
        "'void')",
        name="ck_constructclaw_cco_cco_status"),
)

Index("idx_cccco_job", CCO.c.job_id)
Index("idx_cccco_company", CCO.c.company_id)
Index("idx_cccco_pco", CCO.c.pco_id)
Index("idx_cccco_status", CCO.c.cco_status)


# -------------------------------------------------------------------
# 22. constructclaw_rfi -- request for information
# -------------------------------------------------------------------
RFI = Table(
    "constructclaw_rfi", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("naming_series", Text),
    Column("job_id", Text,
           ForeignKey("constructclaw_job.id", ondelete="RESTRICT"), nullable=False),
    Column("rfi_number", Text),
    Column("subject", Text, nullable=False),
    Column("question", Text, nullable=False),
    Column("response", Text),
    Column("initiated_by", Text),
    Column("assigned_to", Text),
    Column("priority", Text, nullable=False, server_default=text("'normal'")),
    Column("date_sent", Text, nullable=False, server_default=text("CURRENT_DATE")),
    Column("date_required", Text),
    Column("date_responded", Text),
    Column("cost_impact", Text, server_default=text("'0'")),
    Column("schedule_impact_days", Integer, server_default=text("0")),
    Column("rfi_status", Text, nullable=False, server_default=text("'open'")),
    Column("notes", Text),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint("priority IN ('critical','high','normal','low')",
                    name="ck_constructclaw_rfi_priority"),
    CheckConstraint("rfi_status IN ('open','responded','closed','void')",
                    name="ck_constructclaw_rfi_rfi_status"),
)

Index("idx_ccrfi_job", RFI.c.job_id)
Index("idx_ccrfi_company", RFI.c.company_id)
Index("idx_ccrfi_status", RFI.c.rfi_status)


# -------------------------------------------------------------------
# 23. constructclaw_submittal -- submittal tracking
# -------------------------------------------------------------------
SUBMITTAL = Table(
    "constructclaw_submittal", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("naming_series", Text),
    Column("job_id", Text,
           ForeignKey("constructclaw_job.id", ondelete="RESTRICT"), nullable=False),
    Column("submittal_number", Text),
    Column("spec_section", Text),
    Column("title", Text, nullable=False),
    Column("description", Text),
    Column("submitted_by", Text),
    Column("submitted_to", Text),
    Column("date_submitted", Text, nullable=False,
           server_default=text("CURRENT_DATE")),
    Column("date_required", Text),
    Column("date_returned", Text),
    Column("submittal_status", Text, nullable=False, server_default=text("'pending'")),
    Column("review_comments", Text),
    Column("notes", Text),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "submittal_status IN ('pending','under_review','approved',"
        "'approved_as_noted','revise_resubmit','rejected')",
        name="ck_constructclaw_submittal_submittal_status"),
)

Index("idx_ccsubm_job", SUBMITTAL.c.job_id)
Index("idx_ccsubm_company", SUBMITTAL.c.company_id)
Index("idx_ccsubm_status", SUBMITTAL.c.submittal_status)


# -------------------------------------------------------------------
# 24. constructclaw_incident -- safety incidents
# -------------------------------------------------------------------
INCIDENT = Table(
    "constructclaw_incident", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("naming_series", Text),
    Column("job_id", Text,
           ForeignKey("constructclaw_job.id", ondelete="RESTRICT"), nullable=False),
    Column("incident_number", Text),
    Column("incident_date", Text, nullable=False,
           server_default=text("CURRENT_DATE")),
    Column("incident_time", Text),
    Column("incident_type", Text, nullable=False, server_default=text("'near_miss'")),
    Column("severity", Text, nullable=False, server_default=text("'minor'")),
    Column("location", Text),
    Column("description", Text, nullable=False),
    Column("injured_party", Text),
    Column("witnesses", Text),
    Column("root_cause", Text),
    Column("corrective_action", Text),
    Column("osha_recordable", Integer, nullable=False, server_default=text("0")),
    Column("days_lost", Integer, server_default=text("0")),
    Column("incident_status", Text, nullable=False, server_default=text("'open'")),
    Column("notes", Text),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "incident_type IN ('near_miss','first_aid','recordable','lost_time',"
        "'fatality','property_damage','environmental','other')",
        name="ck_constructclaw_incident_incident_type"),
    CheckConstraint(
        "severity IN ('minor','moderate','serious','critical','fatal')",
        name="ck_constructclaw_incident_severity"),
    CheckConstraint("osha_recordable IN (0,1)",
                    name="ck_constructclaw_incident_osha_recordable"),
    CheckConstraint(
        "incident_status IN ('open','investigating','corrective_action','closed')",
        name="ck_constructclaw_incident_incident_status"),
)

Index("idx_ccinc_job", INCIDENT.c.job_id)
Index("idx_ccinc_company", INCIDENT.c.company_id)
Index("idx_ccinc_type", INCIDENT.c.incident_type)
Index("idx_ccinc_status", INCIDENT.c.incident_status)
Index("idx_ccinc_date", INCIDENT.c.incident_date)


# -------------------------------------------------------------------
# 25. constructclaw_toolbox_talk -- safety meetings
# -------------------------------------------------------------------
TOOLBOX_TALK = Table(
    "constructclaw_toolbox_talk", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("job_id", Text,
           ForeignKey("constructclaw_job.id", ondelete="RESTRICT"), nullable=False),
    Column("talk_date", Text, nullable=False, server_default=text("CURRENT_DATE")),
    Column("topic", Text, nullable=False),
    Column("presenter", Text),
    Column("attendee_count", Integer, nullable=False, server_default=text("0")),
    Column("attendees", Text),
    Column("duration_minutes", Integer, server_default=text("0")),
    Column("notes", Text),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
)

Index("idx_cctt_job", TOOLBOX_TALK.c.job_id)
Index("idx_cctt_company", TOOLBOX_TALK.c.company_id)
Index("idx_cctt_date", TOOLBOX_TALK.c.talk_date)


# -------------------------------------------------------------------
# 26. constructclaw_safety_cert -- safety certifications for workers
# -------------------------------------------------------------------
SAFETY_CERT = Table(
    "constructclaw_safety_cert", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("job_id", Text,
           ForeignKey("constructclaw_job.id", ondelete="SET NULL")),
    Column("worker_name", Text, nullable=False),
    Column("cert_type", Text, nullable=False),
    Column("cert_number", Text),
    Column("issued_date", Text),
    Column("expiry_date", Text),
    Column("issuing_authority", Text),
    Column("cert_status", Text, nullable=False, server_default=text("'active'")),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "cert_status IN ('active','expiring_soon','expired','revoked')",
        name="ck_constructclaw_safety_cert_cert_status"),
)

Index("idx_ccsc_company", SAFETY_CERT.c.company_id)
Index("idx_ccsc_worker", SAFETY_CERT.c.worker_name)
Index("idx_ccsc_expiry", SAFETY_CERT.c.expiry_date)
Index("idx_ccsc_status", SAFETY_CERT.c.cert_status)


# -------------------------------------------------------------------
# 27. constructclaw_earned_value -- earned value management data points
# -------------------------------------------------------------------
EARNED_VALUE = Table(
    "constructclaw_earned_value", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("job_id", Text,
           ForeignKey("constructclaw_job.id", ondelete="RESTRICT"), nullable=False),
    Column("period_date", Text, nullable=False, server_default=text("CURRENT_DATE")),
    Column("planned_value", Text, nullable=False, server_default=text("'0'")),
    Column("earned_value", Text, nullable=False, server_default=text("'0'")),
    Column("actual_cost", Text, nullable=False, server_default=text("'0'")),
    Column("budget_at_completion", Text, nullable=False, server_default=text("'0'")),
    Column("notes", Text),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
)

Index("idx_ccev_job", EARNED_VALUE.c.job_id)
Index("idx_ccev_company", EARNED_VALUE.c.company_id)
Index("idx_ccev_date", EARNED_VALUE.c.period_date)


# -------------------------------------------------------------------
# 28. constructclaw_equipment_assignment -- equipment scheduling per job
# -------------------------------------------------------------------
EQUIPMENT_ASSIGNMENT = Table(
    "constructclaw_equipment_assignment", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("job_id", Text,
           ForeignKey("constructclaw_job.id", ondelete="RESTRICT"), nullable=False),
    Column("equipment_name", Text, nullable=False),
    Column("equipment_type", Text),
    Column("start_date", Text, nullable=False),
    Column("end_date", Text),
    Column("daily_rate", Text, server_default=text("'0'")),
    Column("mobilization_cost", Text, server_default=text("'0'")),
    Column("demobilization_cost", Text, server_default=text("'0'")),
    Column("actual_hours", Text, server_default=text("'0'")),
    Column("notes", Text),
    Column("status", Text, nullable=False, server_default=text("'scheduled'")),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "status IN ('scheduled','active','completed','cancelled')",
        name="ck_constructclaw_equipment_assignment_status"),
)

Index("idx_ccea_job", EQUIPMENT_ASSIGNMENT.c.job_id)
Index("idx_ccea_company", EQUIPMENT_ASSIGNMENT.c.company_id)
Index("idx_ccea_status", EQUIPMENT_ASSIGNMENT.c.status)
Index("idx_ccea_dates", EQUIPMENT_ASSIGNMENT.c.start_date,
      EQUIPMENT_ASSIGNMENT.c.end_date)


# -------------------------------------------------------------------
# 29. constructclaw_prevailing_wage_rate -- Davis-Bacon prevailing wage rates
# -------------------------------------------------------------------
PREVAILING_WAGE_RATE = Table(
    "constructclaw_prevailing_wage_rate", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("job_id", Text,
           ForeignKey("constructclaw_job.id", ondelete="RESTRICT"), nullable=False),
    Column("trade", Text, nullable=False),
    Column("classification", Text, nullable=False),
    # Rates are money: TEXT, no default -- the shipped DDL requires a value.
    Column("basic_rate", Text, nullable=False),
    Column("fringe_rate", Text, nullable=False, server_default=text("'0'")),
    Column("total_rate", Text, nullable=False),
    Column("overtime_rate", Text),
    Column("wage_determination_number", Text),
    Column("effective_date", Text),
    Column("status", Text, server_default=text("'active'")),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint("status IN ('active','expired')",
                    name="ck_constructclaw_prevailing_wage_rate_status"),
)

Index("idx_ccpwr_job", PREVAILING_WAGE_RATE.c.job_id)
Index("idx_ccpwr_company", PREVAILING_WAGE_RATE.c.company_id)
Index("idx_ccpwr_trade", PREVAILING_WAGE_RATE.c.trade,
      PREVAILING_WAGE_RATE.c.classification)


# -------------------------------------------------------------------
# 30. constructclaw_certified_payroll_entry -- WH-347 payroll entries
# -------------------------------------------------------------------
CERTIFIED_PAYROLL_ENTRY = Table(
    "constructclaw_certified_payroll_entry", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("job_id", Text,
           ForeignKey("constructclaw_job.id", ondelete="RESTRICT"), nullable=False),
    Column("week_ending", Text, nullable=False),
    Column("employee_name", Text, nullable=False),
    Column("employee_id", Text),
    Column("trade", Text, nullable=False),
    Column("classification", Text, nullable=False),
    Column("mon_hours", Text, server_default=text("'0'")),
    Column("tue_hours", Text, server_default=text("'0'")),
    Column("wed_hours", Text, server_default=text("'0'")),
    Column("thu_hours", Text, server_default=text("'0'")),
    Column("fri_hours", Text, server_default=text("'0'")),
    Column("sat_hours", Text, server_default=text("'0'")),
    Column("sun_hours", Text, server_default=text("'0'")),
    Column("total_hours", Text, server_default=text("'0'")),
    Column("overtime_hours", Text, server_default=text("'0'")),
    Column("hourly_rate", Text, nullable=False),
    Column("gross_pay", Text, nullable=False),
    Column("fica", Text, server_default=text("'0'")),
    Column("federal_tax", Text, server_default=text("'0'")),
    Column("state_tax", Text, server_default=text("'0'")),
    Column("other_deductions", Text, server_default=text("'0'")),
    Column("net_pay", Text, nullable=False),
    Column("fringe_paid", Text, server_default=text("'0'")),
    Column("fringe_method", Text, server_default=text("'cash'")),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint("fringe_method IN ('cash','plan')",
                    name="ck_constructclaw_certified_payroll_entry_fringe_method"),
)

Index("idx_cccpe_job", CERTIFIED_PAYROLL_ENTRY.c.job_id)
Index("idx_cccpe_company", CERTIFIED_PAYROLL_ENTRY.c.company_id)
Index("idx_cccpe_week", CERTIFIED_PAYROLL_ENTRY.c.week_ending)
Index("idx_cccpe_employee", CERTIFIED_PAYROLL_ENTRY.c.employee_name)


# -------------------------------------------------------------------
# 31. constructclaw_time_entry -- individual labor time tracking
# -------------------------------------------------------------------
TIME_ENTRY = Table(
    "constructclaw_time_entry", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("job_id", Text,
           ForeignKey("constructclaw_job.id", ondelete="RESTRICT"), nullable=False),
    # No foreign key here, unlike cost_entry and commitment. The asymmetry is in
    # the shipped DDL and is preserved rather than tidied (rule 12).
    Column("cost_code_id", Text),
    Column("employee_name", Text, nullable=False),
    Column("employee_id", Text),
    Column("trade", Text),
    Column("work_date", Text, nullable=False),
    Column("regular_hours", Text, server_default=text("'0'")),
    Column("overtime_hours", Text, server_default=text("'0'")),
    Column("double_time_hours", Text, server_default=text("'0'")),
    Column("total_hours", Text, server_default=text("'0'")),
    Column("hourly_rate", Text, server_default=text("'0'")),
    Column("total_cost", Text, server_default=text("'0'")),
    Column("description", Text),
    Column("approved_by", Text),
    Column("approved_at", Text),
    Column("status", Text, server_default=text("'draft'")),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint("status IN ('draft','submitted','approved','rejected')",
                    name="ck_constructclaw_time_entry_status"),
)

Index("idx_ccte_job", TIME_ENTRY.c.job_id)
Index("idx_ccte_company", TIME_ENTRY.c.company_id)
Index("idx_ccte_date", TIME_ENTRY.c.work_date)
Index("idx_ccte_employee", TIME_ENTRY.c.employee_name)
Index("idx_ccte_status", TIME_ENTRY.c.status)


# -------------------------------------------------------------------
# 32. constructclaw_permit -- building permits & inspections
# -------------------------------------------------------------------
PERMIT = Table(
    "constructclaw_permit", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("job_id", Text,
           ForeignKey("constructclaw_job.id", ondelete="RESTRICT"), nullable=False),
    Column("permit_type", Text, nullable=False),
    Column("permit_number", Text),
    Column("jurisdiction", Text),
    Column("application_date", Text),
    Column("approval_date", Text),
    Column("expiration_date", Text),
    Column("inspection_required", Integer, server_default=text("1")),
    Column("inspection_date", Text),
    Column("inspection_result", Text),
    Column("inspector_name", Text),
    Column("correction_notes", Text),
    Column("status", Text, server_default=text("'applied'")),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=now_default()),
    CheckConstraint(
        "inspection_result IN ('pass','fail','conditional','pending')",
        name="ck_constructclaw_permit_inspection_result"),
    CheckConstraint("status IN ('applied','approved','expired','closed')",
                    name="ck_constructclaw_permit_status"),
)

Index("idx_ccperm_job", PERMIT.c.job_id)
Index("idx_ccperm_company", PERMIT.c.company_id)
Index("idx_ccperm_status", PERMIT.c.status)
Index("idx_ccperm_expiry", PERMIT.c.expiration_date)


# -------------------------------------------------------------------
# 33. constructclaw_punch_list_item -- closeout punch list
# -------------------------------------------------------------------
PUNCH_LIST_ITEM = Table(
    "constructclaw_punch_list_item", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("job_id", Text,
           ForeignKey("constructclaw_job.id", ondelete="RESTRICT"), nullable=False),
    Column("description", Text, nullable=False),
    Column("location", Text),
    Column("assigned_to", Text),
    Column("subcontractor_id", Text),
    Column("priority", Text, server_default=text("'normal'")),
    Column("photo_url", Text),
    Column("completion_date", Text),
    Column("status", Text, server_default=text("'open'")),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=now_default()),
    CheckConstraint("priority IN ('critical','high','normal','low')",
                    name="ck_constructclaw_punch_list_item_priority"),
    CheckConstraint("status IN ('open','in_progress','completed','verified')",
                    name="ck_constructclaw_punch_list_item_status"),
)

Index("idx_ccpunch_job", PUNCH_LIST_ITEM.c.job_id)
Index("idx_ccpunch_company", PUNCH_LIST_ITEM.c.company_id)
Index("idx_ccpunch_status", PUNCH_LIST_ITEM.c.status)
Index("idx_ccpunch_priority", PUNCH_LIST_ITEM.c.priority)


# -------------------------------------------------------------------
# 34. constructclaw_insurance_bond -- insurance & bond tracking
# -------------------------------------------------------------------
INSURANCE_BOND = Table(
    "constructclaw_insurance_bond", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    # job_id carries no foreign key here, unlike every other table that names it.
    # Preserved as shipped (rule 12).
    Column("job_id", Text),
    Column("subcontractor_id", Text),
    Column("document_type", Text, nullable=False),
    Column("carrier", Text),
    Column("policy_number", Text),
    Column("coverage_amount", Text, server_default=text("'0'")),
    Column("effective_date", Text),
    Column("expiration_date", Text),
    Column("verified", Integer, server_default=text("0")),
    Column("verified_by", Text),
    Column("verified_date", Text),
    Column("status", Text, server_default=text("'active'")),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=now_default()),
    CheckConstraint(
        "document_type IN ('coi','bid_bond','performance_bond','payment_bond',"
        "'builders_risk')",
        name="ck_constructclaw_insurance_bond_document_type"),
    CheckConstraint("status IN ('active','expired','cancelled')",
                    name="ck_constructclaw_insurance_bond_status"),
)

Index("idx_ccbond_company", INSURANCE_BOND.c.company_id)
Index("idx_ccbond_job", INSURANCE_BOND.c.job_id)
Index("idx_ccbond_status", INSURANCE_BOND.c.status)
Index("idx_ccbond_expiry", INSURANCE_BOND.c.expiration_date)


# -------------------------------------------------------------------
# 35. constructclaw_warranty -- warranty tracking
# -------------------------------------------------------------------
WARRANTY = Table(
    "constructclaw_warranty", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("job_id", Text,
           ForeignKey("constructclaw_job.id", ondelete="RESTRICT"), nullable=False),
    Column("trade", Text),
    Column("system", Text, nullable=False),
    Column("subcontractor_id", Text),
    Column("start_date", Text, nullable=False),
    Column("end_date", Text, nullable=False),
    Column("warranty_type", Text, server_default=text("'standard'")),
    Column("description", Text),
    Column("contact_info", Text),
    Column("status", Text, server_default=text("'active'")),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=now_default()),
    CheckConstraint(
        "warranty_type IN ('standard','extended','manufacturer')",
        name="ck_constructclaw_warranty_warranty_type"),
    CheckConstraint("status IN ('active','expired','claimed')",
                    name="ck_constructclaw_warranty_status"),
)

Index("idx_ccwarr_job", WARRANTY.c.job_id)
Index("idx_ccwarr_company", WARRANTY.c.company_id)
Index("idx_ccwarr_status", WARRANTY.c.status)
Index("idx_ccwarr_end", WARRANTY.c.end_date)


# -------------------------------------------------------------------
# 36. constructclaw_milestone -- project scheduling / CPM milestones
# -------------------------------------------------------------------
MILESTONE = Table(
    "constructclaw_milestone", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("job_id", Text,
           ForeignKey("constructclaw_job.id", ondelete="RESTRICT"), nullable=False),
    Column("name", Text, nullable=False),
    Column("description", Text),
    Column("planned_date", Text),
    Column("actual_date", Text),
    # Self-referential in intent, but the shipped DDL declares no foreign key.
    # Adding one here would be a schema change wearing a refactor's clothes.
    Column("predecessor_id", Text),
    Column("dependency_type", Text, server_default=text("'finish_to_start'")),
    Column("lag_days", Integer, server_default=text("0")),
    Column("is_critical", Integer, server_default=text("0")),
    Column("status", Text, server_default=text("'pending'")),
    Column("company_id", Text,
           ForeignKey("company.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", Text, server_default=now_default()),
    CheckConstraint(
        "dependency_type IN ('finish_to_start','start_to_start',"
        "'finish_to_finish','start_to_finish')",
        name="ck_constructclaw_milestone_dependency_type"),
    CheckConstraint(
        "status IN ('pending','in_progress','completed','delayed')",
        name="ck_constructclaw_milestone_status"),
)

Index("idx_ccms_job", MILESTONE.c.job_id)
Index("idx_ccms_company", MILESTONE.c.company_id)
Index("idx_ccms_status", MILESTONE.c.status)
Index("idx_ccms_planned", MILESTONE.c.planned_date)


def init_constructclaw_schema(db_path: str = DB_PATH) -> dict:
    """Create construction management tables and indexes.

    Same contract as before the ADR-0034 conversion: idempotent, and the returned
    counts are what was ACTUALLY created rather than what was declared.
    """
    result = provision(METADATA, db_path)
    return {
        "database": db_path,
        "tables": result["tables"],
        "indexes": result["indexes"],
    }


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else DB_PATH
    result = init_constructclaw_schema(path)
    print(f"ConstructClaw schema created in {result['database']}")
    print(f"  Tables: {result['tables']}")
    print(f"  Indexes: {result['indexes']}")
