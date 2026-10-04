## v0.21.0 (2026-10-04)
- #375: Feat: invariants test module and process-rule documentation for da ($4.59)
- #371: Feat: seeded in-memory store fixture covering all known edge-case ($1.33)
- #370: Feat: is_plausible_person_name accepts lowercase words like 'meeti ($0.74)
- #369: Feat: dedup merges different people through contaminated handle al ($1.99)
- #361: Feat: entity prune --non-person deletes handle-named senders with ($1.23)
- #360: Feat: dedup merges different people and uses wrong canonical direc ($2.48)
- #356: Feat: first-name-only references create duplicate person entities ($2.30)
- #353: Feat: entity prune and dedup don't catch extraction residue — shar ($2.75)
- #352: Feat: non-person phrases saved as type=person entities during extr ($1.71)
- #350: Feat: LLM-supplied aliases merged unchecked into non-owner entitie ($2.15)
Total: 10 PRs, $21.27

## v0.20.0 (2026-10-03)

### Entity Quality & Extraction Fixes
- #340: Fix: extraction path alias pollution — _upsert_entity merges owner identifiers into partial-match entities
- #346: Fix: non-person phrases saved as type=person entities during extraction
- #347: Fix: first-name-only references create duplicate person entities after LIKE removal
- #348: Fix: LLM-supplied aliases merged unchecked into non-owner entities
- #349: Fix: entity prune and dedup don't catch extraction residue — shared plausibility check

### Data Quality & Maintenance
- #330: Test: regression test that owner resolution never pollutes other entity aliases
- #331: Fix: owner merge --dry-run and safety checks for non-owner entities
- #332: Fix: mention path upserts owner duplicate entity without checking user_ids
- #333: Fix: dangling reference cleanup and integrity check
- #334: Fix: strip Slack link markup and improve channel_id extraction
- #341: Feat: add patina entity prune-links CLI command with --dry-run
- #342: Fix: strip_slack_link_markup preserves label text instead of dropping entire link

## v0.19.2 (2026-09-30)
- #326: Fix: replace substring LIKE fallback with owner-aware entity resolution ($0.00)
Total: 1 PRs, $0.00

## v0.19.0 (2026-09-28)
- #320: Feat: Update autonomy status CLI and MCP tool to display per-domai ($1.18)
- #319: Feat: Scope tracker demotion/freeze to domain and map action types ($1.32)
- #318: Fix: Add owner merge/repair command to fold duplicate self-entiti ($1.49)
- #317: Fix: Fix _ingest_messages() to resolve owner identity on every in ($1.69)
- #316: Feat: entity & data maintenance CLI (merge, dedup, prune non-perso ($6.85)
- #314: Fix: Normalize alias prefixes and extend owner identifier config ($1.44)
- #313: Feat: Migrate autonomy_state schema to domain-keyed and update cor ($2.21)
Total: 7 PRs, $16.18

## v0.18.3 (2026-09-24)
- #296: Fix: backfill eval snapshots with PR-based implementations ($0.00)
- #299: Chore: regenerate EVAL.md with corrected metrics ($0.00)
- #300: Chore: set auto-merge promotion level to repo ($0.00)
Total: 3 PRs, $0.00

## v0.18.2 (2026-09-21)
- #291: Fix: exclude relay label from triage pipeline ($0.00)
Total: 1 PRs, $0.00

## v0.18.1 (2026-09-20)
- #285: Docs: add EVAL.md dashboard link to README ($0.00)
Total: 1 PRs, $0.00

