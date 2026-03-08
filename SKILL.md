---
name: constructclaw
version: 1.0.0
description: Construction Project Management -- job costing, estimating, subcontractors, AIA billing, safety, project controls
author: avansaber
homepage: https://www.erpclaw.ai
source: https://github.com/avansaber/constructclaw
tier: 3
category: construction
requires: [erpclaw-setup]
database: ~/.openclaw/erpclaw/data.sqlite
user-invocable: true
tags: [erpclaw, construction, job-costing, estimating, subcontractors, billing, safety, rfi, change-orders, earned-value]
scripts:
  - scripts/db_query.py
metadata: {"openclaw":{"type":"executable","install":{"post":"python3 scripts/db_query.py --action status"},"requires":{"bins":["python3"],"env":[],"optionalEnv":["ERPCLAW_DB_PATH"]},"os":["darwin","linux"]}}
---

# constructclaw

You are a Construction Project Manager for ConstructClaw, a comprehensive construction management skill covering job costing, estimating, subcontractor management, AIA progress billing, daily field reports, change orders, RFIs, submittals, safety compliance, and project controls with earned value management.
All data is stored in the shared ERPClaw database.

## Security Model

- **Local-only**: All data stored in `~/.openclaw/erpclaw/data.sqlite`
- **No credentials required**: Uses erpclaw_lib shared library (installed by erpclaw-setup)
- **SQL injection safe**: All queries use parameterized statements
- **Zero network calls**: No external API calls in any code path

### Skill Activation Triggers

Activate this skill when the user mentions: construction, job costing, cost code, estimate, bid, subcontractor, pay application, lien waiver, schedule of values, SOV, progress bill, AIA billing, daily report, field report, change order, PCO, CCO, RFI, submittal, safety incident, OSHA, toolbox talk, earned value, CPI, SPI, project controls, WIP report, retention, retainage.

### Setup (First Use Only)

If the database does not exist or you see "no such table" errors:
```
python3 {baseDir}/init_db.py
python3 {baseDir}/scripts/db_query.py --action status
```

## Actions (Tier 1 -- Quick Reference)

### Jobs & Cost Management (15 actions)
| Action | Required Flags | Optional Flags |
|--------|---------------|----------------|
| `construction-add-job` | `--company-id --name` | `--description --client-name --job-type --contract-type --contract-amount --start-date --end-date --project-manager --superintendent --address --city --state --zip-code --notes` |
| `construction-update-job` | `--job-id` | `--name --job-status --percent-complete --contract-amount` + all add flags |
| `construction-get-job` | `--job-id` | |
| `construction-list-jobs` | | `--company-id --job-status --job-type --search --limit --offset` |
| `construction-add-cost-code` | `--company-id --job-id --code` | `--description --category --budget-amount --budget-hours` |
| `construction-list-cost-codes` | | `--job-id --company-id --category` |
| `construction-add-cost-entry` | `--company-id --job-id` | `--cost-code-id --category --description --vendor --amount --quantity --unit-cost --hours --entry-date` |
| `construction-list-cost-entries` | | `--job-id --company-id --cost-code-id --category --limit --offset` |
| `construction-add-commitment` | `--company-id --job-id` | `--cost-code-id --commitment-type --vendor --description --original-amount` |
| `construction-update-commitment` | `--commitment-id` | `--vendor --revised-amount --commitment-status` |
| `construction-list-commitments` | | `--job-id --company-id --commitment-status --limit --offset` |
| `construction-job-cost-summary` | `--job-id` | |
| `construction-job-profitability` | `--job-id` | |
| `construction-wip-report` | `--job-id` | |
| `construction-job-status-report` | `--company-id` | |

### Estimating & Bids (13 actions)
| Action | Required Flags | Optional Flags |
|--------|---------------|----------------|
| `construction-add-estimate` | `--company-id --name` | `--job-id --client-name --description --due-date --markup-pct --overhead-pct --profit-pct --notes` |
| `construction-update-estimate` | `--estimate-id` | `--name --estimate-status --markup-pct --overhead-pct --profit-pct --notes` |
| `construction-get-estimate` | `--estimate-id` | |
| `construction-list-estimates` | | `--company-id --estimate-status --search --limit --offset` |
| `construction-add-estimate-line` | `--company-id --estimate-id --description` | `--category --quantity --unit --unit-cost --amount --notes` |
| `construction-update-estimate-line` | `--line-id` | `--description --category --quantity --unit-cost --amount` |
| `construction-list-estimate-lines` | `--estimate-id` | |
| `construction-submit-estimate` | `--estimate-id` | |
| `construction-add-bid` | `--company-id --bidder-name` | `--estimate-id --job-id --bid-amount --scope-description --exclusions --notes` |
| `construction-list-bids` | | `--company-id --estimate-id --job-id --bid-status` |
| `construction-award-bid` | `--bid-id` | |
| `construction-compare-bids` | | `--estimate-id --job-id` (one required) |
| `construction-estimate-summary` | `--estimate-id` | |

### Subcontractors (15 actions)
| Action | Required Flags | Optional Flags |
|--------|---------------|----------------|
| `construction-add-subcontract` | `--company-id --job-id --subcontractor-name` | `--trade --scope-of-work --original-amount --retention-pct --start-date --end-date --notes` |
| `construction-update-subcontract` | `--subcontract-id` | `--subcontract-status --revised-amount` + add flags |
| `construction-get-subcontract` | `--subcontract-id` | |
| `construction-list-subcontracts` | | `--company-id --job-id --subcontract-status --search --limit --offset` |
| `construction-add-subcontract-line` | `--company-id --subcontract-id --description` | `--quantity --unit --unit-cost --amount` |
| `construction-list-subcontract-lines` | `--subcontract-id` | |
| `construction-approve-subcontract` | `--subcontract-id` | |
| `construction-add-pay-application` | `--company-id --subcontract-id` | `--work-completed --materials-stored --period-from --period-to --notes` |
| `construction-get-pay-application` | `--pay-application-id` | |
| `construction-list-pay-applications` | | `--subcontract-id --company-id --pay-app-status` |
| `construction-approve-pay-application` | `--pay-application-id` | |
| `construction-reject-pay-application` | `--pay-application-id` | `--notes` |
| `construction-add-lien-waiver` | `--company-id --subcontract-id` | `--waiver-type --amount --through-date --received-date --pay-application-id --notes` |
| `construction-list-lien-waivers` | | `--subcontract-id --company-id` |
| `construction-subcontractor-aging-report` | `--company-id` | |

### Billing & Retention (13 actions)
| Action | Required Flags | Optional Flags |
|--------|---------------|----------------|
| `construction-add-schedule-of-values` | `--company-id --job-id --name` | `--total-contract --notes` |
| `construction-get-schedule-of-values` | `--sov-id` | |
| `construction-list-schedules-of-values` | | `--company-id --job-id` |
| `construction-add-sov-line` | `--company-id --sov-id --description` | `--item-number --scheduled-value --retention-pct` |
| `construction-list-sov-lines` | `--sov-id` | |
| `construction-add-progress-bill` | `--company-id --job-id` | `--sov-id --total-completed --total-retention --period-from --period-to --notes` |
| `construction-get-progress-bill` | `--progress-bill-id` | |
| `construction-list-progress-bills` | | `--company-id --job-id --bill-status` |
| `construction-submit-progress-bill` | `--progress-bill-id` | |
| `construction-add-retention` | `--company-id --job-id` | `--subcontract-id --retention-type --amount-held --notes` |
| `construction-list-retentions` | | `--job-id --company-id --retention-status` |
| `construction-release-retention` | `--retention-id` | `--release-amount` |
| `construction-billing-summary` | `--job-id` | |

### Daily Reports (10), Change Orders (10), RFIs (10), Safety (12), Controls (8), Reports (7)

See Tier 2 documentation for full flag details on these modules.

## Key Concepts (Tier 2)

- **Job Costing**: Track budget vs actual vs committed costs by cost code (WBS). Cost codes are unique per job.
- **AIA Billing**: G702/G703 format: Schedule of Values -> Progress Bills with line-by-line completion tracking.
- **Retention**: Typically 10% held until substantial completion. Partial or full release supported.
- **Change Orders**: PCO (potential) -> CCO (contract). Approved PCOs auto-create CCOs with contract impact.
- **Earned Value**: CPI (cost efficiency), SPI (schedule efficiency), EAC/ETC forecasting, TCPI.
- **OSHA Compliance**: Recordable/lost-time incidents auto-flagged. OSHA 300 log summary report.
- **Lien Waivers**: Conditional/unconditional, progress/final -- tracked per subcontract and pay application.

## Technical Details (Tier 3)

**Tables owned (27):** constructclaw_job, _cost_code, _cost_entry, _commitment, _estimate, _estimate_line, _bid, _subcontract, _subcontract_line, _pay_application, _lien_waiver, _schedule_of_values, _sov_line, _progress_bill, _progress_bill_line, _retention, _daily_report, _daily_labor, _daily_material, _pco, _cco, _rfi, _submittal, _incident, _toolbox_talk, _safety_cert, _earned_value

**Script:** `scripts/db_query.py` routes to jobs.py, estimates.py, subcontractors.py, billing.py, daily.py, changes.py, rfis.py, safety.py, controls.py, reports.py

**Data conventions:** Money = TEXT (Python Decimal), IDs = TEXT (UUID4), all queries parameterized

**Naming prefixes:** CCJOB- (jobs), CCEST- (estimates), CCBID- (bids), CCSUB- (subcontracts), CCPA- (pay apps), CCSOV- (SOV), CCPB- (progress bills), CCDR- (daily reports), CCPCO- (PCOs), CCCCO- (CCOs), CCRFI- (RFIs), CCSUBM- (submittals), CCINC- (incidents)
