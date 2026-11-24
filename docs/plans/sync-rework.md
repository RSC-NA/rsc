# Sync rework plan

Status on 2026-11-24. In progress. The stack is A1 (PR 34), A2 (PR 36), B (PR 37), the captain fix (PR 41), the GM cut fix (PR 42), then C, which is being built, then D. The GM check for `/admin sync nonplaying` is PR 44, beside B. The sign-ups-closed fix is PR 40, off `master`. Nothing lands until the stack through D is built. The hand-run checks are in `docs/plans/sync-rework-test-checklist.md`. Appendix F records the rulings and Appendix G records what execution found.

The Discord sync commands and the nightly task get three changes for league staff and members.
They read the right season's rows, so a member who has not declared intent yet is never stripped.
They send one Discord request per changed member and report what they did.
The nightly run moves a member to non-playing only after a declared "not returning" or after sign-ups close.
G reacts to website change events and stays blocked until the website emits them.
The rule for every PR is that a sync run twice in a row makes no second write.
PR ids in order are A1, A2, B, C, D, E, F, G.

## How to read this

One box is one unit of work. Every box names the evidence that checks it. A nested box is a sub-step of the box above it. Check a box only when its evidence exists, a file, a log line, a screenshot, a test run, or a SHA. The body is a how-to. The appendices explain and record.

The program runs `playbooks/autopilot-stack.md` from the pstack plugin (`~/.claude/plugins/cache/cursor-plugins/pstack/0.15.36/skills/poteto-mode/playbooks/autopilot-stack.md`). The operator lands every PR. Every PR stops at merge-ready. E is also review-gated.

Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

## Program checklist

### Arm the program

- [ ] State the protocol and this plan to the operator, then stop. Start execution only on the operator's explicit go.
- [ ] Read these at program start. Re-read them at every tick. The playbook's `git show origin/main:` lines do not apply, because this repo's trunk is `master` and pstack lives in the plugin cache. Read each file from `~/.claude/plugins/cache/cursor-plugins/pstack/0.15.36/skills/`.
  - [ ] `poteto-mode/playbooks/autopilot-stack.md` and `poteto-mode/playbooks/autopilot-full.md`
  - [ ] `swarm/SKILL.md`
  - [ ] `poteto-mode/playbooks/opening-a-pr.md`
  - [ ] `docs/development.md` in this repo, for the test bot and the test server
- [ ] On the operator's go, arm the audit tick as `/loop 1h` with the tick prompt below. Never leave the cadence to memory.
- [ ] Use this tick prompt, verbatim. "Re-read the execution playbook. Audit the operation against it and fix drift in this tick. Probe every active lane and judge progress by side effects only. Stand down a stuck lane and dispatch its replacement now. Then post a short status message to the operator in chat only when the audit found a tracked change that no earlier status message reported, such as a PR opened, a code-ready head, a round launched or closed, a verdict, a stuck agent and the action taken, a blocker added or cleared, or a decision only the operator can make. Name every such change and nothing else. If the audit found none, end the turn with no reply text. Either way, log this tick's row in your decision trail."
- [ ] On the operator's hold or stand-down, send every owner a zero-writes order at once.

### Spawn owners

- [ ] Spawn one owner per PR with the full lifecycle the execution playbook names.
- [ ] Follow this dependency graph. A dependent PR is based on its parent's branch.
  - [ ] A1 is first and branches from `master`. It ships first because 858 members are exposed today.
  - [ ] A2 after A1. B after A2. C after B. D after C. E after D. F after E.
  - [ ] G after E, and only after website issue 233 ships and staging emits the events. Until then G stays unstarted and does not block the program's close.
- [ ] Hold the file boundaries. A1 owns the season lookup in `rsc/leagues/` and its callers in `rsc/admin/sync.py`. A2 owns `rsc/transactions/roles.py` and the intent flow in `rsc/members/members.py`. No PR touches the website repo. The website work is the issue in Appendix D.
- [x] File the website issue from `docs/plans/sync-rework-evidence/website-issue-draft.md` on `RSC-NA/web-rsc-website`. Filed on 2026-11-23 as https://github.com/RSC-NA/web-rsc-website/issues/233.
- [ ] Hold the review gate. E changes what staff see in Discord. E waits for the operator's review in chat with screenshots and a video before merge.
- [ ] Never start a second copy of the test bot. Check `pgrep -f "redbot rsc"` and port 8008 first. Never run a lane against the production bot.

### PR mechanics, for every PR

- [ ] Use `gh` for every PR operation.
- [ ] Open the PR ready, never draft, with `gh pr create --base <base-branch>`. A stack child targets its parent branch.
- [ ] Run `uv run ruff check .`, `uv run ruff format --check .` and `uv run ty check` once before the PR-facing push. Never use mypy. Never use `typing.cast()`. Push with hooks on.
- [ ] Run `/deslop` before each commit and `/no-comments` before review.
- [ ] Run the `update-module-docs` skill when a PR changes a command, a task loop, or a Config key.
- [ ] This repo has no Bugbot check. Record the skip in the PR's trail.
- [ ] Rebase onto current `master` before the code-ready report. Keep that merge base in fix rounds.

### Verdict and merge, for every PR

- [ ] A full swarm runs once, at the code-ready head. It has one gates lane, the ten live lanes from the PR's **Verify, live** block, the perf lane from its **Verify, perf** block, and two audit lanes that read the diff and distrust the PR body.
- [ ] A rebase or a minor fix gets a single verifier at the new head. A wording-only change gets none.
- [ ] Judge every finding by the execution playbook's blocking rule. A failure on trunk behavior in the lane marked `Regression lane against trunk.` is recorded against trunk and does not block the PR.
- [ ] Stop at verified. Hand the PR to the operator. Nobody pushes after the handoff without the operator's go.

### Boot recipe, for every live lane

Discord has no control skill, so each lane names its driver. The drivers are a read-only probe of the live API, the lab script on the test server, and the operator's own slash command on the test server. Lanes run one at a time because the test bot runs as one instance.

- [ ] `git fetch origin <head-branch> && git checkout <head SHA>`, then `uv sync`.
- [ ] For a probe lane, run `uv run python scripts/sync_season_probe.py` with `RSC_API_KEY` set. The probe sends GET requests only.
- [ ] For a lab lane, stop the dev bot, then run `uv run python scripts/sync_lab.py <scenario>`. The lab logs in as the test bot, sets the lab member's starting roles on the test server, runs the scenario, reads the member back from Discord, and prints the requests it sent.
- [ ] For an operator lane, start the test bot with `uv run redbot rsc --dev --debug`, reload the cog, and ask the operator to run the command. The operator saves the screenshot.
- [ ] Save every artifact to `/tmp/swarm-<pr-id>/worker-<n>/<slug>` and return the paths with the report.

## Read the right season's rows in every sync (A1)

**Depends on.** None.

**Files.**

- [ ] Edit `rsc/leagues/leagues.py`.
- [ ] Edit `rsc/admin/sync.py`.
- [ ] Create `rsc/leagues/effective.py`.
- [ ] Create `scripts/sync_season_probe.py` from `docs/plans/sync-rework-evidence/probe_overlap.py.txt`.
- [ ] Edit `tests/test_admin_sync.py`. Create `tests/test_effective_player.py`.

**Build.**

- [ ] Add the pure function `pick_effective_row(rows, seasons, now, signups_open)` in `rsc/leagues/effective.py`. It takes one member's rows from at most two seasons and returns one row or `None`. The rule has three steps in order. A rostered row (RO, RN, IR, AR, UG) in a season whose `end_date` has not passed wins. Otherwise the newest season's row wins. Otherwise the older season's row wins while its own season has not ended. Otherwise the older season's row wins while sign-ups for the newer season are open, unless the member declared "not returning". `None` means non-playing. So a member with an active older row becomes non-playing in two cases only, and only after that row's season has ended. The cases are a declared "not returning" and closed sign-ups.
- [ ] Add `effective_players(guild)` and `effective_player(guild, discord_id)` in `rsc/leagues/leagues.py`. They read the default season. While `next_signup_season` returns a season, they also read that season and the season numbered one below it. They treat the API's 404 for no open sign-ups as "no sign-up season". While sign-ups are open they also read `player_intents` for the sign-up season once per run. A declared "not returning" is an intent row with `missing` false and `returning` false. A row with `missing` true is no declaration.
- [ ] Replace `paged_players(guild=guild)` with `effective_players(guild)` in the nightly task and in `/admin sync players`.
- [ ] Replace the `players(guild, discord_id=member.id, limit=1)` lookup in `/admin sync member` with `effective_player`.
- [ ] In `/admin sync nonplaying`, replace the `league_player_from_member` test with a lookup in the `effective_players` set. A member with an effective row that is not DR, FR, or BN is playing.
- [ ] Catch `discord.HTTPException` per member in the nightly loop, log the member and the error, and continue. Move the literal guild id into the module constant `NIGHTLY_GUILD_ID`.

**You see.**

- [ ] `uv run python scripts/sync_season_probe.py` prints `stripped by nonplaying while sign-ups are open` with the value 0. On trunk the same line prints 858 (measured 2026-11-23 19:59 UTC).
- [ ] The nightly log shows `Finished syncing league players` on a night when one member's role write failed, with one warning that names the member.

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] `tests/test_effective_player.py` gains one case per rule step, one case per row of the cross-tab in Appendix A, one case for closed sign-ups, one for a declared "not returning", and one for an intent row with `missing` true. Run `uv run pytest tests/test_effective_player.py`.
- [ ] `tests/test_admin_sync.py` gains a case where `/admin sync nonplaying` leaves a member who holds only an older-season RO row, and a case where the nightly loop continues after `discord.Forbidden`. Run `uv run pytest tests/test_admin_sync.py`.

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Ten lanes on `inherit-parent` at the PR head, per the boot recipe.

- [ ] Lane 1. Regression lane against trunk. Probe lane. Count the members that `/admin sync nonplaying` would treat as non-playing among members with an active S27 row, at trunk and at head. Save `a1-regression.log`. Pass when trunk reports the count the probe measures that day (858 on 2026-11-23) and head reports 0.
- [ ] Lane 2. Probe lane. Resolve every member who has an S28 row. Save `a1-newest-wins.log`. Pass when every one resolves to the S28 row.
- [ ] Lane 3. Probe lane. Resolve every member whose only row is S27 with status DR or FR. Save `a1-gone.log`. Pass when every one counts as non-playing.
- [ ] Lane 4. Probe lane with S27's end date moved into the future in memory. Save `a1-preflip.log`. Pass when every RO to FA member resolves to the S27 row and every PF to DE member resolves to the S28 row.
- [ ] Lane 5. Probe lane with sign-ups marked closed in memory. Save `a1-closed.log`. Pass when no member resolves to an S27 row.
- [ ] Lane 6. Probe lane. Resolve every member with an S27-only active row and a declared "not returning" for S28. Save `a1-not-returning.log`. Pass when every one resolves to non-playing once S27 has ended (15 members on 2026-11-24) and no member with `missing` true does.
- [ ] Lane 7. Operator lane. Run `/admin sync member` on the test server for a member with a league player row. Save `a1-member-row.png`. Pass when the reply is the success card and the member's roles are unchanged.
- [ ] Lane 8. Operator lane. Run `/admin sync member` for a member with no row in any season. Save `a1-member-none.png`. Pass when the member loses league roles and gets the welcome roles.
- [ ] Lane 9. Operator lane. Run `/admin sync nonplaying dryrun:True` on the test server. Save `a1-nonplaying-dry.png`. Pass when the run finishes and no member's roles change.
- [ ] Lane 10. Operator lane. From `[p]eval` on the test bot, set `rsc.admin.sync.NIGHTLY_GUILD_ID` to the test server and run the nightly body with one member whose franchise role sits above the bot's top role. Save `a1-nightly-isolation.log`. Pass when the log has one warning for that member and `Finished syncing league players`.

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. API pages and wall time for the player read of one sync, at trunk and at head, against the live API.
- [ ] Probe. `uv run python scripts/sync_season_probe.py --time`, three runs each at trunk and head, interleaved.
- [ ] Baseline. Record the trunk value first. Trunk read 1 page of 369 rows on 2026-11-23.
- [ ] Rule. Head reads at most 4 pages plus one intents request. The PR fails when head reads more than 6 pages or the median read takes more than 10 s.

**Review gate.** None. A1 is not review-gated.

**Merge.**

- [ ] Root's clean verdict at the exact head SHA.
- [ ] Rebased onto current `master` after the verdict, patch-id unchanged.
- [ ] The operator lands it and deploys before anyone runs `/admin sync nonplaying` on production.

## Keep the franchise tag on AGMs and close three role gaps (A2)

**Depends on.** A1.

**Files.**

- [ ] Edit `rsc/transactions/roles.py`.
- [ ] Edit `rsc/members/members.py`.
- [ ] Edit `tests/test_admin_agm.py`, `tests/test_nickname_updates.py`, and `tests/test_members.py`.

**Build.**

- [ ] Pass `agm_franchise` from `update_league_player_discord` into `update_free_agent_discord`, `update_draft_eligible_discord`, and `update_permfa_waiting_discord`.
- [ ] In those three functions, when `agm_franchise` is set, call `apply_agm_role_updates` so the member keeps the AGM role and the franchise role, and write the nickname with the franchise prefix. Keep the status roles the function already applies.
- [ ] Remove the "records need to be reconciled by hand" warning in `update_league_player_discord`. An AGM with FA status is a normal off-season state.
- [ ] Remove the "PermFA in Waiting" role in `update_draft_eligible_discord`.
- [ ] In `_intent_to_play_flow`, after `declare_intent` succeeds, look the member up with `effective_player` and call `update_league_player_discord` with the result. A returning player gets the new row's roles. A player who declared "not returning" becomes non-playing once their older row's season has ended. Until then that row holds. Fix the return annotation of `declare_intent` to `LeaguePlayer | Deleted`. A nickname that is too long must not turn the reply into an error.

**You see.**

- [ ] `PYTHONPATH=. uv run python docs/plans/sync-rework-evidence/role_matrix.py.txt` with an AGM franchise prints `'BET | Player'` in the FA, DE, PF, PW, WV, WC, and WR columns, and `KA` on the AGM franchise role row.
- [ ] The same script prints `R.` for "PermFA in Waiting" in the DE column.
- [ ] After `/intent declare` on the test server, the member's roles match the returned row before the reply card appears.

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] `tests/test_admin_agm.py` gains a case per non-rostered status that asserts the franchise prefix, the AGM role, and the franchise role. Run `uv run pytest tests/test_admin_agm.py`.
- [ ] `tests/test_members.py` gains a case for a returning player whose roles follow the new row, a case for "not returning" that syncs the member to non-playing, and a case for "not returning" where a rostered row in an unfinished season holds. Run `uv run pytest tests/test_members.py tests/test_nickname_updates.py`.

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Ten lanes on `inherit-parent` at the PR head, per the boot recipe.

- [ ] Lane 1. Regression lane against trunk. Operator lane. Run `/admin sync member` on an AGM whose row is FA, at trunk and at head. Save `a2-regression.png`. Pass when trunk shows the `FA |` tag and head shows the franchise tag.
- [ ] Lane 2. Operator lane. Run the same command twice at head. Save `a2-agm-twice.png`. Pass when the second run changes nothing in the server audit log.
- [ ] Lane 3. Operator lane. Sync an AGM whose row is FA and who lost the franchise role. Save `a2-agm-role-back.png`. Pass when the franchise role and the AGM role are back and "Free Agent" stays.
- [ ] Lane 4. Operator lane. Sync a member who is FA and not an AGM. Save `a2-plain-fa.png`. Pass when the tag is `FA |` and no franchise role is present.
- [ ] Lane 5. Operator lane. Sync a rostered AGM. Save `a2-rostered-agm.png`. Pass when the tag is the roster franchise's prefix, as on trunk.
- [ ] Lane 6. Operator lane. Sync a DE member who holds "PermFA in Waiting". Save `a2-de-waiting.png`. Pass when the role is gone and "Draft Eligible" is present.
- [ ] Lane 7. Operator lane. Run `/intent declare` as a returning player on the test server. Save `a2-intent-returning.png`. Pass when the member's roles match the new row and the reply is the success card.
- [ ] Lane 8. Operator lane. Run `/intent declare` and answer not returning, as a member whose only row is in a finished season. Save `a2-intent-leaving.png`. Pass when the member loses league roles, gets "Former Player", and the reply is the success card.
- [ ] Lane 9. Operator lane. Run `/intent declare` for a member whose new nickname exceeds 32 characters. Save `a2-intent-long-name.png`. Pass when the roles apply and the reply is still the success card.
- [ ] Lane 10. Probe lane. List the live AGMs with a non-rostered effective row. Save `a2-agm-population.log`. Pass when the list matches the count the probe prints (20 on 2026-11-23) and each has a franchise with a prefix.

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. Discord requests the role functions send per member, from `role_matrix.py`, at trunk and at head.
- [ ] Probe. `PYTHONPATH=. uv run python docs/plans/sync-rework-evidence/role_matrix.py.txt`, with and without an AGM franchise, at trunk and at head.
- [ ] Baseline. Record the trunk rows `requests, all roles` and `requests, no roles` first.
- [ ] Rule. A second run on the member the first run produced sends 0 requests. The PR fails when any non-AGM column sends more requests than trunk for a member who does not hold "PermFA in Waiting". A Draft Eligible sync of a member who holds that role sends one more request, which is the removal this PR adds.

**Review gate.** None. A2 is not review-gated.

**Merge.**

- [ ] Root's clean verdict at the exact head SHA.
- [ ] Rebased onto its parent after the verdict, patch-id unchanged.
- [ ] The operator lands it.

## Count every Discord write a sync makes (B)

**Depends on.** A2.

**Files.**

- [ ] Create `rsc/transactions/writer.py`.
- [ ] Edit `rsc/transactions/roles.py` and `rsc/utils/utils.py`.
- [ ] Edit `rsc/admin/sync.py`.
- [ ] Create `scripts/sync_lab.py`.
- [ ] Create `tests/test_role_writer.py`.

**Build.**

- [ ] Add `apply_member_changes(member, remove, add, nick, stats)` in `rsc/transactions/writer.py`. It makes the same calls the function tails make today, in the same order, and records each request's type and duration in `stats`.
- [ ] Add the `SyncStats` dataclass with members visited, members changed, requests by type, failures, seconds in API reads, seconds in Discord writes, and elapsed seconds.
- [ ] Replace the remove, add, and nickname tail of every `update_*_discord` function with one call to `apply_member_changes`.
- [ ] Log one line per run in the nightly task and in each `/admin sync` command, starting with `Sync summary.`.
- [ ] Write `scripts/sync_lab.py` with the scenarios `reset`, `fresh-to-de`, `de-to-rostered`, `rostered-to-fa`, `no-change`, and `nick-forbidden`. It refuses to run when the dev bot is running or when the guild is the production server.

**You see.**

- [ ] The log line `Sync summary. kind=players visited=<n> changed=<n> requests=<dict> failed=<n> api_s=<s> discord_s=<s> elapsed_s=<s>` after every run.
- [ ] `uv run python scripts/sync_lab.py fresh-to-de` prints the starting roles, the final roles read back from Discord, and the request list.

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] `tests/test_role_writer.py` asserts the request counts for an add, a remove, a nickname change, and a no-op. Run `uv run pytest tests/test_role_writer.py`.
- [ ] The existing role tests pass unchanged. Run `uv run pytest tests/test_admin_sync.py tests/test_admin_agm.py tests/test_nickname_updates.py tests/test_transactions.py`.

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Ten lanes on `inherit-parent` at the PR head, per the boot recipe.

- [ ] Lane 1. Regression lane against trunk. Lab lane. Run `fresh-to-de` at trunk and at head. Trunk has no summary line, so record that and gate the final roles. Save `b-regression.log`. Pass when the final roles and nickname are equal at trunk and head.
- [ ] Lane 2. Lab lane. Run `fresh-to-de`. Save `b-fresh-to-de.log`. Pass when the summary's request counts equal the lab's own count of requests.
- [ ] Lane 3. Lab lane. Run `de-to-rostered`. Save `b-de-to-rostered.log`. Pass when the final roles match the rostered column of the matrix.
- [ ] Lane 4. Lab lane. Run `rostered-to-fa`. Save `b-rostered-to-fa.log`. Pass when the final roles match the FA column of the matrix.
- [ ] Lane 5. Lab lane. Run `no-change` twice. Save `b-no-change.log`. Pass when both runs report `changed=0` and an empty request dict.
- [ ] Lane 6. Lab lane. Run `nick-forbidden` on the server owner. Save `b-nick-forbidden.log`. Pass when the roles apply, the nickname failure is counted once, and the run does not raise.
- [ ] Lane 7. Lab lane. Run `reset` then `fresh-to-de` three times. Save `b-repeat.log`. Pass when the three request lists are identical.
- [ ] Lane 8. Operator lane. Run `/admin sync players` on the test server. Save `b-players.png`. Pass when the bot log has one `Sync summary. kind=players` line.
- [ ] Lane 9. Operator lane. Run `/admin sync freeagent` on the test server. Save `b-freeagent.png`. Pass when the bot log has one `Sync summary. kind=freeagent` line.
- [ ] Lane 10. Operator lane. Run a `/transactions` sign and cut on the test server. Save `b-transactions.png`. Pass when both still apply roles and the nickname as on trunk.

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. Wall time of the lab scenario `fresh-to-de`, measured by the lab outside the code under test, at trunk and at head. The request count is the cross-check.
- [ ] Probe. `uv run python scripts/sync_lab.py fresh-to-de --repeat 5`, at trunk and at head, interleaved. Report the median and the spread.
- [ ] Baseline. Record the trunk median first.
- [ ] Rule. Head sends the same number of requests as trunk. The PR fails when the head median exceeds the trunk median by more than the run-to-run spread.

**Review gate.** None. B is not review-gated.

**Merge.**

- [ ] Root's clean verdict at the exact head SHA.
- [ ] Rebased onto its parent after the verdict, patch-id unchanged.
- [ ] The operator lands it, deploys, and pastes one nightly `Sync summary.` line and one `/admin sync players` line from production into Appendix A. The operator ruled on 2026-11-24 that C and D are built before those lines exist. The lines still decide whether C's speedup was worth its risk.

## Send one request per changed member (C)

**Depends on.** B.

**Files.**

- [ ] Edit `rsc/transactions/writer.py`.
- [ ] Edit `tests/test_role_writer.py`.

**Build.**

- [ ] In `apply_member_changes`, build the new role list from the member's current roles minus `remove` plus `add`, read from `guild.get_member` at write time.
- [ ] Send one `member.edit(roles=..., nick=...)`. Send nothing when the roles and the nickname are unchanged.
- [ ] Leave the nickname out of the request when the member is the server owner or the member's top role is not below the bot's top role.
- [ ] On `discord.Forbidden` for a request that carried a nickname, retry once with roles only, and record the nickname failure in `stats`.

**You see.**

- [ ] `Sync summary.` lines show `requests={'edit': <n>}` with `<n>` equal to `changed`.
- [ ] The server audit log shows one member update entry per changed member.

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] `tests/test_role_writer.py` asserts one `edit` call per changed member, zero for a no-op, no `nick` key for the owner, and the roles-only retry. It asserts that a role the member holds and the bot cannot manage stays in the list. Run `uv run pytest tests/test_role_writer.py`.

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Ten lanes on `inherit-parent` at the PR head, per the boot recipe.

- [ ] Lane 1. Regression lane against trunk. Lab lane. Run `fresh-to-de` at trunk and at head. Save `c-regression.log`. Pass when the final roles and nickname are equal and head sends 1 request.
- [ ] Lane 2. Lab lane. Run `de-to-rostered`. Save `c-de-to-rostered.log`. Pass when head sends 1 request and the final state matches trunk's.
- [ ] Lane 3. Lab lane. Run `rostered-to-fa`. Save `c-rostered-to-fa.log`. Pass when head sends 1 request and the final state matches trunk's.
- [ ] Lane 4. Lab lane. Run `no-change`. Save `c-no-change.log`. Pass when head sends 0 requests.
- [ ] Lane 5. Lab lane. Run `nick-forbidden` on the server owner. Save `c-owner.log`. Pass when head sends 1 request without a nickname and the roles apply.
- [ ] Lane 6. Lab lane. Give the lab member a role above the bot's top role, then run `fresh-to-de`. Save `c-higher-role.log`. Pass when the edit succeeds and the higher role is still held.
- [ ] Lane 7. Lab lane. Give the lab member a managed role, then run `fresh-to-de`. Save `c-managed-role.log`. Pass when the edit succeeds and the managed role is still held.
- [ ] Lane 8. Lab lane. Add an unrelated role to the lab member through the Discord API 1 second before the run. Save `c-foreign-role.log`. Pass when the unrelated role is still held after the run.
- [ ] Lane 9. Lab lane. Run a scenario whose member left the server. Save `c-member-left.log`. Pass when the run records one failure and continues.
- [ ] Lane 10. Operator lane. Run `/admin sync players` on the test server. Save `c-players.png`. Pass when the summary line shows `edit` requests only.

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. Discord requests per changed member and wall time of `fresh-to-de`, at trunk and at head.
- [ ] Probe. `uv run python scripts/sync_lab.py fresh-to-de --repeat 5`, at trunk and at head, interleaved. Report the median and the spread.
- [ ] Baseline. Record the trunk values first. The matrix measured 3 to 5 requests for a member with no roles and 10 to 16 for a member with every role.
- [ ] Rule. Head sends 1 request per changed member, or 2 when Discord refuses the nickname. The PR fails when any scenario sends more than 2, or when the head median is not below the trunk median by more than the spread.

**Review gate.** None. C is not review-gated.

**Merge.**

- [ ] Root's clean verdict at the exact head SHA.
- [ ] Rebased onto its parent after the verdict, patch-id unchanged.
- [ ] The operator lands it.

## Compute roles from one status table (D)

**Depends on.** C.

**Files.**

- [ ] Create `rsc/transactions/planner.py`.
- [ ] Edit `rsc/transactions/roles.py`.
- [ ] Create `scripts/role_matrix.py` from `docs/plans/sync-rework-evidence/role_matrix.py.txt`.
- [ ] Create `tests/test_role_planner.py`.

**Build.**

- [ ] Extend `scripts/role_matrix.py` so it writes the matrix as JSON for the current code and compares two JSON files. Commit the trunk matrix as the first commit of the PR.
- [ ] Add `plan_member(status, row, member_state, agm_franchise, franchise, tiers)` in `rsc/transactions/planner.py`. It is a pure function. It returns the full set of managed roles the member should hold and the nickname. One table maps each status to its roles and prefix.
- [ ] Turn the seven status functions (`update_nonplaying_discord`, `update_nonplaying_gm_discord`, `update_unsigned_gm_discord`, `update_rostered_discord`, `update_free_agent_discord`, `update_draft_eligible_discord`, `update_permfa_waiting_discord`) into wrappers that call `plan_member` then `apply_member_changes`. Keep their names and signatures. Leave `update_signed_player_discord` and `update_cut_player_discord` as they are.
- [ ] Apply the intended differences in Appendix A, one commit each, and no other difference. The "Subbed Out" role follows the row's `sub_status`. A member holds it only while `sub_status` is 1, Subbing Out.

**You see.**

- [ ] `uv run python scripts/role_matrix.py --compare trunk.json head.json` prints only the intended differences listed in Appendix A.
- [ ] `rsc/transactions/roles.py` shrinks by about 600 lines.

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] `tests/test_role_planner.py` runs every status against a member with every managed role, a member with none, and an AGM, and compares the result with the committed matrix. Run `uv run pytest tests/test_role_planner.py`.
- [ ] Every existing role and sync test passes unchanged. Run `uv run pytest`.

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Ten lanes on `inherit-parent` at the PR head, per the boot recipe.

- [ ] Lane 1. Regression lane against trunk. Lab lane. Run `fresh-to-de`, `de-to-rostered`, and `rostered-to-fa` at trunk and at head. Save `d-regression.log`. Pass when the final roles and nicknames are equal for all three.
- [ ] Lane 2. Lab lane. Start from DE and sync an FA row. Save `d-de-to-fa.log`. Pass when "Draft Eligible" is gone, which is an intended difference.
- [ ] Lane 3. Lab lane. Start from PermFA and sync an FA row. Save `d-pf-to-fa.log`. Pass when "PermFA" is gone.
- [ ] Lane 4. Lab lane. Start from FA and sync a PermFA row. Save `d-fa-to-pf.log`. Pass when "Free Agent" is gone and "PermFA" is held.
- [ ] Lane 5. Lab lane. Start from "PermFA in Waiting" and sync an unsigned GM row. Save `d-pw-to-ug.log`. Pass when "PermFA in Waiting" is gone.
- [ ] Lane 6. Lab lane. Sync a rostered row with the captain flag and `sub_status` 1, then the same row with neither. Save `d-captain-sub.log`. Pass when Captain and "Subbed Out" are added, then removed.
- [ ] Lane 7. Lab lane. Sync an AGM with an FA row. Save `d-agm-fa.log`. Pass when the result equals A2's result.
- [ ] Lane 8. Lab lane. Sync a row with status DR for a member with a franchise prefix. Save `d-dropped.log`. Pass when league roles are gone and "Former Player" is held.
- [ ] Lane 9. Lab lane. Run `no-change` for every status. Save `d-no-change.log`. Pass when every run sends 0 requests.
- [ ] Lane 10. Operator lane. Run a `/transactions` sign, cut, and retire on the test server. Save `d-transactions.png`. Pass when the roles and nicknames match trunk's.

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. CPU time to plan 1,540 members with no change, and Discord requests per changed member, at trunk and at head.
- [ ] Probe. `uv run python scripts/role_matrix.py --bench 1540`, five runs each at trunk and at head, interleaved.
- [ ] Baseline. Record the trunk median first.
- [ ] Rule. Head sends the same requests as C. The PR fails when the head median plan time exceeds the trunk median by more than 20 percent and by more than 1 s.

**Review gate.** None. D is not review-gated.

**Merge.**

- [ ] Root's clean verdict at the exact head SHA.
- [ ] Rebased onto its parent after the verdict, patch-id unchanged.
- [ ] The operator lands it.

## Run every sync as one background job (E)

**Depends on.** D.

**Files.**

- [ ] Create `rsc/admin/sync_job.py`.
- [ ] Edit `rsc/admin/sync.py`.
- [ ] Edit `tests/test_admin_sync.py`. Create `tests/test_sync_job.py`.
- [ ] Edit `docs/modules/` for the admin module through the `update-module-docs` skill.

**Build.**

- [ ] Add the `SyncJob` class. It takes a kind, a guild, an iterator of (member, row) pairs, a dry-run flag, and a progress target. It plans each member, applies the change, records a failure per member, and continues.
- [ ] Hold one lock per guild. A second run replies that a sync is already running and names who started it.
- [ ] Post progress as one plain message in the invoking channel and edit it on a 15 second timer. Never use the interaction token after the first reply. Delete the progress image code in `sync.py`.
- [ ] In a dry run, list each member and the roles and nickname that would change, paged, and write nothing.
- [ ] Replace the bodies of the nightly task and of `/admin sync players`, `nonplaying`, `freeagent`, `drafteligible`, and `member` with `SyncJob` calls. Keep the command names and options, so no command resync is needed.
- [ ] End every run with a summary card that shows the `SyncStats` numbers and the first 20 failures. Use the red stripe when a run has failures.

**You see.**

- [ ] A sync that runs longer than 15 minutes finishes and posts its summary card.
- [ ] `/admin sync drafteligible dryrun:True` lists the members and changes it would make.
- [ ] A second `/admin sync players` during a run answers "A sync is already running".

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] `tests/test_sync_job.py` covers a per-member failure that does not stop the run, the lock, the dry run that writes nothing, a cancel, and a second run after a crash that converges. Run `uv run pytest tests/test_sync_job.py tests/test_admin_sync.py`.

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Ten lanes on `inherit-parent` at the PR head, per the boot recipe.

- [ ] Lane 1. Regression lane against trunk. Operator lane. Run `/admin sync players` at trunk and at head from the same lab starting state. Save `e-regression.png`. Pass when the members' final roles are equal and head posts the summary card.
- [ ] Lane 2. Operator lane. Run `/admin sync players dryrun:True`. Save `e-dry-run.png`. Pass when the reply lists each change and the audit log shows no member update.
- [ ] Lane 3. Operator lane. Run `/admin sync freeagent`. Save `e-freeagent.png`. Pass when the progress message updates in place and ends with the summary card.
- [ ] Lane 4. Operator lane. Run `/admin sync drafteligible`. Save `e-drafteligible.png`. Pass when the run ends with the summary card.
- [ ] Lane 5. Operator lane. Run `/admin sync nonplaying dryrun:True`. Save `e-nonplaying-dry.png`. Pass when the list excludes every member with an effective row.
- [ ] Lane 6. Operator lane. Start a run, then start a second one. Save `e-lock.png`. Pass when the second reply says a sync is already running.
- [ ] Lane 7. Operator lane. Start a run and press Cancel. Save `e-cancel.png`. Pass when the run stops within one member and the card says how many members it finished.
- [ ] Lane 8. Lab lane. Run a job over two members where the first write fails. Save `e-failure-isolation.log`. Pass when the second member is synced and the summary lists one failure.
- [ ] Lane 9. Lab lane. Run a job with a 16 minute artificial delay. Save `e-over-15-min.log`. Pass when the summary card posts after the interaction token expired.
- [ ] Lane 10. Operator lane. Run the nightly body from `[p]eval` with `NIGHTLY_GUILD_ID` set to the test server. Save `e-nightly.log`. Pass when the log has one `Sync summary. kind=nightly` line.

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. Elapsed seconds and Discord requests of `/admin sync freeagent` from the same lab starting state, from the `Sync summary.` line, at trunk and at head. Message edits for progress are counted apart.
- [ ] Probe. Reset the lab state, run the command, and read the summary line. Three runs each at trunk and at head, interleaved.
- [ ] Baseline. Record the trunk median first.
- [ ] Rule. Head sends at most one progress edit per 15 seconds. The PR fails when the head median elapsed time exceeds the trunk median.

**Review gate.** The operator reviews before merge.

- [ ] Copy the lane 2, 3, 6, and 7 screenshots into `docs/plans/sync-rework-evidence/e-review-<slug>.png`. Include one screenshot from a phone.
- [ ] Record a 30 to 60 second video of a run with its progress message and summary card. Save it as `docs/plans/sync-rework-evidence/e-review.mp4`.
- [ ] Post the screenshots and the video in chat. Leave the change uncommitted on the review branch until the operator approves. Stop at merge-ready. Wait for the operator's click.

**Merge.**

- [ ] Root's clean verdict at the exact head SHA.
- [ ] Rebased onto its parent after the verdict, patch-id unchanged.
- [ ] The operator lands it.

## Find non-playing members from Discord roles and strip them nightly (F)

**Depends on.** E.

**Files.**

- [ ] Edit `rsc/admin/sync.py`.
- [ ] Edit `tests/test_admin_sync.py`.

**Build.**

- [ ] In the `nonplaying` job, build the candidates from `guild.members`. A candidate holds a managed league role or a nickname prefix and has no effective row, or has one with status DR, FR, or BN.
- [ ] Delete the `paged_members` sweep and the stale AGM reverse sweep, which the candidate rule now covers.
- [ ] Sync a candidate who is a franchise's GM with `update_nonplaying_gm_discord`, as `/admin sync member` does. Today `/admin sync nonplaying` has no GM check and strips a GM who has no row.
- [ ] Apply welcome roles to candidates only.
- [ ] Run the `nonplaying` job at the end of every nightly run, after the players job. The candidate rule uses `effective_players`, so while sign-ups are open it strips only members who declared "not returning" or whose row is DR, FR, or BN. On the first night after sign-ups close it strips every member with league roles and no new-season row. The pass reuses the player set the players job already read, so it adds no API request. It finds candidates by scanning the member cache, and it sends a Discord request only for a candidate. A stripped member holds no league role and no prefix, so the next night does not find them again.

**You see.**

- [ ] `/admin sync nonplaying dryrun:True` lists a member who holds league roles and has no member record in the API.
- [ ] The run makes no request to the members endpoint.
- [ ] The nightly log has a `Sync summary. kind=nonplaying` line after the `kind=nightly` line.

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] `tests/test_admin_sync.py` replaces the AGM sweep cases with candidate cases. They cover a stale AGM with no member record, a member with a prefix only, a member with no league role, a pending-intent member who is kept, a member who declared "not returning", and the same pending-intent member after sign-ups close. Run `uv run pytest tests/test_admin_sync.py`.

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Ten lanes on `inherit-parent` at the PR head, per the boot recipe.

- [ ] Lane 1. Regression lane against trunk. Operator lane. Run `/admin sync nonplaying dryrun:True` at trunk and at head on the test server. Save `f-regression.png`. Pass when every member trunk lists is also listed by head.
- [ ] Lane 2. Operator lane. Run it with a member who holds a franchise role and has no API record. Save `f-no-record.png`. Pass when head lists that member.
- [ ] Lane 3. Operator lane. Run it with a stale AGM. Save `f-stale-agm.png`. Pass when head lists the AGM role for removal.
- [ ] Lane 4. Operator lane. Run it with a member who has a prefix and no league role. Save `f-prefix-only.png`. Pass when head lists the nickname change.
- [ ] Lane 5. Operator lane. Run it with a member who holds no league role and no prefix. Save `f-plain-member.png`. Pass when head does not list that member.
- [ ] Lane 6. Operator lane. Run it with a non-playing AGM the API lists. Save `f-agm-kept.png`. Pass when the AGM keeps the franchise role and tag.
- [ ] Lane 7. Operator lane. Run it with a non-playing GM. Save `f-gm-kept.png`. Pass when the GM keeps the franchise role and tag.
- [ ] Lane 8. Probe lane. Count candidates against live data without writing. Save `f-live-count.log`. Pass when no candidate has an effective row with an active status.
- [ ] Lane 9. Operator lane. Run the nightly body from `[p]eval` on the test server, once with sign-ups open and once with sign-ups marked closed in memory. Save `f-nightly-close.log`. Pass when the first run strips only the member who declared "not returning", and the second run strips every member without a new-season row.
- [ ] Lane 10. Lab lane. Run the job on two candidates, then run it again. Save `f-twice.log`. Pass when each candidate takes 1 Discord request and the second run has no candidates.

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. API requests and elapsed seconds before the first Discord write of `/admin sync nonplaying dryrun:True`, at trunk and at head.
- [ ] Probe. Read the `Sync summary.` line's `api_s` and the request log, three runs each at trunk and at head, interleaved, against staging.
- [ ] Baseline. Record the trunk values first. Against a production copy the member sweep was 65 pages and about 7 s of server time.
- [ ] Rule. Head makes 0 requests to the members endpoint. A nightly pass with no candidates adds 0 API requests and sends 0 Discord requests. The PR fails when head's `api_s` exceeds trunk's, or when the candidate scan on the production server takes more than 5 s in the `Sync summary. kind=nonplaying` line.

**Review gate.** None. F is not review-gated.

**Merge.**

- [ ] Root's clean verdict at the exact head SHA.
- [ ] Rebased onto its parent after the verdict, patch-id unchanged.
- [ ] The operator lands it and deploys before 2026-12-30 21:59 ET, or staff run `/admin sync nonplaying` once after that time.

## React to website change events (G)

**Depends on.** E, and the website issue in Appendix D. G does not start until staging emits the events.

**Files.**

- [ ] Edit `rsc/events/handlers.py`.
- [ ] Edit `rsc/enums.py` only if the website adds a new action, after the `rscapi` release that carries it.
- [ ] Edit `tests/test_events.py`.

**Build.**

- [ ] Add `handle_player_changed(cog, guild, event)` in `rsc/events/handlers.py`. It reads the member's Discord id from the event payload, looks the member up with `effective_player`, and runs E's single-member job. It writes nothing when the member is already correct.
- [ ] Register the handler in `EVENT_HANDLERS` for each action the website issue delivers.
- [ ] Skip an event whose member is not in the server, and log it at DEBUG.
- [ ] Leave the nightly task as it is. It stays the safety net for a path the website does not cover.

**You see.**

- [ ] A status change made on the website shows in Discord within one poll interval plus the poller's lag window, with no staff command.
- [ ] The bot log has one `Sync summary. kind=event` line per handled event that changed a member.

**Verify, unit.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] `tests/test_events.py` gains a case per registered action, a case for a member who left the server, a case for an event from another league, and a case where the handler raises and the poll cursor still advances. Run `uv run pytest tests/test_events.py tests/test_events_poller.py`.

**Verify, live.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked. Ten lanes on `inherit-parent` at the PR head, per the boot recipe.

- [ ] Lane 1. Regression lane against trunk. Operator lane. Change a test player's status on the staging website and wait. Trunk has no handler, so record that and gate head. Save `g-regression.log`. Pass when head updates the member with no command.
- [ ] Lane 2. Operator lane. Change a test player's tier on staging. Save `g-tier.log`. Pass when the tier role changes.
- [ ] Lane 3. Operator lane. Change a test player's name on staging. Save `g-name.log`. Pass when the nickname changes.
- [ ] Lane 4. Operator lane. Approve a PermFA on the staging website. Save `g-permfa.log`. Pass when the member gets the PermFA roles.
- [ ] Lane 5. Operator lane. Run a `/transactions` sign through the bot. Save `g-bot-made.log`. Pass when the event that follows sends 0 Discord requests.
- [ ] Lane 6. Operator lane. Replay one event with `/rsc events replay`. Save `g-replay.png`. Pass when the replay makes no second change.
- [ ] Lane 7. Lab lane. Feed the handler an event for a member who left the server. Save `g-member-left.log`. Pass when the handler logs the skip and does not raise.
- [ ] Lane 8. Probe lane. Compare the write paths listed in the website issue with the events staging emitted during lanes 1 to 4. Save `g-coverage.log`. Pass when every path exercised produced an event.
- [ ] Lane 9. Lab lane. Make the handler raise for one event in a batch of three. Save `g-handler-error.log`. Pass when the other two are handled and the cursor advances past all three.
- [ ] Lane 10. Operator lane. Start `/admin sync players`, then change a player on staging during the run. Save `g-during-run.log`. Pass when the member is correct after both finish.

**Verify, perf.** Tests alone are not sufficient verification. A PR is verified only when its unit, live, and perf boxes are all checked.

- [ ] Metric. Seconds from the event's `created_at` to the Discord change, and Discord requests per event. Trunk has no handler, so the budget is absolute.
- [ ] Probe. Read `created_at` from the event and the time of the `Sync summary. kind=event` line for lanes 1 to 4, at head. Run the same four changes at trunk and record that nothing happens before the nightly run.
- [ ] Baseline. Record trunk first. On trunk the change waits for the next 07:00 UTC run.
- [ ] Rule. Each event sends at most 1 Discord request, or 2 when Discord refuses the nickname. The PR fails when a change takes longer than two poll intervals plus the lag window.

**Review gate.** None. G is not review-gated.

**Merge.**

- [ ] Root's clean verdict at the exact head SHA.
- [ ] Rebased onto its parent after the verdict, patch-id unchanged.
- [ ] The operator deploys the website first, then lands this PR.

## Close the program

- [ ] Every box above is checked with its evidence.
- [ ] Update the status line at the top of this file and the row in `docs/plans/README.md`.
- [ ] Reply to the operator with each PR and its verdict.

## Appendix A. Prototype evidence

Three runs settled open questions on 2026-11-23. Their scripts are in `docs/plans/sync-rework-evidence/`. They carry a `.txt` suffix so the repo linter skips them, and `uv run python <file>` still runs them.

**The live API already defaults to S28.** `probe_overlap.py.txt` ran read-only against production at 19:59 UTC. S27's end date is now 2026-11-22, so `leagues/current_season` and `seasons/signup_season` both return S28. The default listing has 369 rows, all S28. S27 has 1,498 rows. 327 members have both rows, 42 have only S28, and 1,171 have only S27. Of the S27-only members, 858 have an active status, and `/admin sync nonplaying` on trunk would strip them. The S27 to S28 cross-tab is RO to RO 171, RO to FA 80, FA to FA 22, PF to DE 20, RO to UG 11, PW to DE 10, IR to FA 4, UG to UG 2, DR to DE 2, RO to PW 2, IR to RO 1, FR to DE 1, AR to AR 1. Of 56 AGMs, 20 have an S28 FA row.

**The role functions disagree with each other.** `role_matrix.py.txt` runs every status function against a fake member who holds every managed role and one who holds none. A member with no roles costs 3 to 5 requests today. A member with every role costs 10 to 16. The gaps below are the intended differences for D. The operator approved all of them on 2026-11-23.

| Status synced | Role left in place today | D removes it |
|---|---|---|
| DE | PermFA in Waiting | Yes, in A2 |
| FA | Draft Eligible, PermFA | Yes |
| PermFA | Free Agent, Draft Eligible | Yes |
| Waivers (WV, WC, WR) | Free Agent, PermFA, Draft Eligible | Yes |
| Unsigned GM, non-playing GM | PermFA in Waiting | Yes |
| Non-playing GM | IR | Yes |
| FA, DE, PermFA, PW, waivers for a member who is not an AGM | Assistant GM | Yes. Found while building A2 |
| Rostered, for an AGM who lacks the League role | League is added twice, one wasted request | Yes. Found while building A2 |
| Every playing status | Subbed Out | Yes. It is held only while the row's `sub_status` is Subbing Out |
| FA, DE, PermFA, waivers for an AGM | Franchise role removed, tag set to the status prefix | Fixed in A2 |

**The intents endpoint separates a declaration from silence.** A read-only probe at 20:20 UTC found 1,182 intent rows for S28. 825 have `missing` true, which means no declaration. 345 declared returning. 12 declared "not returning", with `missing` false and `returning` false. A filter on `returning=False` alone returns 837 rows and would strip the 825 who have not answered.

**The nightly non-playing pass is a cache scan.** `candidate_scan_bench.py.txt` timed the candidate rule on synthetic members. 30,000 members took a median of 8.4 ms and 100,000 took 31.6 ms, over 7 runs each. The real `member.roles` property is slower than the fake one, so the production number comes from B's summary line. The scan makes no API request and no Discord request.

**A failed nightly run waits a full day.** `loop_restart.py.txt` showed that a `time=` loop whose error handler calls `restart()` runs again at the next scheduled time. The per-member `except` in the nightly loop does not catch `discord.HTTPException`, so one refused role write ends that night's run.

**Unproven.** No timing of a real sync exists. Discord publishes no number for the member routes' rate limit, and discord.py buckets them per route per server. B's two production summary lines are the first real measurement. The lab script's login without a gateway connection passed against a local stand-in for the Discord HTTP API and has not run against Discord. If it fails there, lab lanes become operator lanes with `[p]eval`.

## Appendix B. Alternatives rejected

- **Newer row always wins.** The earlier brief chose it. It would turn 80 rostered players into free agents before their season ends the next time two seasons overlap. The rule in A1 keeps a rostered row until its season's end date.
- **Skip pending-intent members instead of syncing their older row.** It is a smaller change. It leaves a member who lost the League role with no way back until they declare. A1 syncs them from the older row, which writes nothing when nothing changed.
- **A 15 minute interval run for sync on change.** The operator rejected it. It would start a job 96 times a day that finds nothing to do on most runs. G waits for website events instead. The cost is on the website side. A status can change in about 25 places there, and six of them use `queryset.update()`, which skips model signals.
- **Staff-run cleanup after sign-ups close.** The operator chose the automatic nightly pass in F.
- **Parallel writes.** discord.py keys the rate limit bucket by route and server, so members of one server share it.
- **The planner before the single write.** B's writer already gives C one place to change. C ships the speedup without waiting for the larger refactor.
- **Moving `update_signed_player_discord` and `update_cut_player_discord` onto the planner.** They take a transaction result, not a league player row. They stay as they are.

## Appendix C. Risks

- **A full role list can undo another actor's change.** It lands in C. `member.edit(roles=...)` replaces the list, so a role another bot adds between the cache read and the request is lost. The writer reads the roles at write time and sends nothing for an unchanged member. The owner watches lane 8 of C.
- **A refused nickname rejects the whole edit.** It lands in C. The writer leaves the nickname out for the owner and for members the bot does not outrank, and retries once with roles only.
- **Discord has no control skill.** It affects every PR. Operator lanes need the operator at the test server. The lab script exists to keep that to a few lanes per PR.
- **The test server is small.** Lab timings show request counts, not production speed. The production summary lines from B are the speed evidence.
- **The nightly task is tied to one server id.** A1 moves the id to a constant so the test bot can run the loop body. E does not make it a setting.
- **The nightly pass strips everyone without a new row once sign-ups close.** It lands in F. Sign-ups close on 2026-12-30 21:59 ET, and no person checks the list first. A wrong `signup_close` date on the website would strip hundreds of members. The change is reversible, because correcting the date and running a sync restores each member from the older row. The owner watches lane 9 of F. If F is not deployed by the close date, staff can run `/admin sync nonplaying` once, with one caution. Until F adds the GM check, that run strips any GM who has no new-season row.
- **Other callers still read the default season.** 35 call sites of `players`, `paged_players`, `total_players`, and `player_count` pass no season. A1 changes the sync paths only. The rest were not audited.
- **G depends on another repo.** The website must emit an event for every path that changes a league player. A path the website misses stays stale until the nightly run. The owner watches lane 8 of G.

## Appendix D. Links and reading list

- `docs/development.md` for the test bot, the test server, and the test commands.
- `docs/architecture.md` for the cog lifecycle and task loops.
- `rsc/transactions/roles.py`, `rsc/admin/sync.py`, `rsc/leagues/leagues.py`, and `rsc/events/events.py` before editing.
- In the website repo, `api_rest/league_season.py` and `core/models/league.py` for the default season rule. Read only. This plan changes nothing there.
- The website issue for change events. It is https://github.com/RSC-NA/web-rsc-website/issues/233. Its text is also in `docs/plans/sync-rework-evidence/website-issue-draft.md`.
- D and E are the contested designs. Their owners run the pstack `interrogate` skill on the design before the code-ready report.
- Each owner keeps a decision trail per the pstack `show-me-your-work` skill.

## Appendix E. Brief claims rechecked

| Claim in the earlier brief | Result | Evidence |
|---|---|---|
| Six loops walk members one at a time | Confirmed | Read `rsc/admin/sync.py` |
| Eight role functions | Close. Seven status functions and two transaction functions share the tail | Read `rsc/transactions/roles.py` |
| Each function writes only on a difference | Confirmed for the status functions | `role_matrix.py`, unchanged members send 0 requests |
| `add_roles` and `remove_roles` send one request per role | Confirmed | discord.py 2.7.1 `member.py:1144` and `:1189` |
| The website defaults to the earliest unfinished season | Confirmed | Website `core/models/league.py:131` |
| The default is S27 until 2026-11-29 | Stale. Production defaults to S28 since S27's end date moved to 11-22 | Live probe, 19:59 UTC |
| `nonplaying` would strip 35 S28 sign-ups | Stale. Today it would strip 858 members with an active S27 row | Live probe |
| `/intent declare` discards the reply | Confirmed. The client already maps 201 to a league player, so no client release is needed | Read `rsc/members/members.py`, `rscapi/api/members_api.py` |
| The API returns 201 with the row or a 200 "deleted" reply | Incomplete. A 200 also comes back for a returning player who already has a row | Website `members/views/admin.py:418` |
| Draft Eligible keeps "PermFA in Waiting" | Confirmed, with seven more gaps | `role_matrix.py` |
| `nonplaying` pages all 16,046 members | Confirmed | Read `sync.py`, local database count |
| The `drafteligible` progress edit is unguarded | Confirmed. The run dies when the token expires at 15 minutes | Read `sync.py:1351`, Discord docs |
| One Discord error aborts a run | Confirmed | Read `sync.py`, `loop_restart.py` |
| One event handler, for trades | Confirmed. The bot polls events every 60 s | Read `rsc/events/` |
| Sync on change needs a client release | Only if the website adds a new action. The client already has PSG, PCT, PRS, PDR, NCH, and UPD | Read `rsc/enums.py`, website `integrations/models.py` |
| Member edits are limited to about one a second | Unverified. Discord publishes no number | Discord rate limit docs |
| Interaction tokens last 15 minutes | Confirmed | Discord docs, `interactions.py:423` |
| Website cost of 0.4 s and 7 s | Measured once or twice on a local copy, without network or auth | Earlier session's transcript |

## Appendix F. Operator decisions

The operator answered these on 2026-11-23.

| Decision | Answer | Lands in |
|---|---|---|
| Which row applies when a member has two | A rostered row holds until its season's end date. Otherwise the newest row applies | A1 |
| When a member becomes non-playing | Only after a declared "not returning", or after sign-ups close, and in both cases only once their older row's season has ended | A1, F |
| Pending-intent members while sign-ups are open | Synced from the older row | A1 |
| What happens at sign-up close | The nightly run strips everyone without a new row. No staff step | F |
| AGM with a non-rostered status | Keeps the franchise tag, the franchise role, and the AGM role. Status roles still apply | A2 |
| Leftover roles in the matrix | Remove all of them, with "Subbed Out" tied to `sub_status` | D |
| Sync on change | Website events. No interval job. The website work is an issue on `RSC-NA/web-rsc-website` | G |
| F | Kept, before G | F |
| A2's request rule | One extra request is allowed on a Draft Eligible sync of a member who holds "PermFA in Waiting". Ruled 2026-11-24 | A2 |
| A failed role sync after `/intent declare` | The member always sees the success card, and the error is logged. Ruled 2026-11-24 | A2 |
| A member in a season still being played who declares "not returning" | Their row holds until that season's end date. Ruled 2026-11-24 | A1 |
| When C starts | C and D are built now, without waiting for production summary lines. Ruled 2026-11-24 | C, D |
| Landing | Nothing lands until the stack through D is built and checked. Ruled 2026-11-24 | All |
| Live checks | The PRs land on the offline checks. The test-server lanes become a written checklist the operator can run. A sync that goes wrong is corrected by a later sync. Ruled 2026-11-24 | All |
| Extra fixes | The GM check in `/admin sync nonplaying`, issue 35, issue 38, and issue 39 each get their own PR. Ruled 2026-11-24 | Outside the lettered PRs |
| A cut GM | Does not become a free agent, because a GM cannot be rostered by another franchise. Ruled 2026-11-24 | Issue 39, D |

## Appendix G. Findings during execution

- **`LeaguePlayer.season` and `IntentToPlay.season` hold the season number.** The plan's first draft called it an id. A1's rule is keyed by number.
- **The counts move daily.** On 2026-11-23 at 22:00 UTC, 812 members held an active S27 row with no S28 row, down from 858. 12 had declared "not returning". 23 AGMs had an S28 FA row, up from 20.
- **The API marks "no sign-up season" with its own code.** Production answers the lookup for a league with no open sign-ups with a 404 and the code `no_signup_season` (measured on league 2). A1 treats only that answer as closed sign-ups.
- **Eleven other callers of `next_signup_season` catch the wrong exception for that 404.** They will show an API error once sign-ups close on 2026-12-30. Filed as https://github.com/RSC-NA/rsc/issues/35. It is outside this plan's PRs.
- **`tests/sync_fakes.py` from A2 has a fake member whose roles and nickname change when written.** B, C, and D reuse it for the rule that a second sync sends no request.
- **The Intent to Play DM buttons and `/admin intents set` record an answer without a sync.** A2 covers `/intent declare` only. The nightly run catches the rest.
- **A free agent in a season still being played who declared "not returning" used to become non-playing at once.** The operator ruled on 2026-11-24 that any older row holds until its season ends. A1 has that rule since head `5147b78`.
- **B's writer takes two calls per member, one for roles and one for the nickname.** Today a name that is too long raises after the roles are written, and callers rely on that. C merges the two calls and must keep that outcome.
- **The summary line carries the guild tag first.** It reads `[RSC 3v3] Sync summary. kind=players ...`. `elapsed_s` leaves out the wait for the confirm button.
- **C's "You see" line holds only when no request is retried and no nickname is refused.** With a refused nickname the count of `edit` requests exceeds `changed` by one for that member.
- **Two defects on `master` showed up in B's call dump.** A captain update removes the Captain role from a captain who already holds it, filed as https://github.com/RSC-NA/rsc/issues/38. Cutting a GM who already holds an FA role raises `ValueError`, filed as https://github.com/RSC-NA/rsc/issues/39. Both are outside this plan's PRs.
- **`/admin sync nonplaying` has no GM check until F.** All 28 GMs have a row in S27 or S28 on 2026-11-23 (measured), so no GM is affected while sign-ups are open. 13 GMs have only an S27 row. A run after sign-ups close would strip those who still have no S28 row.
- **A1's guard stops an empty player read only.** A read that is short for another reason, such as the previous season's lookup returning nothing, is not detected and would expose the pending members again. The dry-run list in E and a candidate count in F's confirm step are the places to add a stronger check.
- **The root did not run the full swarm the plan describes.** For A1, A2, and B the root read each diff and reran the gates and the offline or read-only checks. No lane has run against Discord. An Opus reviewer then read the trail and the three diffs, and its flags are the three items above plus the A2 rule change below.
- **The root corrected A2's request rule after the operator's go and before giving A2's verdict.** The operator has not yet ruled on that change.
- **The dispatcher strips a GM whose row is Dropped, Former, or Banned.** `update_league_player_discord` sends those statuses to the non-playing path with no GM check, so the nightly run, `/admin sync players`, and `/admin sync member` remove that GM's franchise role and tag. No production GM has such a row on 2026-11-23 (measured). D's table treats a franchise's GM as management whatever the row's status. PR 44 added `franchise_staff`, which gives the GM map in the one franchise read the syncs already make.
- **The free agent sync has no GM rule.** If the API gives a cut GM the Free Agent status, the next sync adds the FA roles and the `FA |` tag back, against the ruling in Appendix F. Which status the API gives is not checked. D's GM rule covers it either way.
- **`master` moved on 2026-11-24.** PR 43 and one more commit landed. The stack merges `master` once, when D is code-ready.
- **`/tmp` was wiped on the night of 2026-11-23.** The lane logs under `/tmp/swarm-*` are gone. Evidence from 2026-11-24 on is under `.audit/evidence/` in the main checkout, which git ignores.
