#!/usr/bin/env python3
"""ConstructClaw -- db_query.py (unified router)

Construction project management: job costing, estimating, subcontractors,
AIA billing, daily reports, change orders, RFIs, safety, project controls,
equipment scheduling, certified payroll, labor time tracking.
Routes all 157 actions across 12 domain modules.

Usage: python3 db_query.py --action <action-name> [--flags ...]
Output: JSON to stdout, exit 0 on success, exit 1 on error.
"""
import argparse
import json
import os
import sys

# Add shared lib to path
try:
    import importlib.util
    if importlib.util.find_spec("erpclaw_lib") is None:
        sys.path.insert(0, os.path.join(os.path.expanduser(os.environ.get("ERPCLAW_HOME", "~/.openclaw/erpclaw")), "lib"))
    from erpclaw_lib.db import get_connection, ensure_db_exists, DEFAULT_DB_PATH
    from erpclaw_lib.validation import check_input_lengths
    from erpclaw_lib.response import ok, err
    from erpclaw_lib.dependencies import check_required_tables
    from erpclaw_lib.args import SafeArgumentParser, check_unknown_args
except ImportError:
    import json as _json
    print(_json.dumps({
        "status": "error",
        "error": "ERPClaw foundation not installed. Install erpclaw-setup first: clawhub install erpclaw-setup",
        "suggestion": "clawhub install erpclaw-setup"
    }))
    sys.exit(1)

# Add this script's directory so domain modules can be imported
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from jobs import ACTIONS as JOB_ACTIONS
from estimates import ACTIONS as ESTIMATE_ACTIONS
from subcontractors import ACTIONS as SUB_ACTIONS
from billing import ACTIONS as BILLING_ACTIONS
from daily import ACTIONS as DAILY_ACTIONS
from changes import ACTIONS as CHANGE_ACTIONS
from rfis import ACTIONS as RFI_ACTIONS
from safety import ACTIONS as SAFETY_ACTIONS
from controls import ACTIONS as CONTROL_ACTIONS
from reports import ACTIONS as REPORT_ACTIONS
from field_ops import ACTIONS as FIELD_OPS_ACTIONS
from project_mgmt import ACTIONS as PROJECT_MGMT_ACTIONS

# ---------------------------------------------------------------------------
# Merge all domain actions into one router
# ---------------------------------------------------------------------------
SKILL = "constructclaw"
REQUIRED_TABLES = ["company", "constructclaw_job"]

ACTIONS = {}
ACTIONS.update(JOB_ACTIONS)
ACTIONS.update(ESTIMATE_ACTIONS)
ACTIONS.update(SUB_ACTIONS)
ACTIONS.update(BILLING_ACTIONS)
ACTIONS.update(DAILY_ACTIONS)
ACTIONS.update(CHANGE_ACTIONS)
ACTIONS.update(RFI_ACTIONS)
ACTIONS.update(SAFETY_ACTIONS)
ACTIONS.update(CONTROL_ACTIONS)
ACTIONS.update(REPORT_ACTIONS)
ACTIONS.update(FIELD_OPS_ACTIONS)
ACTIONS.update(PROJECT_MGMT_ACTIONS)


def main():
    parser = SafeArgumentParser(description="constructclaw")
    parser.add_argument("--action", required=True, choices=sorted(ACTIONS.keys()))
    parser.add_argument("--db-path", default=None)

    # -- Jobs --
    parser.add_argument("--job-id")
    parser.add_argument("--company-id")
    parser.add_argument("--name")
    parser.add_argument("--description")
    parser.add_argument("--client-name")
    parser.add_argument("--client-id")
    parser.add_argument("--project-manager")
    parser.add_argument("--superintendent")
    parser.add_argument("--job-type")
    parser.add_argument("--contract-type")
    parser.add_argument("--contract-amount")
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--actual-start-date")
    parser.add_argument("--actual-end-date")
    parser.add_argument("--address")
    parser.add_argument("--city")
    parser.add_argument("--state")
    parser.add_argument("--zip-code")
    parser.add_argument("--job-status")
    parser.add_argument("--percent-complete")

    # -- Cost Codes --
    parser.add_argument("--code")
    parser.add_argument("--category")
    parser.add_argument("--budget-amount")
    parser.add_argument("--budget-hours")
    parser.add_argument("--cost-code-id")
    parser.add_argument("--codes-json")

    # -- Cost Entries --
    parser.add_argument("--entry-date")
    parser.add_argument("--vendor")
    parser.add_argument("--reference")
    parser.add_argument("--quantity")
    parser.add_argument("--unit-cost")
    parser.add_argument("--amount")
    parser.add_argument("--hours")
    parser.add_argument("--unit")

    # -- Commitments --
    parser.add_argument("--commitment-id")
    parser.add_argument("--commitment-type")
    parser.add_argument("--commitment-status")
    parser.add_argument("--original-amount")
    parser.add_argument("--revised-amount")
    parser.add_argument("--invoiced-amount")
    parser.add_argument("--paid-amount")

    # -- Estimates --
    parser.add_argument("--estimate-id")
    parser.add_argument("--estimate-status")
    parser.add_argument("--due-date")
    parser.add_argument("--markup-pct")
    parser.add_argument("--overhead-pct")
    parser.add_argument("--profit-pct")
    parser.add_argument("--total-amount")

    # -- Estimate Lines --
    parser.add_argument("--line-id")

    # -- Bids --
    parser.add_argument("--bid-id")
    parser.add_argument("--bidder-name")
    parser.add_argument("--bid-amount")
    parser.add_argument("--bid-status")
    parser.add_argument("--scope-description")
    parser.add_argument("--exclusions")

    # -- Subcontracts --
    parser.add_argument("--subcontract-id")
    parser.add_argument("--subcontractor-name")
    parser.add_argument("--trade")
    parser.add_argument("--scope-of-work")
    parser.add_argument("--retention-pct")
    parser.add_argument("--insurance-expiry")
    parser.add_argument("--license-number")
    parser.add_argument("--subcontract-status")

    # -- Pay Applications --
    parser.add_argument("--pay-application-id")
    parser.add_argument("--work-completed")
    parser.add_argument("--materials-stored")
    parser.add_argument("--period-from")
    parser.add_argument("--period-to")
    parser.add_argument("--pay-app-status")

    # -- Lien Waivers --
    parser.add_argument("--waiver-type")
    parser.add_argument("--through-date")
    parser.add_argument("--received-date")

    # -- SOV / Billing --
    parser.add_argument("--sov-id")
    parser.add_argument("--total-contract")
    parser.add_argument("--item-number")
    parser.add_argument("--scheduled-value")
    parser.add_argument("--progress-bill-id")
    parser.add_argument("--total-completed")
    parser.add_argument("--total-retention")
    parser.add_argument("--bill-status")

    # -- Retention --
    parser.add_argument("--retention-id")
    parser.add_argument("--retention-type")
    parser.add_argument("--amount-held")
    parser.add_argument("--release-amount")
    parser.add_argument("--retention-status")

    # -- Daily Reports --
    parser.add_argument("--daily-report-id")
    parser.add_argument("--report-date")
    parser.add_argument("--report-status")
    parser.add_argument("--weather")
    parser.add_argument("--temperature-high")
    parser.add_argument("--temperature-low")
    parser.add_argument("--work-description")
    parser.add_argument("--delays")
    parser.add_argument("--visitors")

    # -- Daily Labor --
    parser.add_argument("--headcount")

    # -- Daily Material --
    parser.add_argument("--material-name")
    parser.add_argument("--supplier")
    parser.add_argument("--delivery-ticket")

    # -- Change Orders --
    parser.add_argument("--pco-id")
    parser.add_argument("--pco-status")
    parser.add_argument("--title")
    parser.add_argument("--reason")
    parser.add_argument("--cost-impact")
    parser.add_argument("--time-impact-days")
    parser.add_argument("--requested-by")
    parser.add_argument("--cco-id")
    parser.add_argument("--cco-status")
    parser.add_argument("--cost-change")
    parser.add_argument("--time-change-days")
    parser.add_argument("--approved-by")

    # -- RFIs --
    parser.add_argument("--rfi-id")
    parser.add_argument("--rfi-status")
    parser.add_argument("--subject")
    parser.add_argument("--question")
    parser.add_argument("--response")
    parser.add_argument("--initiated-by")
    parser.add_argument("--assigned-to")
    parser.add_argument("--priority")
    parser.add_argument("--date-required")
    parser.add_argument("--schedule-impact-days")

    # -- Submittals --
    parser.add_argument("--submittal-id")
    parser.add_argument("--submittal-status")
    parser.add_argument("--spec-section")
    parser.add_argument("--submitted-by")
    parser.add_argument("--submitted-to")
    parser.add_argument("--decision")
    parser.add_argument("--review-comments")

    # -- Safety --
    parser.add_argument("--incident-id")
    parser.add_argument("--incident-type")
    parser.add_argument("--incident-status")
    parser.add_argument("--severity")
    parser.add_argument("--location")
    parser.add_argument("--injured-party")
    parser.add_argument("--witnesses")
    parser.add_argument("--root-cause")
    parser.add_argument("--corrective-action")
    parser.add_argument("--osha-recordable")
    parser.add_argument("--days-lost")
    parser.add_argument("--incident-date")
    parser.add_argument("--incident-time")
    parser.add_argument("--topic")
    parser.add_argument("--presenter")
    parser.add_argument("--attendee-count")
    parser.add_argument("--attendees")
    parser.add_argument("--duration-minutes")
    parser.add_argument("--safety-cert-id")
    parser.add_argument("--worker-name")
    parser.add_argument("--cert-type")
    parser.add_argument("--cert-number")
    parser.add_argument("--issued-date")
    parser.add_argument("--expiry-date")
    parser.add_argument("--issuing-authority")
    parser.add_argument("--cert-status")
    parser.add_argument("--talk-date")

    # -- Earned Value --
    parser.add_argument("--period-date")
    parser.add_argument("--planned-value")
    parser.add_argument("--earned-value")
    parser.add_argument("--actual-cost")
    parser.add_argument("--budget-at-completion")

    # -- Equipment Scheduling --
    parser.add_argument("--assignment-id")
    parser.add_argument("--equipment-name")
    parser.add_argument("--equipment-type")
    parser.add_argument("--daily-rate")
    parser.add_argument("--mobilization-cost")
    parser.add_argument("--demobilization-cost")
    parser.add_argument("--actual-hours")
    parser.add_argument("--equipment-status")

    # -- Certified Payroll / Prevailing Wage --
    parser.add_argument("--classification")
    parser.add_argument("--basic-rate")
    parser.add_argument("--fringe-rate")
    parser.add_argument("--total-rate")
    parser.add_argument("--overtime-rate")
    parser.add_argument("--wage-determination-number")
    parser.add_argument("--effective-date")
    parser.add_argument("--wage-status")
    parser.add_argument("--week-ending")
    parser.add_argument("--employee-name")
    parser.add_argument("--employee-id")
    parser.add_argument("--mon-hours")
    parser.add_argument("--tue-hours")
    parser.add_argument("--wed-hours")
    parser.add_argument("--thu-hours")
    parser.add_argument("--fri-hours")
    parser.add_argument("--sat-hours")
    parser.add_argument("--sun-hours")
    parser.add_argument("--overtime-hours")
    parser.add_argument("--hourly-rate")
    parser.add_argument("--gross-pay")
    parser.add_argument("--fica")
    parser.add_argument("--federal-tax")
    parser.add_argument("--state-tax")
    parser.add_argument("--other-deductions")
    parser.add_argument("--net-pay")
    parser.add_argument("--fringe-paid")
    parser.add_argument("--fringe-method")

    # -- Labor Time Tracking --
    parser.add_argument("--time-entry-id")
    parser.add_argument("--regular-hours")
    parser.add_argument("--double-time-hours")
    parser.add_argument("--work-date")
    parser.add_argument("--time-status")

    # -- Permits & Inspection --
    parser.add_argument("--permit-id")
    parser.add_argument("--permit-type")
    parser.add_argument("--permit-number")
    parser.add_argument("--permit-status")
    parser.add_argument("--application-date")
    parser.add_argument("--approval-date")
    parser.add_argument("--expiration-date")
    parser.add_argument("--inspection-date")
    parser.add_argument("--inspection-result")
    parser.add_argument("--correction-notes")

    # -- Punch List --
    parser.add_argument("--punch-item-id")
    parser.add_argument("--punch-status")
    parser.add_argument("--photo-url")
    parser.add_argument("--completion-date")
    parser.add_argument("--subcontractor-id")

    # -- Material Procurement --
    parser.add_argument("--material-id")

    # -- Insurance & Bond --
    parser.add_argument("--document-type")
    parser.add_argument("--carrier")
    parser.add_argument("--policy-number")
    parser.add_argument("--coverage-amount")

    # -- Warranty Tracking --
    parser.add_argument("--warranty-id")
    parser.add_argument("--warranty-type")
    parser.add_argument("--warranty-status")
    parser.add_argument("--system")
    parser.add_argument("--contact-info")

    # -- Milestones / CPM --
    parser.add_argument("--milestone-id")
    parser.add_argument("--milestone-status")
    parser.add_argument("--planned-date")
    parser.add_argument("--actual-date")
    parser.add_argument("--predecessor-id")
    parser.add_argument("--dependency-type")
    parser.add_argument("--lag-days")
    parser.add_argument("--is-critical")

    # -- Drawing --
    parser.add_argument("--discipline")
    parser.add_argument("--sheet-number")

    # -- Shared --
    parser.add_argument("--notes")
    parser.add_argument("--search")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--offset", type=int, default=0)

    args, unknown = parser.parse_known_args()
    check_unknown_args(parser, unknown)
    check_input_lengths(args)

    db_path = args.db_path or DEFAULT_DB_PATH
    ensure_db_exists(db_path)
    conn = get_connection(db_path)

    _dep = check_required_tables(conn, REQUIRED_TABLES)
    if _dep:
        _dep["suggestion"] = "clawhub install erpclaw-setup && python3 init_db.py"
        print(json.dumps(_dep, indent=2))
        conn.close()
        sys.exit(1)

    try:
        ACTIONS[args.action](conn, args)
    except SystemExit:
        raise
    except Exception as e:
        conn.rollback()
        sys.stderr.write(f"[{SKILL}] {e}\n")
        err(str(e))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
