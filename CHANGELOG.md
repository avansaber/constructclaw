# Changelog

All notable changes to the ConstructClaw vertical skill.

## [1.1.0] — 2026-07-05 — M33 Item 3 (B9) — G703 continuation-sheet line derivation

### Added
- **`construction-add-progress-bill` now derives AIA G703 continuation-sheet
  lines from the linked schedule of values.** When the bill is called with a
  `--sov-id` whose SOV carries line items, one `constructclaw_progress_bill_line`
  is derived per `constructclaw_sov_line` (item number, description, scheduled
  value, previous completed, this period, materials stored, total completed,
  percent complete, balance to finish, retention amount). Per-line G703 columns
  are recomputed from their components (`total_completed = previous + this_period
  + materials_stored`; `retention_amount = retention_pct% of total_completed`),
  so each derived line is self-consistent. `construction-get-progress-bill` now
  returns these lines instead of an always-empty `lines` list. Retires the
  `constructclaw_progress_bill_line` zero-writer orphan (necessity-audit G2).

### Changed
- **Header totals roll up from the derived lines and OVERRIDE caller-supplied
  flat totals.** With SOV lines present, `total_completed` / `total_retention`
  equal the exact Decimal roll-up of the line values; any flat
  `--total-completed` / `--total-retention` the caller passes are ignored and
  reported back in the response (`totals_source: "sov_lines"`,
  `caller_totals_overridden: true`, `overridden_totals: {...}`). This is an
  observable-behavior change for callers that previously supplied flat totals
  alongside `--sov-id`.

### Unchanged
- The header-only path is preserved for backward compatibility: no `--sov-id`,
  or an SOV with no lines, keeps the existing flat-totals behavior
  (`totals_source: "caller"`, no lines written). Draft -> submit lifecycle
  semantics are unchanged. All money remains TEXT/Decimal (ROUND_HALF_UP).
