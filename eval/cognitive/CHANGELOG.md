# Cognitive Changelog

## 2026-07-11
- fix: auto_close_parent.py ModuleNotFoundError in CI (PR #168)
- fix: fix: store_search fails on queries containing colons (#157) #157 ($0.67) (PR #163)
- fix: fix: resolve W-prefix Slack user IDs to display names (#158) #158 ($1.44) (PR #164)
- chore: update cognitive changelog (2026-07-11) (PR #167)
- feat: Add mpim channel discovery helper to slack_mcp.py (#160) #160 ($0.47) (PR #169)

## 2026-07-11
- fix: fix: strip CAUTION email banner from ingested external email (#154) #154 ($0.50) (PR #166)
- fix: fix: journal_search returns truncated snippets instead of fu (#156) #156 ($0.28) (PR #165)

## 2026-07-10
- fix: prevent changelog workflow from recording its own PRs (PR #155)

## 2026-07-09
- chore: update cognitive changelog (2026-07-09) (PR #152)

## 2026-07-08
- refactor: rename ai-dlc to autoloop across config, docs, and CI (PR #145)
- Removed ai-dlc (PR #146)
- docs: add required label setup instructions to autoloop.toml (PR #147)
- feat: add autoloop/init.py to scaffold autoloop onto new repos (PR #148)
- feat: add autoloop/init.py to scaffold autoloop onto new repos (PR #149)
- fix: align verify_cmd naming in triage_issues and autoloop.toml (PR #150)
- feat: add protected_paths guard to prevent builder self-modification (PR #151)

## 2026-07-08
- chore: update cognitive changelog (2026-07-08) (PR #114)
- feat: feat: add AutoLoopConfig dataclass and autoloop.toml config  (#121) #121 ($1.01) (PR #131)
- feat: Create autoloop/auto_close_parent.py with cfg.repo parameter (#127) #127 ($0.91) (PR #132)
- feat: Define cfg shape and parameterize path-only functions in ai- (#129) #129 ($1.13) (PR #133)
- feat: Add tests/autoloop/ test suite mirroring tests/ai_dlc/ (#126) #126 ($1.69) (PR #134)
- feat: feat: add autoloop/create_issue.py with config-driven repo a (#124) #124 ($1.45) (PR #135)
- feat: feat: create autoloop/triage_issues.py with config-driven pa (#123) #123 ($3.41) (PR #136)
- feat: Copy and generalize implement_issue and claude_runner into a (#122) #122 ($6.63) (PR #137)
- feat: feat: add --assignee to changelog PR creation in update_chan (#139) #139 ($0.54) (PR #140)
- feat: Add close_completed_parents() to auto-close finished parent  (#138) #138 ($1.39) (PR #141)
- feat: feat: add --version flag to autoloop scripts (#143) #143 ($1.42) (PR #144)

## 2026-07-07
- chore: update cognitive changelog (2026-07-07) (PR #112)
- feat: feat: parse Metric Target comments from issues and strip the (#82) #82 ($0.92) (PR #109)
- chore: bump version to 0.7.0 (PR #113)

## 2026-07-07
- feat: Implement collect_tool_reliability() in eval/cognitive/run.p (#88) #88 ($0.93) (PR #99)
- feat: Add post-merge step to ai-dlc-cleanup.yml that invokes updat (#84) #84 ($1.22) (PR #100)
- feat: Implement collect_merge_rate() and collect_time_to_implement (#86) #86 ($1.11) (PR #101)
- feat: Wire main() to merge all three collectors into EvalSnapshot  (#89) #89 ($1.88) (PR #102)
- feat: Auto-bump pyproject.toml version on PR merge by commit prefi (#78) #78 ($0.82) (PR #103)
- feat: Add session start directives to agent operational instructio (#77) #77 ($0.47) (PR #104)
- feat: feat: add file-issue skill to capture conversation context i (#74) #74 ($4.35) (PR #105)
- feat: feat: implement compare.py delta reporter with non-zero exit (#80) #80 ($0.69) (PR #106)
- chore: gitignore run_history.jsonl (PR #107)
- feat: feat: add post-merge hook script that runs run.py then compa (#81) #81 ($2.36) (PR #108)
- feat: add cron-based changelog update script (PR #110)
- feat: changelog script creates PR instead of pushing directly to main (PR #111)

## 2026-07-06
- chore: bump version to 0.6.0 (PR #72)
- feat: feat: add --version flag to ai-dlc scripts (#71) #71 ($0.98) (PR #73)
- fix: infinite loop on blocked issue (PR #90)
- feat: feat: ensure clean main branch state before each issue in ba (#94) #94 ($1.84) (PR #96)
- feat: feat: filter unmet dependencies in select_top_issue() (#93) #93 ($1.85) (PR #97)
- feat: feat: auto-unblock issues when dependencies are resolved (#95) #95 ($2.61) (PR #98)
- feat: Define EvalSnapshot Pydantic schema in eval/cognitive/__init (#85) #85 ($1.11) (PR #92)
- feat: Create eval/cognitive/update_changelog.py with append and tr (#83) #83 ($0.72) (PR #91)

## 2026-07-05
- feat: test: VPS builder smoke test (#69) #69 ($0.96) (PR #70)

## 2026-07-04
- Set default builder model to claude opus 4.6 1M context window (PR #68)

## 2026-07-03
- feat: feat: add --issue flag to implement_issue.py for targeted is (#36) #36 (PR #37)
- feat: feat: replace flat-rate cost estimates with real token usage (#28) #28 (PR #38)
- feat: feat: auto-create sub-issues on needs-decomposition verdict (#29) #29 ($0.94) (PR #39)
- feat: feat: group sub-issues by parent in get_top_ready_issue() (#41) #41 ($0.75) (PR #42)
- feat: Generate LLM-enriched fields for sub-issues on decomposition (#46) #46 ($1.83) (PR #47)
- Enhanced ai-dlc-cleanup logic (PR #48)
- feat: feat: add design_issue() function to AI-DLC with subprocess  (#43) #43 ($0.85) (PR #51)
- feat: feat: add design gate logic to implement_issue.py (flag, lab (#44) #44 ($1.62) (PR #54)
- feat: test: cover all design-gate acceptance criteria scenarios (#45) #45 ($0.78) (PR #58)
- feat: Implement auto-close helpers: parse parent reference from su (#56) #56 ($0.88) (PR #59)
- feat: Wire auto-close step into ai-dlc-cleanup.yml on pull_request (#57) #57 ($0.65) (PR #60)
- feat: feat: prioritize standalone issues over lower-priority sub-i (#52) #52 ($0.40) (PR #61)
- feat: feat: add journal directives to _OPERATIONAL_INSTRUCTIONS (#50) #50 ($0.38) (PR #62)
- feat: Add journal memory directives to SOUL.md init template (#49) #49 ($0.34) (PR #63)
- feat: feat: auto-assign PRs and post bot comment on issue claim (#53) #53 ($0.99) (PR #64)
- feat: feat: auto-fix rejected issues in triage bot (#33) #33 ($1.63) (PR #65)
- feat: feat: include project tree and CLAUDE.md in triage prompt (#32) #32 ($0.82) (PR #66)
- feat: feat: add semantic review step to AI-DLC pipeline (#31) #31 ($2.26) (PR #67)

## 2026-07-02
- Add core specs to repo (PR #25)
- feat: Make AI-DLC model and timeout configurable via env vars (#15) #15 (PR #24)
- feat: Feed Errors Back on Retry (#14) #14 (PR #26)
- Merged enhancement spec to ai-dlc-v2 spec doc (PR #27)
- feat: Remove in-review label from issues when their PR is merged (#34) #34 (PR #35)

## 2026-07-01
- Refactored AI-DLC scripts (PR #19)
- feat: Track timing, Claude call count, and cost estimate per AI-DL (#17) #17 (PR #20)
- Added PR token usage cost (PR #21)
- feat: Pull latest main before creating feature branch (#18) #18 (PR #22)
- feat: Add --max-issues flag to implement_issue.py for batch proces (#16) #16 (PR #23)
- #185: feat: daily changelog + version bump via PR, auto-tag on merge ($0.0) [2026-07-13]
- #183: feat: feat: configurable lookback window for ingest backfill (#175) ($0.71) [2026-07-13]
- #182: feat: Add integration tests for DM backfill path (6 acceptance cri (#179) ($1.27) [2026-07-13]
- #181: feat: Add `list_dms()` method and `DmChannel` model to `slack_mcp. (#176) ($0.49) [2026-07-13]
- #180: feat: Add DM backfill loop with 180-day stale cutoff to ingest_liv (#178) ($1.09) [2026-07-13]
- #173: refactor: remove in-tree autoloop, use standalone package ($0.0) [2026-07-13]
- #171: feat: Add unit tests for auto-watch behavior (#162) ($0.93) [2026-07-13]
- #170: feat: Wire auto-watch into ingest pipeline with dedup guard (#161) ($1.19) [2026-07-13]
- #169: feat: Add mpim channel discovery helper to slack_mcp.py (#160) ($0.47) [2026-07-13]
- #168: fix: auto_close_parent.py ModuleNotFoundError in CI ($0.0) [2026-07-13]
- #166: fix: fix: strip CAUTION email banner from ingested external email (#154) ($0.5) [2026-07-13]
- #165: fix: fix: journal_search returns truncated snippets instead of fu (#156) ($0.28) [2026-07-13]
- #164: fix: fix: resolve W-prefix Slack user IDs to display names (#158) ($1.44) [2026-07-13]
- #163: fix: fix: store_search fails on queries containing colons (#157) ($0.67) [2026-07-13]
- #155: fix: prevent changelog workflow from recording its own PRs ($0.0) [2026-07-13]
- #151: feat: add protected_paths guard to prevent builder self-modification ($0.0) [2026-07-13]
- #150: fix: align verify_cmd naming in triage_issues and autoloop.toml ($0.0) [2026-07-13]
- #149: feat: add autoloop/init.py to scaffold autoloop onto new repos ($0.0) [2026-07-13]
- #148: feat: add autoloop/init.py to scaffold autoloop onto new repos ($0.0) [2026-07-13]
- #147: docs: add required label setup instructions to autoloop.toml ($0.0) [2026-07-13]
- #146: Removed ai-dlc ($0.0) [2026-07-13]
- #145: refactor: rename ai-dlc to autoloop across config, docs, and CI ($0.0) [2026-07-13]
- #144: feat: feat: add --version flag to autoloop scripts (#143) ($1.42) [2026-07-13]
- #141: feat: Add close_completed_parents() to auto-close finished parent  (#138) ($1.39) [2026-07-13]
- #140: feat: feat: add --assignee to changelog PR creation in update_chan (#139) ($0.54) [2026-07-13]
- #137: feat: Copy and generalize implement_issue and claude_runner into a (#122) ($6.63) [2026-07-13]
- #136: feat: feat: create autoloop/triage_issues.py with config-driven pa (#123) ($3.41) [2026-07-13]
- #135: feat: feat: add autoloop/create_issue.py with config-driven repo a (#124) ($1.45) [2026-07-13]
- #134: feat: Add tests/autoloop/ test suite mirroring tests/ai_dlc/ (#126) ($1.69) [2026-07-13]
- #133: feat: Define cfg shape and parameterize path-only functions in ai- (#129) ($1.13) [2026-07-13]
- #132: feat: Create autoloop/auto_close_parent.py with cfg.repo parameter (#127) ($0.91) [2026-07-13]
- #131: feat: feat: add AutoLoopConfig dataclass and autoloop.toml config  (#121) ($1.01) [2026-07-13]
- #111: feat: changelog script creates PR instead of pushing directly to main ($0.0) [2026-07-13]
- #110: feat: add cron-based changelog update script ($0.0) [2026-07-13]
- #109: feat: feat: parse Metric Target comments from issues and strip the (#82) ($0.92) [2026-07-13]
- #108: feat: feat: add post-merge hook script that runs run.py then compa (#81) ($2.36) [2026-07-13]
- #106: feat: feat: implement compare.py delta reporter with non-zero exit (#80) ($0.69) [2026-07-13]
- #105: feat: feat: add file-issue skill to capture conversation context i (#74) ($4.35) [2026-07-13]
- #104: feat: Add session start directives to agent operational instructio (#77) ($0.47) [2026-07-13]
- #103: feat: Auto-bump pyproject.toml version on PR merge by commit prefi (#78) ($0.82) [2026-07-13]
- #102: feat: Wire main() to merge all three collectors into EvalSnapshot  (#89) ($1.88) [2026-07-13]
- #101: feat: Implement collect_merge_rate() and collect_time_to_implement (#86) ($1.11) [2026-07-13]
- #192: feat: docs: add anonymization rule to CLAUDE.md conventions (#190) ($0.5) [2026-07-14]
- #191: feat: fix: migrate existing observations to restore datamarked whi (#188) ($0.78) [2026-07-14]
- #189: feat: fix: restore datamarked whitespace (\uE000) to spaces in Sla (#187) ($0.32) [2026-07-14]
