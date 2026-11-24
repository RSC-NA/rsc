# Sync rework test checklist

Run these checks by hand to confirm the sync rework behaves on Discord. The PRs land on their offline checks, so nothing here blocks a merge. A sync that goes wrong is corrected by a later sync once the fix is in.

Each check names where to run it, what to do, and what you must see. Tick the box when you have seen it. The plan is [sync-rework.md](sync-rework.md).

## Before you start

- Use the test bot on the test server for every check marked **Test server**. Never use the production bot for those.
- Check out the top of the stack you want to test, then reload the cog with `[p]reload rsc`. No command resync is needed.
- Checks marked **Production** are things to watch after a deploy. They change nothing by themselves.

## After the first deploy, on production

These matter most. They cover PRs 34, 36 and 37.

- [ ] **The nightly run finishes.** After 07:00 UTC, search the bot log for `Sync summary. kind=nightly`. You must see one line, and `Finished syncing league players` just before it.
- [ ] **The run size is what the plan expects.** In that line, `visited` is about 1,500 and `changed` is small. A `changed` value in the hundreds on the first night means members were out of step, so read the debug lines for a few of them before the next night.
- [ ] **Failures are named.** If `failed` is above 0, search for `Discord refused the sync of`. Each line names one member. The run must still have finished.
- [ ] **An AGM with a Free Agent row keeps the franchise tag.** Pick one of the AGMs waiting to re-sign. After the nightly run their nickname starts with the franchise prefix, and they hold the franchise role, "Assistant GM", and "Free Agent".
- [ ] **A member who has not declared intent is untouched.** Pick a rostered S27 player with no S28 row. After the nightly run they still hold their franchise role, tier role, and prefix.
- [ ] **A member who declared "not returning" is non-playing.** Pick one of them. After `/admin sync member` on them, they hold no league roles and hold "Former Player".
- [ ] **Copy two lines into the plan.** Paste one `kind=nightly` line and one `kind=players` line into Appendix A of the plan. They are the first real timing of a sync.

Do not run `/admin sync nonplaying` on production after sign-ups close until the GM check has landed. Before that it strips a GM who has no new-season row.

## PR 34, season-aware reads

- [ ] **Test server.** Run `/admin sync member` on a member who has a league player row. The reply is the success card and their roles do not change.
- [ ] **Test server.** Run `/admin sync member` on a member with no row in any season. They lose league roles and get the welcome roles.
- [ ] **Test server.** Run `/admin sync nonplaying dryrun:True`. It finishes and nobody's roles change.
- [ ] **Test server.** Give one member a franchise role that sits above the bot's top role. Run `/admin sync players`. Note whether the run stops at that member. Before PR E it does, and that is expected. The nightly run does not stop.
- [ ] **Any machine.** Run `uv run python scripts/sync_season_probe.py` with `RSC_API_KEY` set. It sends GET requests only. Every lane prints `PASS`, and the line `stripped by nonplaying while sign-ups are open` shows 0.

## PR 36, AGM tag and role gaps

- [ ] **Test server.** Run `/admin sync member` on an AGM whose row is Free Agent. Their tag is the franchise prefix. They hold the franchise role, "Assistant GM", and "Free Agent".
- [ ] **Test server.** Run it again on the same member. The server audit log shows no second change.
- [ ] **Test server.** Run `/admin sync member` on a free agent who is not an AGM. Their tag is `FA |` and they hold no franchise role.
- [ ] **Test server.** Run `/admin sync member` on a rostered AGM. Their tag is their roster franchise's prefix.
- [ ] **Test server.** Give a Draft Eligible member "PermFA in Waiting", then sync them. The role is gone and "Draft Eligible" stays.
- [ ] **Test server.** Run `/admin sync freeagent` with an AGM among the free agents. The AGM keeps the franchise tag and role.
- [ ] **Test server.** Run `/intent declare` as a returning player. Their roles match their new row, and the reply is the success card.
- [ ] **Test server.** Run `/intent declare` and answer not returning, as a member whose only row is in a finished season. They lose league roles, get "Former Player", and see the success card.

## PR 37, run statistics

- [ ] **Test server.** Run `/admin sync players`. The bot log has one line that starts `Sync summary. kind=players`.
- [ ] **Test server.** Run `/admin sync freeagent`, `/admin sync drafteligible`, and `/admin sync member`. Each logs one summary line with its own `kind`.
- [ ] **Test server.** Run `/admin sync players` twice. On the second run `changed=0` and `requests={}`.
- [ ] **Test server.** Run one `/transactions` sign and one cut. Both still apply the roles and the nickname they did before.
- [ ] **Test server, optional.** Set `RSC_LAB_BOT_TOKEN`, `RSC_LAB_GUILD_ID`, and `RSC_LAB_MEMBER_ID`, stop the test bot, and run `uv run python scripts/sync_lab.py fresh-to-de`. It prints the member's starting roles, final roles, and the requests it sent, and exits with 0. The lab has only run against a stand-in for Discord so far.

## Later PRs

The checks for C, D, and the extra fixes are added to this file as each one is built.
