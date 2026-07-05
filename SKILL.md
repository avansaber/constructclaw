---
name: constructclaw
version: 1.1.0
description: Construction Project Management -- 159 actions across 12 domains. Job costing, estimating, bids, subcontractors, AIA billing, SOV, daily reports, change orders, RFIs, submittals, safety/OSHA, project controls with earned value, field ops, and project management.
author: AvanSaber
homepage: https://github.com/avansaber/constructclaw
source: https://github.com/avansaber/constructclaw
tier: 3
category: construction
requires: [erpclaw]
database: ~/.openclaw/erpclaw/data.sqlite
user-invocable: true
tags: [erpclaw, construction, job-costing, estimating, subcontractors, billing, safety, rfi, change-orders, earned-value, aia, osha, lien-waiver, prevailing-wage, wip, punch-list, submittal, field-ops]
scripts:
  - scripts/db_query.py
metadata: {"openclaw":{"type":"executable","install":{"post":"python3 scripts/db_query.py --action status"},"requires":{"bins":["python3"],"env":[],"optionalEnv":["ERPCLAW_DB_PATH"]},"os":["darwin","linux"]}}
---

# constructclaw

Construction Project Manager for ConstructClaw -- comprehensive construction management on ERPClaw.
Covers job costing, estimating, bids, subcontractor management, AIA progress billing, daily field reports,
change orders (PCO/CCO), RFIs, submittals, safety/OSHA compliance, earned value management,
field operations, and project portfolio management. All data in shared ERPClaw database.

### Skill Activation Triggers

Activate when user mentions: construction, job costing, cost code, estimate, bid, subcontractor,
pay application, lien waiver, schedule of values, SOV, progress bill, AIA billing, daily report,
field report, change order, PCO, CCO, RFI, submittal, safety incident, OSHA, toolbox talk,
earned value, CPI, SPI, project controls, WIP report, retention, retainage, punch list,
prevailing wage, Davis-Bacon, certified payroll, equipment, permit, warranty, milestone.

### Setup
```
python3 {baseDir}/init_db.py
python3 {baseDir}/scripts/db_query.py --action status
```

## Quick Start
```
--action construction-add-job --company-id {id} --name "Main St Office" --contract-amount "2500000.00"
--action construction-add-cost-code --company-id {id} --job-id {id} --code "03-100" --category labor --budget-amount "50000.00"
--action construction-add-subcontract --company-id {id} --job-id {id} --subcontractor-name "ABC Electric" --original-amount "150000.00"
--action construction-add-schedule-of-values --company-id {id} --job-id {id} --name "AIA G703"
--action construction-add-progress-bill --company-id {id} --job-id {id} --sov-id {id}
--action construction-submit-progress-bill --progress-bill-id {id}
```

## All 159 Actions

### Jobs & Cost Management (15 actions)
| Action | Description |
|--------|-------------|
| `construction-add-job` | Create construction job/project |
| `construction-update-job` | Update job details/status |
| `construction-get-job` | Get job with cost summary |
| `construction-list-jobs` | List/filter jobs |
| `construction-add-cost-code` | Add WBS cost code to job |
| `construction-batch-add-cost-codes` | Batch add cost codes |
| `construction-list-cost-codes` | List cost codes |
| `construction-add-cost-entry` | Record actual cost |
| `construction-list-cost-entries` | List cost entries |
| `construction-add-commitment` | Add cost commitment |
| `construction-update-commitment` | Update commitment |
| `construction-list-commitments` | List commitments |
| `construction-job-cost-summary` | Job cost vs budget summary |
| `construction-job-profitability` | Job profitability analysis |
| `construction-job-cost-report` | Detailed job cost report |

### Estimating & Bids (13 actions)
| Action | Description |
|--------|-------------|
| `construction-add-estimate` | Create project estimate |
| `construction-update-estimate` | Update estimate |
| `construction-get-estimate` | Get estimate with lines |
| `construction-list-estimates` | List estimates |
| `construction-add-estimate-line` | Add estimate line item |
| `construction-update-estimate-line` | Update estimate line |
| `construction-list-estimate-lines` | List estimate lines |
| `construction-submit-estimate` | Submit estimate |
| `construction-estimate-summary` | Estimate summary with totals |
| `construction-add-bid` | Add vendor/sub bid |
| `construction-list-bids` | List bids |
| `construction-award-bid` | Award bid to vendor |
| `construction-compare-bids` | Compare bids side by side |

### Subcontractors (16 actions)
| Action | Description |
|--------|-------------|
| `construction-add-subcontract` | Create subcontract |
| `construction-update-subcontract` | Update subcontract |
| `construction-get-subcontract` | Get subcontract details |
| `construction-list-subcontracts` | List subcontracts |
| `construction-add-subcontract-line` | Add subcontract line |
| `construction-list-subcontract-lines` | List subcontract lines |
| `construction-approve-subcontract` | Approve subcontract |
| `construction-add-pay-application` | Create pay application |
| `construction-get-pay-application` | Get pay application |
| `construction-list-pay-applications` | List pay applications |
| `construction-approve-pay-application` | Approve pay application |
| `construction-reject-pay-application` | Reject pay application |
| `construction-add-lien-waiver` | Add lien waiver |
| `construction-list-lien-waivers` | List lien waivers |
| `construction-subcontractor-aging` | Subcontractor aging report |
| `construction-subcontractor-aging-report` | Detailed aging report |

### Billing & Retention (14 actions)
| Action | Description |
|--------|-------------|
| `construction-add-schedule-of-values` | Create SOV (AIA G703) |
| `construction-get-schedule-of-values` | Get SOV with lines |
| `construction-list-schedules-of-values` | List SOVs |
| `construction-add-sov-line` | Add SOV line item |
| `construction-list-sov-lines` | List SOV lines |
| `construction-add-progress-bill` | Create progress bill; with `--sov-id` derives G703 lines from SOV and rolls header totals up from them (flat totals overridden) |
| `construction-get-progress-bill` | Get progress bill with G703 continuation-sheet lines |
| `construction-list-progress-bills` | List progress bills |
| `construction-submit-progress-bill` | Submit progress bill |
| `construction-approve-progress-bill` | Approve progress bill |
| `construction-add-retention` | Record retention held |
| `construction-list-retentions` | List retentions |
| `construction-release-retention` | Release retention |
| `construction-billing-summary` | Billing summary report |

### Daily Reports (10 actions)
| Action | Description |
|--------|-------------|
| `construction-add-daily-report` | Create daily field report |
| `construction-update-daily-report` | Update daily report |
| `construction-get-daily-report` | Get daily report |
| `construction-list-daily-reports` | List daily reports |
| `construction-submit-daily-report` | Submit daily report |
| `construction-add-daily-labor` | Add labor to daily report |
| `construction-list-daily-labor` | List daily labor entries |
| `construction-add-daily-material` | Add material to daily report |
| `construction-list-daily-materials` | List daily materials |
| `construction-daily-summary` | Daily report summary |

### Change Orders (10 actions)
| Action | Description |
|--------|-------------|
| `construction-add-pco` | Create potential change order |
| `construction-update-pco` | Update PCO |
| `construction-get-pco` | Get PCO details |
| `construction-list-pcos` | List PCOs |
| `construction-approve-pco` | Approve PCO (creates CCO) |
| `construction-add-cco` | Create contract change order |
| `construction-get-cco` | Get CCO details |
| `construction-list-ccos` | List CCOs |
| `construction-approve-cco` | Approve CCO |
| `construction-change-order-impact` | Change order impact report |

### RFIs & Submittals (10 actions)
| Action | Description |
|--------|-------------|
| `construction-add-rfi` | Create RFI |
| `construction-update-rfi` | Update RFI |
| `construction-get-rfi` | Get RFI details |
| `construction-list-rfis` | List RFIs |
| `construction-close-rfi` | Close RFI |
| `construction-respond-to-rfi` | Respond to RFI |
| `construction-add-submittal` | Create submittal |
| `construction-update-submittal` | Update submittal |
| `construction-list-submittals` | List submittals |
| `construction-review-submittal` | Review submittal |

### Safety & OSHA (14 actions)
| Action | Description |
|--------|-------------|
| `construction-add-incident` | Report safety incident |
| `construction-update-incident` | Update incident |
| `construction-get-incident` | Get incident details |
| `construction-list-incidents` | List incidents |
| `construction-close-incident` | Close incident |
| `construction-add-toolbox-talk` | Record toolbox talk |
| `construction-list-toolbox-talks` | List toolbox talks |
| `construction-add-safety-cert` | Add safety certification |
| `construction-list-safety-certs` | List safety certs |
| `construction-expire-safety-cert` | Expire safety cert |
| `construction-safety-report` | Safety metrics report |
| `construction-safety-dashboard` | Safety dashboard |
| `construction-osha-300-summary` | OSHA 300 log summary |
| `construction-record-inspection-result` | Record inspection result |

### Project Controls (8 actions)
| Action | Description |
|--------|-------------|
| `construction-add-earned-value` | Record earned value data |
| `construction-list-earned-values` | List earned value entries |
| `construction-calculate-ev-metrics` | Calculate CPI/SPI/EAC/ETC |
| `construction-wip-report` | Work-in-progress report |
| `construction-wip-report-all` | WIP report all jobs |
| `construction-cost-forecast` | Cost forecast with EAC |
| `construction-job-status-report` | Job status report |
| `construction-schedule-variance-report` | Schedule variance report |

### Field Operations (18 actions)
| Action | Description |
|--------|-------------|
| `construction-add-drawing` | Add project drawing |
| `construction-list-drawings` | List drawings |
| `construction-add-punch-list-item` | Add punch list item |
| `construction-update-punch-list-item` | Update punch list item |
| `construction-list-punch-list` | List punch list items |
| `construction-punch-list-summary` | Punch list summary |
| `construction-schedule-inspection` | Schedule inspection |
| `construction-add-insurance-bond` | Add insurance/bond record |
| `construction-list-insurance-bonds` | List insurance/bonds |
| `construction-check-expiring-insurance` | Check expiring insurance |
| `construction-add-warranty` | Add warranty record |
| `construction-list-warranties` | List warranties |
| `construction-check-expiring-warranties` | Check expiring warranties |
| `construction-add-permit` | Add permit |
| `construction-update-permit` | Update permit |
| `construction-list-permits` | List permits |
| `construction-create-material-requisition` | Create material requisition |
| `construction-list-material-requisitions` | List material requisitions |

### Project Management (18 actions)
| Action | Description |
|--------|-------------|
| `construction-add-milestone` | Add project milestone |
| `construction-update-milestone` | Update milestone |
| `construction-list-milestones` | List milestones |
| `construction-add-time-entry` | Add labor time entry |
| `construction-approve-time-entry` | Approve time entry |
| `construction-reject-time-entry` | Reject time entry |
| `construction-list-time-entries` | List time entries |
| `construction-time-entry-summary` | Time entry summary |
| `construction-assign-equipment` | Assign equipment to job |
| `construction-release-equipment` | Release equipment |
| `construction-update-equipment-assignment` | Update equipment assignment |
| `construction-list-equipment-assignments` | List equipment assignments |
| `construction-equipment-conflict-check` | Check equipment conflicts |
| `construction-track-material-delivery` | Track material delivery |
| `construction-add-prevailing-wage-rate` | Add prevailing wage rate |
| `construction-list-prevailing-wage-rates` | List prevailing wage rates |
| `construction-add-certified-payroll-entry` | Add certified payroll entry |
| `construction-list-certified-payroll` | List certified payroll |

### Reports (13 actions)
| Action | Description |
|--------|-------------|
| `construction-report-status` | Module status |
| `construction-executive-summary` | Executive project summary |
| `construction-portfolio-overview` | Multi-project portfolio |
| `construction-project-health-dashboard` | Project health dashboard |
| `construction-critical-path-report` | Critical path report |
| `construction-resource-utilization` | Resource utilization |
| `construction-labor-cost-report` | Labor cost report |
| `construction-material-waste-report` | Material waste report |
| `construction-insurance-compliance-report` | Insurance compliance |
| `construction-permit-expiry-report` | Permit expiry report |
| `construction-equipment-utilization-report` | Equipment utilization |
| `construction-certified-payroll-summary` | Certified payroll summary |
| `construction-generate-wh347` | Generate WH-347 form |

## Technical Details (Tier 3)
**Tables (27):** All use `constructclaw_` prefix. **Script:** `scripts/db_query.py` routes to 12 modules. **Data:** Money=TEXT(Decimal), IDs=TEXT(UUID4). **Prefixes:** CCJOB-, CCEST-, CCBID-, CCSUB-, CCPA-, CCSOV-, CCPB-, CCDR-, CCPCO-, CCCCO-, CCRFI-, CCSUBM-, CCINC-.
