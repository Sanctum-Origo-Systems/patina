## v0.9.0 (2026-07-14)
- #192: Feat: docs: add anonymization rule to CLAUDE.md conventions ($0.50)
- #191: Feat: fix: migrate existing observations to restore datamarked whi ($0.78)
- #189: Feat: fix: restore datamarked whitespace () to spaces in Sla ($0.32)
Total: 3 PRs, $1.60

## v0.8.0 (2026-07-13)
- #185: Feat: daily changelog + version bump via PR, auto-tag on merge ($0.00)
- #183: Feat: configurable lookback window for ingest backfill ($0.71)
- #182: Feat: Add integration tests for DM backfill path (6 acceptance cri ($1.27)
- #181: Feat: Add `list_dms()` method and `DmChannel` model to `slack_mcp. ($0.49)
- #180: Feat: Add DM backfill loop with 180-day stale cutoff to ingest_liv ($1.09)
- #173: Refactor: remove in-tree autoloop, use standalone package ($0.00)
- #171: Feat: Add unit tests for auto-watch behavior ($0.93)
- #170: Feat: Wire auto-watch into ingest pipeline with dedup guard ($1.19)
- #169: Feat: Add mpim channel discovery helper to slack_mcp.py ($0.47)
- #168: Fix: auto_close_parent.py ModuleNotFoundError in CI ($0.00)
- #167: Chore: update cognitive changelog (2026-07-11) ($0.00)
- #166: Fix: strip CAUTION email banner from ingested external email ($0.50)
- #165: Fix: journal_search returns truncated snippets instead of fu ($0.28)
- #164: Fix: resolve W-prefix Slack user IDs to display names ($1.44)
- #163: Fix: store_search fails on queries containing colons ($0.67)
- #155: Fix: prevent changelog workflow from recording its own PRs ($0.00)
- #152: Chore: update cognitive changelog (2026-07-09) ($0.00)
- #151: Feat: add protected_paths guard to prevent builder self-modification ($0.00)
- #150: Fix: align verify_cmd naming in triage_issues and autoloop.toml ($0.00)
- #149: Feat: add autoloop/init.py to scaffold autoloop onto new repos ($0.00)
- #148: Feat: add autoloop/init.py to scaffold autoloop onto new repos ($0.00)
- #147: Docs: add required label setup instructions to autoloop.toml ($0.00)
- #146: Removed ai-dlc ($0.00)
- #145: Refactor: rename ai-dlc to autoloop across config, docs, and CI ($0.00)
- #144: Feat: add --version flag to autoloop scripts ($1.42)
- #141: Feat: Add close_completed_parents() to auto-close finished parent ($1.39)
- #140: Feat: add --assignee to changelog PR creation in update_chan ($0.54)
- #137: Feat: Copy and generalize implement_issue and claude_runner into a ($6.63)
- #136: Feat: create autoloop/triage_issues.py with config-driven pa ($3.41)
- #135: Feat: add autoloop/create_issue.py with config-driven repo a ($1.45)
- #134: Feat: Add tests/autoloop/ test suite mirroring tests/ai_dlc/ ($1.69)
- #133: Feat: Define cfg shape and parameterize path-only functions in ai- ($1.13)
- #132: Feat: Create autoloop/auto_close_parent.py with cfg.repo parameter ($0.91)
- #131: Feat: add AutoLoopConfig dataclass and autoloop.toml config ($1.01)
- #114: Chore: update cognitive changelog (2026-07-08) ($0.00)
Total: 35 PRs, $28.62

## v0.7.0 (2026-07-07)
- #113: Chore: bump version to 0.7.0 ($0.00)
- #112: Chore: update cognitive changelog (2026-07-07) ($0.00)
- #111: Feat: changelog script creates PR instead of pushing directly to main ($0.00)
- #110: Feat: add cron-based changelog update script ($0.00)
- #109: Feat: parse Metric Target comments from issues and strip the ($0.92)
- #108: Feat: add post-merge hook script that runs run.py then compa ($2.36)
- #107: Chore: gitignore run_history.jsonl ($0.00)
- #106: Feat: implement compare.py delta reporter with non-zero exit ($0.69)
- #105: Feat: add file-issue skill to capture conversation context i ($4.35)
- #104: Feat: Add session start directives to agent operational instructio ($0.47)
- #103: Feat: Auto-bump pyproject.toml version on PR merge by commit prefi ($0.82)
- #102: Feat: Wire main() to merge all three collectors into EvalSnapshot ($1.88)
- #101: Feat: Implement collect_merge_rate() and collect_time_to_implement ($1.11)
- #100: Feat: Add post-merge step to ai-dlc-cleanup.yml that invokes updat ($1.22)
- #99: Feat: Implement collect_tool_reliability() in eval/cognitive/run.p ($0.93)
- #98: Feat: auto-unblock issues when dependencies are resolved ($2.61)
- #97: Feat: filter unmet dependencies in select_top_issue() ($1.85)
- #96: Feat: ensure clean main branch state before each issue in ba ($1.84)
- #92: Feat: Define EvalSnapshot Pydantic schema in eval/cognitive/__init ($1.11)
- #91: Feat: Create eval/cognitive/update_changelog.py with append and tr ($0.72)
- #90: Fix: infinite loop on blocked issue ($0.00)
- #73: Feat: add --version flag to ai-dlc scripts ($0.98)
- #72: Chore: bump version to 0.6.0 ($0.00)
Total: 23 PRs, $23.86

## v0.6.0 (2026-07-05)
- #70: Feat: test: VPS builder smoke test ($0.96)
- #68: Set default builder model to claude opus 4.6 1M context window ($0.00)
- #67: Feat: add semantic review step to AI-DLC pipeline ($2.26)
- #66: Feat: include project tree and CLAUDE.md in triage prompt ($0.82)
- #65: Feat: auto-fix rejected issues in triage bot ($1.63)
- #64: Feat: auto-assign PRs and post bot comment on issue claim ($0.99)
- #63: Feat: Add journal memory directives to SOUL.md init template ($0.34)
- #62: Feat: add journal directives to _OPERATIONAL_INSTRUCTIONS ($0.38)
- #61: Feat: prioritize standalone issues over lower-priority sub-i ($0.40)
- #60: Feat: Wire auto-close step into ai-dlc-cleanup.yml on pull_request ($0.65)
- #59: Feat: Implement auto-close helpers: parse parent reference from su ($0.88)
- #58: Feat: test: cover all design-gate acceptance criteria scenarios ($0.78)
- #54: Feat: add design gate logic to implement_issue.py (flag, lab ($1.62)
- #51: Feat: add design_issue() function to AI-DLC with subprocess ($0.85)
- #48: Enhanced ai-dlc-cleanup logic ($0.00)
- #47: Feat: Generate LLM-enriched fields for sub-issues on decomposition ($1.83)
- #42: Feat: group sub-issues by parent in get_top_ready_issue() ($0.75)
- #39: Feat: auto-create sub-issues on needs-decomposition verdict ($0.94)
- #38: Feat: replace flat-rate cost estimates with real token usage ($0.00)
- #37: Feat: add --issue flag to implement_issue.py for targeted is ($0.00)
- #35: Feat: Remove in-review label from issues when their PR is merged ($0.00)
- #27: Merged enhancement spec to ai-dlc-v2 spec doc ($0.00)
- #26: Feat: Feed Errors Back on Retry ($0.00)
- #25: Add core specs to repo ($0.00)
- #24: Feat: Make AI-DLC model and timeout configurable via env vars ($0.00)
Total: 25 PRs, $16.08

## v0.5.0 (2026-07-01)
- #23: Feat: Add --max-issues flag to implement_issue.py for batch proces ($0.00)
- #22: Feat: Pull latest main before creating feature branch ($0.00)
- #21: Added PR token usage cost ($0.00)
- #20: Feat: Track timing, Claude call count, and cost estimate per AI-DL ($0.00)
- #19: Refactored AI-DLC scripts ($0.00)
Total: 5 PRs, $0.00
## v0.10.0 (2026-07-30)
- #217: Fix: list_channel_messages fetches only the first page — no ($1.12)
- #216: Feat: Wire discovery stats and streak warning into CLI summary and ($1.42)
- #213: Feat: fix: changelog automation creates duplicate PRs when previou ($0.79)
- #212: Fix: list_dms timestamp field name mismatch — all DMs treate ($0.70)
- #211: Feat: Add discovery_zero_streak persistence and counter logic in i ($0.80)
- #210: Feat: fix: recent_messages queries observations by channel_id inst ($0.82)
Total: 6 PRs, $5.65
## v0.14.0 (2026-08-05)
- #237: Feat: docs: reframe README from assistant to cognitive framework + ($0.48)
Total: 1 PRs, $0.48

## v0.13.0 (2026-08-04)
- #234: Feat: fix: remove autoloop from Python dependencies — it's a CLI t ($0.61)
Total: 1 PRs, $0.61

## v0.12.0 (2026-08-01)
- #231: Feat: fix: store_search uses phrase matching for multi-word querie ($0.56)
- #228: Feat: docs: add autoloop reference to README ($0.40)
- #227: Feat: refactor: clean PR titles, add version-grouped format, and u ($4.64)
Total: 3 PRs, $5.60

## v0.11.0 (2026-07-31)
- #225: Feat: Consolidate ingest.py to single list_dms call for DM fetching ($2.16)
- #221: Feat: Remove conversations_list adapter methods and update adapter ($0.90)
Total: 2 PRs, $3.06

## v0.15.0 (2026-08-14)
- #242: Feat: fix: rebuild journal_fts index for pre-existing entries ($0.82)
- #240: Feat: fix: journal_search has same phrase-matching limitation as s ($0.72)
Total: 2 PRs, $1.54

## v0.16.0 (2026-08-25)
- #273: Feat: auto_resolve_draft_reply: add lower-similarity floor so unre ($1.31)
- #271: Feat: Auto-resolve proposed draft_reply actions on owner-sent mess ($3.40)
- #270: Feat: Reaction backfill reads wrong field (name vs emoji) — insert ($1.03)
- #269: Feat: Persist draft_text in draft_reply action payload at propose ($0.50)
- #263: Feat: _obs_id mishandles NULL channel_id (one-line fix, no migrati ($0.38)
- #261: Feat: Observation ids not re-keyed to new identity scheme after #2 ($4.13)
- #259: Feat: Source-family normalization: key observation identity on fam ($2.22)
- #258: Feat: Outlook adapter: skip meeting-request items at ingest time ( ($0.69)
- #254: Feat: Backfill decisions from historical reactions (seed act-on ra ($1.48)
- #253: Feat: Observation dedup keys on channel_id, which is unstable — sa ($1.46)
- #252: Feat: Migration: de-duplicate existing observation rows (channel_i ($2.75)
- #251: Feat: Fix reject/edit signal capture: record decisions rows for re ($0.62)
- #250: Feat: Wire draft_reply → propose_action to populate action_queue + ($1.91)
Total: 13 PRs, $21.88

## v0.17.0 (2026-09-06)
- #278: Feat: store_search AND-joins query terms — multi-word queries sile ($0.70)
- #277: Feat: p0: daily changelog job bumps pyproject version but never sy ($1.20)
Total: 2 PRs, $1.90

## v0.18.0 (2026-09-09)
- #281: Feat: journal_search AND-joins query terms and has no recency mode ($0.64)
Total: 1 PRs, $0.64

## v0.18.2 (2026-09-21)
- #291: Fix: exclude relay label from triage pipeline ($0.00)
Total: 1 PRs, $0.00

## v0.18.1 (2026-09-20)
- #285: Docs: add EVAL.md dashboard link to README ($0.00)
Total: 1 PRs, $0.00

## v0.18.3 (2026-09-24)
- #296: Fix: backfill eval snapshots with PR-based implementations ($0.00)
- #299: Chore: regenerate EVAL.md with corrected metrics ($0.00)
- #300: Chore: set auto-merge promotion level to repo ($0.00)
Total: 3 PRs, $0.00

## v0.19.0 (2026-09-28)
- #320: Feat: Update autonomy status CLI and MCP tool to display per-domai ($1.18)
- #319: Feat: Scope tracker demotion/freeze to domain and map action types ($1.32)
- #318: Fix: Add owner merge/repair command to fold duplicate self-entiti ($1.49)
- #317: Fix: Fix _ingest_messages() to resolve owner identity on every in ($1.69)
- #316: Feat: entity & data maintenance CLI (merge, dedup, prune non-perso ($6.85)
- #314: Fix: Normalize alias prefixes and extend owner identifier config ($1.44)
- #313: Feat: Migrate autonomy_state schema to domain-keyed and update cor ($2.21)
Total: 7 PRs, $16.18

## v0.19.2 (2026-09-30)
- #326: Fix: replace substring LIKE fallback with owner-aware entity resolution ($0.00)
Total: 1 PRs, $0.00

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

## v0.21.0 (2026-10-04)

### Dedup Safety & Correctness
- #372: Fix: dedup ignores contaminated bare Slack IDs and uses name-type ranking for canonical direction
- #373: Fix: restore correct handle-to-full-name merges lost by is_foreign_handle
- #364: Fix: dedup merges different people through contaminated handle aliases
- #359: Fix: dedup canonical direction prefers full name over handle

### Entity Quality
- #363: Fix: is_plausible_person_name split — handle check removed from shared function
- #374: Fix: tighten Slack ID regex to reject uppercase words like URGENT
- #358: Fix: entity prune --non-person protects handle-named senders

### Testing Infrastructure
- #366: Feat: seeded in-memory store fixture covering all known edge-case shapes
- #367: Feat: invariants test module and process-rule documentation

### Config
- #368: Chore: add review-queue to triage_labels exclusion list

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

## v0.26.0 (2026-10-13)
- #454: Feat: extraction.py + ingest.py Slack ID precedence ($1.83)
- #453: Fix: EVAL.md first-attempt chart plots false zeros for no-outcome weeks ($4.81)
- #452: Feat: preview/commit equivalence invariant for maintenance commands ($1.94)
- #451: Fix: resolve_entity_id returns wrong entity when duplicate Slack ID exists ($1.50)
- #450: Feat: shared identity fixtures + graph.py Slack ID contract ($2.34)
Total: 5 PRs, $12.42

## v0.26.1 (2026-10-14)
- #466: Feat: apply DN rank to maintenance.py and add split command for DN-sink entities ($3.98)
- #464: Fix: bot sender pattern misses hyphenated -commenter names ($0.67)
- #463: Feat: rank DNs below handles in _name_type_rank and block truncated-DN matches ($0.75)
- #458: Chore: enable worktree isolation for patina implement jobs ($0.00)
- #457: Fix: add external to triage_labels exclusion list ($0.00)
Total: 5 PRs, $5.40

