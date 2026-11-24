# Sync rework handoff

Written on 2026-11-24 for whoever resumes the sync rework, a person or an agent. It records where the work stopped, what to do next, and the facts that are easy to get wrong. The plan is [sync-rework.md](sync-rework.md). The hand-run checks are in [sync-rework-test-checklist.md](sync-rework-test-checklist.md).

## The goal

The operator wants the Discord sync commands faster, correct across a season change, and reacting soon after the website changes a member.

## Where the work stopped

Every PR below is open, has green CI, and passed the coordinator's own offline check at the head shown. Nothing is merged. No check has run against Discord.

| PR | Branch | Base | Head | What it does |
|---|---|---|---|---|
| 33 | `docs/sync-rework-plan` | `master` | see `git log` | Plan, evidence scripts, checklist, this file |
| 34 | `sync/a1-season-aware` | `master` | `5147b78` | A1. Syncs read the right season's rows |
| 36 | `sync/a2-agm-tag` | `sync/a1-season-aware` | `d18df25` | A2. AGM tag and roles, DE drops "PermFA in Waiting", `/intent declare` syncs roles |
| 37 | `sync/b-write-stats` | `sync/a2-agm-tag` | `da35e0c` | B. Role writer and the `Sync summary.` log line |
| 41 | `fix/captain-role-kept` | `sync/b-write-stats` | `c43d8c5` | Fixes issue 38 |
| 42 | `fix/cut-gm-fa-roles` | `fix/captain-role-kept` | `9459fc7` | Fixes issue 39 |
| 49 | `sync/c-one-request` | `fix/cut-gm-fa-roles` | `2297a96` | C. One Discord request per changed member |
| 44 | `sync/nonplaying-gm-check` | `sync/b-write-stats` | `adaff10` | GM check in `/admin sync nonplaying`. A sibling of PR 41, not in the main line |
| 40 | `fix/no-signup-season-404` | `master` | `9ecf973` | Fixes issue 35. Independent of the stack |

The main line is 34, 36, 37, 41, 42, 49, then D.

## What was running when the session ended

**PR D, the role table.** An owner agent was building it on branch `sync/d-role-table`, based on `origin/sync/c-one-request`. The branch did not exist on the remote when this file was written.

To see how far it got, run these.

```sh
git fetch origin
git ls-remote origin 'refs/heads/sync/d-role-table'
gh pr list --repo RSC-NA/rsc --head sync/d-role-table
tail -20 /home/xentrick/dev/rsc/.audit/sync-rework.tsv
ls /home/xentrick/dev/rsc/.audit/evidence/d/
```

- If a PR exists and its report never arrived, check it as described under "How the coordinator checks a PR".
- If the branch exists with no PR, a fresh owner takes it over from the branch and the trail rows with phase `D`.
- If nothing exists, start D again from the brief summary below.

**D's brief in short.** Add `rsc/transactions/planner.py` with a pure `plan_member` function and one status table. Turn the seven status functions in `rsc/transactions/roles.py` into thin wrappers with the same names and signatures. Leave the sign, cut, and captain functions alone. First prove with `scripts/role_matrix.py --json` and `--compare` that the refactor changes no final state and no request count. Then make six approved differences, one commit each.

1. A Free Agent sync also removes Draft Eligible and PermFA. A PermFA sync also removes Free Agent and Draft Eligible.
2. A Waivers, Waiver Claim, or Waiver Release sync removes Free Agent, PermFA, and Draft Eligible.
3. An Unsigned GM sync and a non-playing GM sync remove "PermFA in Waiting". A non-playing GM sync also removes IR.
4. "Subbed Out" is held only while the row's `sub_status` is 1.
5. A member who is not an AGM and has a non-rostered status loses a stale Assistant GM role.
6. The IR role follows the status and no longer flips. This fixes issue 50, and the 8 `IR_ROLE_FLIPS` expected failures in `tests/test_role_writer.py` become passing tests.

D must not add a GM rule. D's owner runs the pstack `interrogate` skill on the planner design before the code-ready push.

## What comes after D

1. **Check D** and report to the operator.
2. **Merge `master` into the stack once.** `master` moved on 2026-11-24. Use merge commits from the bottom up, because force pushes are refused. Expect small conflicts under `docs/`.
3. **Tell the operator the stack through D is built.** That is the point the operator said they would land. The landing order is 34, 36, 37, then 41 and 44 (both target 37), 42, 49, D. Retarget each child PR to `master` as its parent merges.
4. **Add checklist entries for C and D** to `sync-rework-test-checklist.md`.
5. **Then E, F, and G** from the plan. G waits for [website issue 233](https://github.com/RSC-NA/web-rsc-website/issues/233).

## Questions the operator has not answered

- **Should a franchise's GM always be treated as management?** Today the dispatcher strips a GM whose row is Dropped, Former, or Banned, and the free agent sync would re-add FA roles to a cut GM if the API marks them Free Agent. No production GM is in either state. The fix would be a small PR after D. It needs the GM map from `franchise_staff`, which exists only on PR 44's branch.
- **Does the website give a cut GM the Unsigned GM status or Free Agent?** Not checked.
- **When to land PR 40.** It is independent and has the 2026-12-30 deadline.

## Rulings already made

All are in Appendix F of the plan. The ones that most shape the remaining work follow.

- A rostered row holds until its season's end date. Otherwise the newest row applies. Any older row holds until its own season ends, even after "not returning".
- A member becomes non-playing only after a declared "not returning" or after sign-ups close.
- An AGM with a non-rostered status keeps the franchise tag, the franchise role, and the AGM role.
- A cut GM does not become a free agent.
- The PRs land on offline checks. The Discord checks are a written checklist, not a gate.
- Nothing lands until the stack through D is built.
- Sync on change uses website events, not an interval job.
- When the operator says an issue should exist, file it at once and report the URL.

## Facts that are easy to get wrong

- **The operator's main checkout at `/home/xentrick/dev/rsc` is on their own branch with uncommitted work.** Never change it with git. Write there only under `.audit/`, which git ignores.
- **The plan lives on branch `docs/sync-rework-plan`.** Edit it in the worktree at `/home/xentrick/dev/rsc/.claude/worktrees/plan-docs`. Agents read it with `git show origin/docs/sync-rework-plan:docs/plans/sync-rework.md`.
- **Run the plan checker after every plan edit.** `node ~/.claude/plugins/cache/cursor-plugins/pstack/0.15.36/skills/poteto-mode/scripts/check-plan.mjs docs/plans/sync-rework.md`. It rejects long dashes, curly quotes, and a colon followed by text in prose.
- **`/tmp` does not survive a reboot.** Evidence goes under `/home/xentrick/dev/rsc/.audit/evidence/<name>/`. The decision trail is `/home/xentrick/dev/rsc/.audit/sync-rework.tsv`. Rows before 2026-11-24 point at `/tmp` files that are gone.
- **History rewrites are refused.** No force push, no hard reset, no `--no-verify`. Restack with merge commits.
- **A new worktree needs `uv sync --locked --all-groups`** or the pre-commit `ty` hook fails on missing packages.
- **A script with a shebang must be committed executable.** CI lint rule EXE001 does not fire on this machine.
- **Type-check with `uv run ty check`.** Never mypy. Never `typing.cast()`.
- **`rm`, `cp`, and `mv` are aliased to interactive.** Use `\rm -f`, `\cp -f`, `\mv -f`.
- **Commit subjects are one plain sentence**, with no Conventional Commits prefix.
- **`LeaguePlayer.season` and `IntentToPlay.season` hold the season number**, not an id.
- **A declared "not returning" is `missing` false and `returning` false.** `returning=False` alone also matches everyone who has not answered.
- **Never start `redbot` and never use the production bot.** Read-only GET requests to the production API with `RSC_API_KEY` are allowed.

## How the coordinator checks a PR

The coordinator never writes PR code. For each PR an owner returns, the coordinator does this before reporting.

1. Read the production diff under `rsc/` against the PR's base.
2. In a worktree at the PR head, run `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, and `uv run ty check`.
3. For a PR that must not change what a sync writes, run `scripts/role_matrix.py --json` on the base tree and the head, then `--compare`, in both plain and `--agm` modes.
4. Read `gh pr checks <n>`.
5. Save the result under `.audit/evidence/root/` and add a trail row with the helper below.

```sh
bash ~/.claude/plugins/cache/cursor-plugins/pstack/0.15.36/skills/show-me-your-work/scripts/log.sh \
  /home/xentrick/dev/rsc/.audit/sync-rework.tsv <phase> "<decision>" "<why>" "<evidence>" "<result>"
```

Owners are `pstack:poteto-agent` subagents in their own worktree, one per PR, each given the goal, the plan pointer, the base branch, the constraints above, and what to report. A fix round goes to a fresh agent with the full scope.

## Issues filed during this work

| Issue | What | State |
|---|---|---|
| [web 233](https://github.com/RSC-NA/web-rsc-website/issues/233) | Emit a league event when a league player changes | Open, blocks G |
| [35](https://github.com/RSC-NA/rsc/issues/35) | API error once sign-ups close | Fixed by PR 40 |
| [38](https://github.com/RSC-NA/rsc/issues/38) | Captain update removes the Captain role | Fixed by PR 41 |
| [39](https://github.com/RSC-NA/rsc/issues/39) | Cutting a GM raises an error | Fixed by PR 42 |
| [50](https://github.com/RSC-NA/rsc/issues/50) | IR role flips on every sync | D fixes it |

## Known limits of what is built

- No lane has run against Discord. The lab script `scripts/sync_lab.py` needs `RSC_LAB_BOT_TOKEN`, `RSC_LAB_GUILD_ID`, and `RSC_LAB_MEMBER_ID`.
- A1's guard stops an empty player read only. A short read is not detected.
- After C, one refused role blocks that member's whole update.
- After C, the summary line's `failed` counts the owner and higher-ranked members whose nickname is out of date. E should give them their own counter.
- The Intent to Play DM buttons and `/admin intents set` record an answer without a sync.
- The full swarm the plan describes never ran. The coordinator's own reruns replaced it.
