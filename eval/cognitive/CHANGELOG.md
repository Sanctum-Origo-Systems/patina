## v0.29.0 (2026-10-19)
- #487: Fix: slack_live sender_slack_id guard inconsistency and weak test ($2.98)
- #484: Feat: Fix backfill channel-peer DN logic in backfill.py and add pr ($2.16)
Total: 2 PRs, $5.14

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

## v0.24.0 (2026-10-08)
- #414: Fix: empty-text Slack messages never leave unprocessed ($1.15)
- #410: Fix: pre-#399 junk senders remain in store ($2.17)
- #411: Fix: organizations, lists and roles saved as people ($3.08)
- #412: Fix: extraction creates single-word people — places and first names ($1.43)
- #413: Fix: duplicates that share a Slack ID are stuck in SKIP ($2.57)
- #409: Fix: people stay named by a raw Slack ID ($3.38)
- #401: Fix: Outlook adapter creates junk sender entities ($2.68)
- #400: Fix: ingest overwrites merged entities' name and aliases ($1.71)
Total: 8 PRs, $18.17

## v0.23.0 (2026-10-06)
- #394: Fix: entity cleanup nulls dangling sender_entity_id refs ($1.20)
- #393: Fix: route handle-alias merge to REVIEW when target has no Slack ID ($3.53)
- #395: Fix: validate _collect_slack_ids captures against _SLACK_ID_RE ($1.52)
- #387: Feat: REVIEW reason shows wrong label for ambiguous-handle entries ($0.79)
- #386: Fix: foreign-handle exemption lets handle-named entity merge thro ($2.23)
Total: 5 PRs, $9.27

## v0.22.0 (2026-10-05)

### Dedup Safety (continued)
- #384: Fix: restrict foreign-handle exemption to full-name entities
- #385: Fix: REVIEW reason shows correct label for ambiguous-handle entries

### Testing & Dashboard
- #367: Feat: invariants test module and process-rule documentation
- #383: Chore: refresh EVAL.md with short date labels (MM-DD)

