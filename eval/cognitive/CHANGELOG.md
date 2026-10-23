## v0.29.1 (2026-10-23)
- #492: Fix: repair multi-identity entities retaining stolen member handles ($0.00)
Total: 1 PRs, $0.00

## v0.29.0 (2026-10-19)
- #489: Fix: split_dn_sink calendar branch never fires — live calendar source is outlook_mcp_email ($2.29)
- #488: Fix: ingest renames DN sink entity to a member's Slack handle via name-type ranking ($1.66)
- #487: Fix: slack_live sender_slack_id guard inconsistency and weak test ($2.98)
- #484: Feat: Fix backfill channel-peer DN logic in backfill.py and add pr ($2.16)
Total: 4 PRs, $9.09

## v0.28.0 (2026-10-18)
- #481: Feat: Write sender_slack_id and organizer_dn keys at ingest in Sla ($1.53)
Total: 1 PRs, $1.53

## v0.27.0 (2026-10-17)
- #476: Fix: backfill sender keys and multi-source routing for DN sink split ($3.75)
- #474: Feat: maintenance.py conflicting-ID routing and merge rewire ($3.55)
- #471: Feat: split_dn_sink routes 0 observations — Outlook adapter sender_dn ($2.09)
- #469: Fix: truncated DN dedup ($0.00, external contribution)
Total: 4 PRs, $9.39

## v0.26.1 (2026-10-14)
- #466: Feat: apply DN rank to maintenance.py and add split command for DN-sink entities ($3.98)
- #464: Fix: bot sender pattern misses hyphenated -commenter names ($0.67)
- #463: Feat: rank DNs below handles in _name_type_rank and block truncated-DN matches ($0.75)
- #458: Chore: enable worktree isolation for patina implement jobs ($0.00)
- #457: Fix: add external to triage_labels exclusion list ($0.00)
Total: 5 PRs, $5.40

## v0.26.0 (2026-10-13)
- #454: Feat: extraction.py + ingest.py Slack ID precedence ($1.83)
- #453: Fix: EVAL.md first-attempt chart plots false zeros for no-outcome weeks ($4.81)
- #452: Feat: preview/commit equivalence invariant for maintenance commands ($1.94)
- #451: Fix: resolve_entity_id returns wrong entity when duplicate Slack ID exists ($1.50)
- #450: Feat: shared identity fixtures + graph.py Slack ID contract ($2.34)
Total: 5 PRs, $12.42

## v0.25.2 (2026-10-11)
- #439: Docs: link JEV.md from README ($0.00)
- #437: Fix: automated Outlook senders still typed as person ($0.92)
- #436: Fix: Slack message routed to wrong person via stale handle alias ($2.75)
Total: 3 PRs, $3.67

## v0.25.1 (2026-10-10)
- #432: Fix: pin CI to Python 3.13 ($0.00)
- #431: Fix: Outlook senders get a fake slack: alias ($1.83)
- #430: Fix: dedup preview doesn't show what --confirm will do after #417 ($8.38)
Total: 3 PRs, $10.21

## v0.25.0 (2026-10-09)
- #425: Fix: entity resolve-names writes by default and misses duplicates ($3.02)
- #424: Fix: entity retype and extract --dry-run write without asking ($0.82)
- #423: Fix: shared Slack ID dedup misses 3-entity group shape ($2.68)
- #420: Fix: merge DN senders by trailing handle alias ($0.00)
Total: 4 PRs, $6.52

