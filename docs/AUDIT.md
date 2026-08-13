# RSC Bot — Senior Engineering Code Audit

**Scope:** `/home/xentrick/dev/rsc` @ `caf897d` (master, clean). ~35.5k LOC in `rsc/`, 18.5k LOC in `tests/`.
**Method:** Direct reading of the signup path plus three parallel read-only audit agents (signup/onboarding, security/secrets, architecture/reliability).

---

## Remediation status

Work has started on three Criticals. Two are closed outright; one is only partly addressed.
Everything else in this document is untouched and still describes current behaviour.

Status vocabulary used throughout:

- **Resolved** — the defect is gone. No follow-up work is implied.
- **Mitigated** — the specific gap named in the finding is closed, but the finding's own text
  identifies further work that has *not* been done. Read the remaining-work note before treating it
  as done.
- **Open** — unchanged.

| ID | Status | Change | Follow-up |
|---|---|---|---|
| C-2 | **Resolved** | `exc=` → `exc_info=` at `rsc/admin/sync.py:71, :80`; added the missing `continue` after the tiers handler | none |
| C-4 | **Resolved** | Permission gates on `/assign`, `/unassign`, `/resolve`; new `is_modmail_channel()` guard on `/assign` | confirm the permission level matches your moderator roles (below) — a config question, not a code defect |
| C-5 | **Mitigated** | `.error` handlers added to all three unprotected loops — 5 of 5 now covered | **yes** — loop bodies still have no per-guild `try/except`, so one bad guild aborts the tick for the rest. H-17 now recurs loudly instead of dying silently, but is not fixed. |
| all others | **Open** | No source changes | — |

Verification run after the fixes: `ruff check` → 4 findings (unchanged pre-existing `PLC0415`,
none introduced), `ruff format --check` → clean, `ty check` → clean, `pytest` → **1233 passed**.

The C-2 defect was confirmed empirically rather than assumed — `GuildLogAdapter` passing `exc=`
through to `Logger._log()` raises `TypeError: Logger._log() got an unexpected keyword argument
'exc'` on every invocation, and the `exc_info=` form does not. Error-handler registration was
likewise verified by introspecting `Loop._error` on all five loop objects rather than trusting the
decorator.

**Knock-on effects on other findings.** C-5 downgrades the *permanence* of several open items
without fixing their causes: **H-17** (duplicate FA check-in raising `ValueError`) and the
`expire_sub_contract_loop` failure modes described under C-5 now auto-restart instead of dying for
the process lifetime. The underlying bugs are untouched — they will now fail repeatedly and
visibly rather than once and silently, which is the better failure mode but not a resolution.

**One judgement call to confirm.** C-4's gates were set to `manage_channels` for `/assign` and
`/unassign` (they call `channel.move(sync_permissions=True)`, which is genuinely a channel-management
action) and `manage_messages` for `/resolve` (it only posts a message). This is deliberately lighter
than the `manage_guild` the `_thread` config group uses, so routine ticket triage does not require
server-admin. **If RSC's moderator roles do not carry `manage_channels`, this will block their
workflow** — adjust the decorator to match your actual role setup.

`is_modmail_thread` was left unchanged and a new `is_modmail_channel` added alongside it, because
the former matches only *group* categories. That is correct for `/unassign` but would have broken
`/assign`'s main use case — moving a fresh ticket out of the primary category.

---

## Executive summary

**This is a disciplined codebase with a serious enforcement gap.** Zero bare `except:` clauses, zero
swallowed exceptions, zero naive datetimes, `ty check` clean, `ruff check` clean (4 findings across
35.5k lines), 1,233 passing unit tests, and unusually dense "why" comments recording prior fixes.
That is well above the bar for a volunteer-run community bot.

The defects are not sloppiness. They cluster into four recognisable patterns:

1. **Guards that were written and then disabled or never wired up.** Nine `override` permission
   checks commented out in the transaction suite (C-3), the ModMail authenticity check commented out
   in `/llm summarize` (H-11), `/welcome toggle` never read by its own listener, the FA `visible`
   back-fill testing the wrong variable, and `rsc/decorator.py` — a guard three files point at that
   has never worked (H-22).
2. **Fixes applied to one copy of duplicated logic and not the other six.** The IR-status fix exists
   in 1 of 5 blocks (H-21); the signup-season preamble is inlined 7 times with the `.get()` guard in
   only 1 (H-22, M-21); `/signup` and `/permfa` have already drifted apart (H-3, H-4).
3. **Hard failures inside the error paths meant to contain failure.** Both sync-loop handlers raised
   `TypeError` (C-2, *resolved*); `RscException.__init__` can raise `UnboundLocalError` (H-5) and
   silently drops status at 24 call sites (M-13); three of five background loops had no `.error`
   handler, so any of the above killed them permanently (C-5, *mitigated — loop bodies still lack
   per-guild containment*).
4. **Discord interaction lifecycle misunderstood in the highest-traffic user flow.** The signup form
   can lose a completed submission outright (C-0), can outlive its own token (H-14), and can blow
   the 3-second acknowledgement deadline under exactly the load it was built for (H-13).

**No CI exists** (`.github/` is absent). Every quality gate above is a local pre-commit hook that
`--no-verify` bypasses, and `pytest` is not among the hooks — so the 18.5k lines of tests never run
automatically.

### Where I would start

| # | Item | Effort | Why | Status |
|---|---|---|---|---|
| 1 | **C-2** — `exc=` → `exc_info=`, add one `continue` | 2 lines | Was a *guaranteed* failure that killed nightly role sync | **resolved** |
| 2 | **C-3** — restore the nine `override` permission checks | small | Live privilege escalation in the transaction suite | open |
| 3 | **C-4** — gate `/assign` and `/unassign` | small | `@everyone` could rewrite channel permissions | **resolved** |
| 4 | **C-1** — remove the `NICKM_ID` backdoor | small | Unauditable superuser grant across four guilds | open |
| 5 | **H-1** — un-hardcode the sync guild ID | trivial | Three of four discords have never auto-synced | open |
| 6 | **C-0 + H-2** — restructure the signup modal capture | medium | Silently losing real signups | open |
| 7 | **C-5** — add `.error` handlers to the three loops | small | Turns permanent silent death into auto-restart | **mitigated** — per-guild `try/except` still outstanding |
| 8 | **Add CI** — ruff, ty, pytest on push | small | Without it every fix above can silently regress | open |
| 9 | **H-22** — one `_require_league()` helper; delete `decorator.py` | medium | Makes nine existing error handlers actually fire | open |
| 10 | **H-21 / M-21** — collapse `roles.py` and the sync scaffold | large | Highest long-term payoff, highest regression risk — do it *after* CI | open |

With C-2 and C-5 closed, **H-1 is now the highest-value trivial fix left**: the role-sync loop no
longer dies on an API hiccup, but it still `continue`s past every guild except NA 3v3, so three of
four discords remain unsynced. C-2's fix makes the loop survive; H-1 is what makes it useful.

### Baseline metrics

| Metric | Value |
|---|---|
| `rsc/` production LOC / files | 35,585 / 130 |
| `tests/` LOC / collected tests | 18,524 / 1,421 (1,233 unit, 188 integration) |
| `scripts/` LOC | 3,880 — excluded from ruff and ty, no tests |
| Bare `except:` / silent swallows | **0 / 0** |
| `except Exception` (broad) | 34 — all logged with context |
| `ruff check` / `ty check` | 4 findings (all `PLC0415`) / clean |
| Naive `datetime` / `DTZ` suppressions | **0 / 0** |
| API call sites with an explicit timeout | **7 of 101** |
| Raw `self._league[guild.id]` indexes | **51** (vs 10 `.get()`) |
| `@tasks.loop` with an `.error` handler | **2 of 5** |
| Modules never imported by a test | 44 files, ~6,470 LOC (18%) |
| CI | **none** |

---

## Index

Findings appear below in the order they were established, not in severity order. This index groups
them. IDs are stable — cross-references throughout the report use them.

**Critical — fix before the next signup window**

| ID | Finding | Status |
|---|---|---|
| C-0 | A completed signup can be silently thrown away | open |
| C-1 | Hardcoded developer backdoor bypasses role-safety guards | open |
| C-2 | Both sync-loop error handlers raise a different exception, killing the loop | **resolved** |
| C-3 | The admin-override permission check is commented out in nine transaction commands | open |
| C-4 | `/assign` and `/unassign` have no permission gate at all | **resolved** |
| C-5 | Three of five background loops have no `.error` handler | **mitigated** |

**High**

| ID | Finding |
|---|---|
| H-0 | Three webhook endpoints accept unauthenticated state-changing requests |
| H-1 | Scheduled role sync is hard-gated to one guild by a magic number |
| H-2 | Abandoned signup modal leaks a coroutine forever |
| H-3 | `/permfa` has none of `/signup`'s guards and can raise `KeyError` |
| H-4 | An `except` handler that can itself raise |
| H-5 | `RscException.__init__` can raise `UnboundLocalError` |
| H-6 | `/transactions cut` decides Dev League eligibility from the wrong person |
| H-7 | Dev League "once per career" invariant is never recorded; role re-granted nightly |
| H-8 | A routed production endpoint is an empty stub that will 500 |
| H-9 | The backup script deletes the only remote backup before creating a new one |
| H-10 | A committed script load-tests production, and documents an unauthenticated endpoint |
| H-11 | `/llm summarize` ships private channel contents to OpenAI, uncapped |
| H-12 | `/intent search` exposes every player's roster intentions to every member |
| H-13 | `/signup` makes three API round-trips before acknowledging the interaction |
| H-14 | The signup flow can outlive its own interaction token |
| H-15 | The signup succeeds in the API, then the command dies applying Discord roles |
| H-16 | `except LeagueNotConfigured` is dead code on every signup path |
| H-17 | A duplicate FA check-in permanently kills the expiry loop |
| H-18 | Stale tier roles survive a re-signup |
| H-19 | Every `/ask` leaks an `httpx.AsyncClient` |
| H-20 | 93% of API calls have no request timeout |
| H-21 | `roles.py` repeats the same reconciliation 11 times; fixes land in one copy |
| H-22 | 51 raw `_league[guild.id]` indexes defeat the `LeagueNotConfigured` taxonomy |
| H-23 | `getProgressBar` returns a `discord.File` over a closed buffer |
| H-24 | `/transactions captain` reports failures as successes and names the wrong player |

**Medium** — M-0 through M-21, covering input validation, partial writes, duplication, blocking I/O,
N+1 patterns, cross-guild DM scoping, authorization model, and dependency hygiene.

**Low** — L-1 (no CI, test-coverage gaps), L-2 (security miscellany), L-3 (reliability miscellany).

---

## Findings

### C-1 — Hardcoded developer backdoor bypasses role-safety guards
`rsc/utils/utils.py:1128`, `:1137`, `:1241`, `:1250`

```python
if role.permissions > executor.guild_permissions and executor.id != const.NICKM_ID:
...
if role.position >= admin_role.position and executor.id != const.NICKM_ID:
```

`const.NICKM_ID` (`rsc/const.py:56`) is a literal Discord user ID. Both safety checks in the bulk
role add/remove commands — "you may not grant a role with permissions exceeding your own" and
"you may not touch roles at or above the admin role" — are unconditionally waived for that one
account, in **every guild the bot is in**.

These guards exist precisely because the commands they protect (`/addrole`, `/removerole` and their
bulk variants) are gated only by `@app_commands.checks.has_permissions(manage_roles=True)`
(`utils.py:1112`) — a permission most moderator roles carry.

**Why it matters:** this is a permanent, unauditable superuser grant that is invisible to server
owners, survives the removal of every Discord role that account holds, and applies to guilds the
author may not administer (EU, SSA, 2v2). If that account is compromised, the attacker needs only
`manage_roles` to then grant any role in any RSC discord, including roles above RSC Admin. It also
makes the guard untestable in the one workflow most likely to exercise it.

**Honest bound on severity:** Discord's own role hierarchy still applies to `member.add_roles`, so
the bot's own top role caps what can be granted. In practice a league bot sits near the top of the
hierarchy, so the cap is not much of one.

Related, same block: the rejection message at `utils.py:1138` is
`"Yeah right nerd. nickm has been notified."` — nothing in the code notifies anyone. A security
check that lies about alerting is worse than one that says nothing, because it discourages the
victim from reporting while producing no record.

### C-2 — Both error handlers guarding the sync loop raise a *different* exception, killing the loop permanently

> **RESOLVED.** `rsc/admin/sync.py:71, :80` now pass `exc_info=` instead of `exc=`, and the tiers
> handler `continue`s (`sync.py:72`). The `.error` backstop is at `sync.py:150-154`. Zero `exc=`
> sites remain in `rsc/`. Confirmed empirically: the old form raises
> `TypeError: Logger._log() got an unexpected keyword argument 'exc'` on every call; the new form
> does not. The description below is retained as the record of what was wrong.

`rsc/admin/sync.py:64-78`, `:121`, `rsc/logs.py:9-25`

```python
try:
    tiers: list[Tier] = await self.tiers(guild)
except RscException as exc:
    log.exception("Error fetching tiers", guild=guild, exc=exc)      # line 69

try:
    agm_map = await self.agm_franchise_map(guild)
except (RscException, RuntimeError) as exc:
    log.exception("Error fetching AGMs. Skipping guild.", guild=guild, exc=exc)   # line 77
    continue
```

Three defects stacked on the same nine lines.

**1. The handlers themselves throw.** `GuildLogAdapter.process` (`rsc/logs.py:9-25`) pops only
`guild` and `match`, then returns `kwargs` untouched. `exc=` therefore reaches
`logging.Logger._log()`, whose signature accepts only `exc_info` / `stack_info` / `stacklevel` /
`extra` → **`TypeError: _log() got an unexpected keyword argument 'exc'`**. These are the *only two*
`exc=` sites in the codebase; every other call correctly uses `exc_info=`. So both `except` blocks
raise unconditionally when they fire.

**2. The tiers handler does not `continue`.** The AGM handler directly below it does. If the
`TypeError` above were fixed, `tiers` would still be unbound at `:121` (`tiers=tiers`) →
`UnboundLocalError`.

**3. Nothing catches the result.** `sync_discord_roles` has no `@sync_discord_roles.error` handler,
and `discord.ext.tasks.Loop` **stops permanently** on an unhandled exception.

**Net effect:** the first time the API returns an error while fetching tiers or AGMs, the code
written to contain that error raises a different error, which escapes and kills nightly role sync
for the process lifetime. The only trace is a generic "Unhandled exception in internal background
task". Combined with H-1, the one guild that does sync silently stops syncing.

This is the cheapest fix in the audit — `exc=` → `exc_info=` and add one `continue` — and it is
currently a guaranteed failure, not a probabilistic one.

### H-1 — Scheduled role sync is hard-gated to one guild by a magic number
`rsc/admin/sync.py:60-62`

```python
log.info("Syncing discord roles", guild=guild)
if guild.id != 395806681994493964:
    continue
```

The loop logs "Syncing discord roles" for every guild and then silently skips all but one. There is
no config knob, no comment, and no log line explaining the skip. Read at face value, the EU, SSA,
and 2v2 discords get **no** automated role sync, and the logs actively claim otherwise. This has
the shape of leftover test-scoping that shipped.

### H-2 — Abandoned signup modal leaks a coroutine forever
`rsc/members/views/signup.py:424-432`

```python
info_modal = PlayerInfoModal(is_2v2=self._is_2v2)
await interaction.response.send_modal(info_modal)
await info_modal.wait()

if not info_modal.submitted:
    # User dismissed the modal
```

`PlayerInfoModal.__init__` (`:50`) calls `super().__init__()` with no `timeout`, and
`discord.ui.Modal`'s default is `timeout=None` (verified against installed discord.py 2.7.1). Discord
sends **no event when a user dismisses a modal**, so `wait()` never returns. The `if not
info_modal.submitted` branch and its comment are dead code.

**Consequence:** every abandoned signup leaks a suspended task holding the modal and the parent
view for the process lifetime. The parent view's own 600s timeout does fire, so `members.py:535`
resumes with `state == TRACKERS` and falls through to the `!= FINISHED` branch — the user is told
*"Signup failed for an unknown reason"* when they simply closed the box.

### H-3 — `/permfa` has none of `/signup`'s guards and can raise `KeyError`
`rsc/members/members.py:636-752` vs `:470-634`

`_member_signup` gates on `next_signup_season()` (`:480`), which surfaces `LeagueNotConfigured` and
`SignupsClosedException` as clean user-facing embeds, and checks for an existing league player
(`:508`, `:516`). `_member_permfa_signup` does **none** of this — it is the only signup command in
the codebase that never calls `next_signup_season` (verified by grep across `rsc/`).

`permfa_signup()` then does `league=self._league[guild.id]` (`:1328`) *outside* its `try` block. In a
guild where `prepare_league` has not populated `_league` (`rsc/core.py:290`), that is an unhandled
`KeyError` after the user has already filled out the entire 10-minute form. Same unguarded index at
`rsc/core.py:478` and `rsc/members/members.py:1200`.

### H-4 — `except` handler that can itself raise
`rsc/members/members.py:653`

```python
except RscException as exc:
    log.warning(f"MemberCreate exception during PermFA sign-up: {exc.response.body}")
```

`RscException.__init__` sets `self.response = kwargs.pop("response", None)` (`rsc/exceptions.py:51`) —
it defaults to `None`. Any `RscException` raised without a `response=` kwarg turns this log line into
`AttributeError: 'NoneType' object has no attribute 'body'`, escaping the handler and killing the
command. The equivalent line in `_member_signup` (`:532`) correctly uses `{exc}`.

### H-5 — `RscException.__init__` can raise `UnboundLocalError`
`rsc/exceptions.py:79-92`

```python
elif isinstance(self.response, BadRequestException) or (len(args) > 0 and isinstance(args[0], BadRequestException)):
    self.status = args[0].status
    if args[0].body:
        body = json.loads(args[0].body)
    elif self.response and self.response.body:
        body = json.loads(self.response.body)

    if body:          # <-- body may never have been assigned
```

A `BadRequestException` with an empty body and no `self.response` leaves `body` unbound. The error
path for the codebase's own error type crashes — the worst place to have a latent bug, because it
converts a handled API error into an opaque one at the point where diagnostics matter most.

### C-0 — A completed signup can be silently thrown away
`rsc/members/views/signup.py:422-442` + `rsc/members/members.py:535-552`

This is the most serious finding in the audit, and it is the one I would block a release on.

The parent view's 600-second timer is refreshed only when the *view* dispatches an item callback
(`discord/ui/view.py:595-596`). A modal submission is dispatched to the **Modal**, not the View. So
once `complete_step` parks on `await info_modal.wait()` (`:426`), the parent view's clock keeps
running while the user is typing.

The sequence:

1. User reaches the referrer select; the tracker modal opens. They alt-tab to look up their Steam64
   ID and find their tracker links.
2. At T+600s the view times out. `_dispatch_timeout` releases `signup_view.wait()` in
   `members.py:535` with `state == TRACKERS`.
3. `members.py:545` sees `state != FINISHED` and renders **"Signup failed for an unknown reason.
   Please try again, if the issue persists contact a staff member."**
4. The user submits the modal — Discord modal tokens stay valid for 15 minutes. `on_submit` fires,
   the orphaned task resumes, populates `rsc_name` and `trackers`, sets `FINISHED`, and re-renders
   the form over the failure message.
5. **`MemberMixIn.signup()` is never called.** Nothing reaches the API. No log line records the loss.

The player typed everything in and watched the form complete. They are not signed up. The only
symptom is a confusing error they were told to ignore ("please try again"), and staff have no
record to reconcile against.

The trigger is not exotic — it is a user who takes more than ten minutes to find their tracker
links, which is exactly the population the modal's own instructions ("Submit tracker links for
**ALL** of your accounts") are aimed at.

This and H-2 are two halves of one defect: the modal result is captured inside a component callback
that can outlive the view that owns it.

### C-3 — The admin-override permission check is commented out in nine transaction commands
`rsc/transactions/transactions.py:747, 858, 965, 1055, 1254, 1571, 1640, 1723, 1977`

```python
# if override and not interaction.user.guild_permissions.manage_guild:
#     await interaction.response.send_message(
#         embed=ErrorEmbed(description="Only admins can process an override.")
#     )
#     return
```

Nine identical copies, all commented out, with no TODO, no issue reference, and no replacement.
`override` flows through to `admin_override=True` on the API request (e.g. `self.cut(..., override=override)`
at `:762`), which is precisely the flag that bypasses league business rules — cap space, roster
limits, contract length, transaction windows.

The only remaining gate is the command group's
`default_permissions=discord.Permissions(manage_roles=True)` (`:416`). That is weak on two counts:
`default_permissions` is a *default* that Discord server admins can reassign per-command in
Integrations settings and is not enforced by the bot itself, and `manage_roles` is a much lower bar
than the `manage_guild` the dead code required. Any GM-tier role carrying `manage_roles` can
currently push overridden transactions.

### H-0 — Three webhook endpoints accept unauthenticated state-changing requests
`rsc/core.py:355-358` + `rsc/combines/runner.py:26-65`

```python
self._web_app.router.add_post("/combines_match", self.start_combines_game)
self._web_app.router.add_post("/combines_event", self.combines_event_handler)
self._web_app.router.add_post("/league_player_update", self.league_player_update_handler)
...
site = web.TCPSite(runner, "localhost", 8008)
```

None of the three handlers checks a header, shared secret, HMAC signature, or source — grepping
`runner.py` and `core.py` for `Authorization|secret|hmac|signature|X-` returns nothing but a
`# super secret tech` comment. The handlers act on entirely caller-supplied fields: a POST to
`/combines_event` with `{"message_type": "Finished", "guild_id": ..., "match_id": ...}` tears down
a combine lobby (`runner.py:55-63`), and `/combines_match` creates one.

Binding to `localhost` is the only control, which downgrades this from Critical to High: exploitation
requires code execution on the bot host, a co-tenant on a shared VPS, or an SSRF elsewhere on the
box that can reach `127.0.0.1:8008`. That is a meaningful mitigation, not a substitute for
authenticating a state-changing endpoint. A shared secret compared with `hmac.compare_digest` is a
few lines.

Related: `runner.py:33` logs the full webhook body via `pformat` at debug level, and `runner.py:31`
does the `from pprint import pformat` import inside the handler — two of the four outstanding
`PLC0415` lint findings.

### H-8 — A routed production endpoint is an empty stub that will 500
`rsc/leagues/leagues.py:34-35`

```python
async def league_player_update_handler(self, request: web.Request):
    log.debug("Got league player update event.")
```

The handler is registered at `/league_player_update` (`core.py:358`) but returns `None`. aiohttp
raises `Web-handler should return a response instance` and serves a 500. Whatever upstream system
posts league-player updates has been receiving errors and dropping them, silently, for as long as
this has been deployed. Either the route should be removed or the handler finished — shipping a
routed no-op is the worst of both.

### C-4 — `/assign` and `/unassign` have no permission gate at all

> **RESOLVED.** `/assign` and `/unassign` now require `manage_channels`; `/resolve` requires
> `manage_messages`. `/assign` additionally gained an `is_modmail_channel()` guard, a new helper
> that accepts the primary category *or* any group category — `is_modmail_thread` matches only
> group categories, so using it directly would have broken `/assign`'s main use case. Both exploits
> below are closed: the channel-hijack path now requires `manage_channels` *and* a real modmail
> ticket, and the mass-ping path requires `manage_channels`. **Confirm the permission choice matches
> your moderator roles** — see the Remediation status section.

`rsc/moderator/thread.py:186-222`, `:223-262`

```python
@app_commands.command(name="assign", description="Assign the current modmail to a specific group")
@app_commands.describe(group="Assignable ModMail group name")
@app_commands.autocomplete(group=thread_autocomplete)
@app_commands.guild_only
async def _thread_assign(self, interaction: discord.Interaction, group: str):
```

These are declared as top-level `@app_commands.command`, **not** as members of the `_thread` group
(`:52-57`), so they do not inherit its `default_permissions=manage_guild`. `guild_only` is not a
permission check. Verified by reading the full decorator stack on both.

Two independent exploits, both available to `@everyone`:

**Channel hijack.** `/assign` validates that the group exists and that the channel is a `TextChannel`
— it never checks that the channel is actually a modmail thread. (`/unassign` *does* check, at
`:234`, which shows the guard was known and simply omitted here.) The body then runs:

```python
await channel.move(end=True, category=category, sync_permissions=True)
```

Any member can run `/assign` in any channel they can type in — `#general`, `#announcements`, a
private staff channel — and the bot relocates it into a ModMail category and **overwrites its
permission overwrites** with the category's, using the bot's Manage Channels. A private staff
channel dropped into a ModMail-visible category becomes readable by that role. This is a
permission-rewriting primitive handed to every member of every RSC discord.

**Mass-ping laundering.** `:213-217` sends with `allowed_mentions=discord.AllowedMentions(roles=True)`,
so any member can loop `/assign`/`/unassign` to ping the moderator role indefinitely — attributed
to the bot rather than to them.

The irony worth stating in review: the joke `/feet` command 70 lines below (M-4) carries
`@app_commands.checks.has_permissions(manage_guild=True)`. The joke is better protected than the
command that rewrites channel permissions.

### H-11 — `/llm summarize` ships private channel contents to OpenAI with its authenticity check commented out and no spend cap
`rsc/llm/llm.py:436-560`, `:509-518`, `:697-731`

```python
# Only allow modmails
# if not self._contains_modmail_messages(history):
#     return await interaction.followup.send(
#         embed=ErrorEmbed(
```

Same pattern as C-3 — a guard commented out and shipped. `_contains_modmail_messages` still exists,
unused, at `:715-723`. What remains is `_is_private_ticket_channel` (`:697-731`), which accepts any
channel `@everyone` cannot view; its ≤40-viewer cap sits in an `elif` that applies only to
`TextChannel`, never to `Thread`. Any private staff channel, appeals channel, or private thread of
any size therefore qualifies.

The command reads up to 300 messages plus 10 image attachments (20 MB), base64-encodes them
(`:786-793`), and sends the lot to OpenAI. It never calls `check_budget` and never calls
`record_usage` — unlike `answer_with_agent` (`:849-862`). So the single most expensive operation the
bot can perform is exempt from the cooldown, both daily caps, and `/llm usage` accounting.

ModMail tickets carry player reports, appeals, and real-world identity claims. That is a PII flow to
a third party with no consent surface, and an unmetered cost channel.

### H-12 — `/intent search` exposes every player's roster intentions to every member
`rsc/members/members.py:113-118`, `:294-320`

```python
_intent = app_commands.Group(
    name="intent",
    description="Declare or check status of player intent to play",
    guild_only=True,
)                                   # no default_permissions
```

The `_intent` group carries no `default_permissions`, and `_intents_search_cmd` checks only that a
search criterion was supplied. Any member can enumerate, filtered by franchise or team, which
players have declared they are **not returning** next season and which have not responded.

That is competitively sensitive roster intelligence during the trade/draft window, and personally
sensitive — a player who told staff privately they are leaving has that surfaced to their GM's
rivals. The aggregate version of the same data, `/admin stats intents` (`rsc/admin/stats.py:22-30`),
*is* behind `manage_guild`, so the intended trust level is documented by the sibling command.

### H-6 — `/transactions cut` decides Dev League eligibility from the wrong person
`rsc/transactions/transactions.py:784-786`

```python
add_devleague_role = await self.should_get_devleague_role(interaction.user)
await update_cut_player_discord(guild=guild, player=player, response=result, ptu=ptu, devleague=add_devleague_role)
```

`interaction.user` is the admin running the command; `player` is the person being cut. Every other
call site passes the affected member — `rsc/admin/sync.py:110` (`m`), `:1005` (`member`),
`rsc/admin/members.py:613` (`member`). The two `interaction.user` uses in `rsc/members/members.py:602`
and `:721` are correct only because the user *is* the subject there, which is where this line was
copied from. Net effect: whether a cut player receives the Dev League role is determined by the
admin's history, so the same player gets a different outcome depending on who cuts them.

### H-7 — Dev League "once per career" invariant is never recorded, so the role is re-granted nightly
`rsc/transactions/roles.py:884-887` and `:991-994` vs `rsc/devleague/devleague.py:185-210`

```python
# roles.py — applies the role directly
if devleague:
    dev_league_role = discord.utils.get(guild.roles, name=const.DEV_LEAGUE_ROLE)
    if dev_league_role and dev_league_role not in player.roles:
        roles_to_add.append(dev_league_role)
```

```python
# devleague.py — the only place that records the grant
async def add_devleague_role(self, member):
    ...
    if member.id not in users:
        users.append(member.id)
        await self._save_devleague_role_users(member.guild, value=users)
```

The signup and sync paths bypass `add_devleague_role()` entirely, so `DevLeagueRoleUsers` is never
written for them. `should_get_devleague_role()` (`devleague.py:208`) consequently returns `True`
forever, and the nightly `sync_discord_roles` loop re-adds the role on every run. A player who
removes the role manually gets it silently restored each night. The comment "only add to users one
time in their career" (`members.py:601`, `transactions.py:783`) documents behaviour the code does
not implement.

Two secondary issues in the same area: the two paths resolve the role differently —
`utils.get_devleague_role()` (`utils.py:205`) vs an inline `discord.utils.get(...)` that silently
no-ops when the role is missing — and `add_devleague_role`/`remove_devleague_role` do an
unsynchronised read-modify-write on the Config list (`devleague.py:191-194`), so concurrent calls
during a sync drop entries.

### M-0 — `/rsc settings` crashes on exactly the guild you would run it to diagnose
`rsc/core.py:476-482`

```python
league = None
if self._league[guild.id]:      # KeyError when the guild was never prepared
    league = await self.league(guild)

league_str = "Not Configured"
```

The code three lines down is explicitly written to render `"Not Configured"`, so an unconfigured
guild is an expected input — but the direct dict index raises `KeyError` before reaching it.
`_league` is only populated by `prepare_league` on a successful API call (`core.py:287-290`). This
is the same unguarded-index class as H-3; `.get(guild.id)` is the fix in both.

**Credit:** the surrounding code is otherwise careful — the API key is reported as
`"Configured"/"Not Configured"` rather than echoed (`core.py:466`, `:490`), `/rsc setup` and
`/rsc league` carry `@bot_owner_required()`, and the URL is run through `validators.url` before
being stored.

### M-6 — `/rsc setup` responds twice to the same interaction
`rsc/core.py:521-532`

```python
await interaction.response.send_modal(setup_modal)
await setup_modal.wait()
setup_modal.stop()

if not (setup_modal.url and setup_modal.key):
    await interaction.response.send_message(          # already responded via send_modal
        embed=ErrorEmbed(description="You must provide a valid URL and API key."),
```

`send_modal` consumes the interaction response. The error branch then calls
`interaction.response.send_message`, which raises `discord.InteractionResponded`. The very next
block (`:535`) correctly uses `interaction.followup.send`, so the right pattern is four lines away.
`RSCSetupModal` (`rsc/views.py:248`) also declares no `timeout`, so it inherits `timeout=None` and
`setup_modal.wait()` hangs forever on dismissal — the same defect as H-2.

### C-5 — Three of five background loops have no `.error` handler, against the project's own written rule

> **MITIGATED — follow-up outstanding.** All five loops now carry an `.error` backstop following the
> existing `events.py:124-128` pattern (log with `exc_info`, then `restart()`). Verified by
> introspecting `Loop._error` on each loop object rather than trusting the decorator — 5 of 5
> registered.
>
> **This is not a full fix.** It bounds the *blast radius* of the remaining loop bugs without fixing
> them, and the loop bodies still have no per-guild containment — see the remaining-work note at the
> end of this section. **H-17** and
> the `expire_sub_contract_loop` failure modes described below now recur visibly on each tick
> instead of dying once and silently. Better, but still open.

| Loop | Location | `.error` handler (before → after) |
|---|---|---|
| `rsc_events_loop` | `rsc/events/events.py:94` | yes (`:124`) → yes |
| `retire_audit_loop` | `rsc/admin/retire.py:79` | yes (`:94`) → yes |
| `sync_discord_roles` | `rsc/admin/sync.py:55` | **no** → **yes** |
| `expire_sub_contract_loop` | `rsc/transactions/transactions.py:141` | **no** → **yes** |
| `expire_free_agent_checkins_loop` | `rsc/freeagents/freeagents.py:52` | **no** → **yes** |

The rule is stated explicitly in the codebase, at `rsc/events/events.py:106-109`:

> `# tasks.Loop only tolerates a handful of network errors before it stops permanently, and`
> `# ApiException/RscException/ValidationError are not among them. Contain every failure to the`
> `# guild it came from so one bad guild cannot kill the loop.`

and again at `:124-127`: `# Backstop. A loop that raises out of _loop never restarts on its own.`

The three formerly-unprotected loops also lack any per-guild `try/except` around their bodies, and
**that part is still open.** `expire_sub_contract_loop` awaits `_get_substitutes`, `_trans_channel`,
`get_subbed_out_role` (which raises a bare `ValueError` at `utils.py:311` when the role is missing),
`tchan.send`, and `m_out.remove_roles`. Any `Forbidden`, missing role, or API error still aborts
contract expiry league-wide for that tick — the `.error` backstop restarts the loop, but the failure
recurs until its cause is addressed.

The consequences were silent and business-visible: temp-FA contracts stop expiring, players keep
`Subbed Out` roles, FA check-ins never clear. C-2 and H-17 are two concrete routes into this. The
missing handler was what made them permanent rather than transient; adding it converts a silent
permanent death into a loud recurring one, which is the right trade but not a fix for the causes.

**Remaining work on this finding:** wrap each loop body in a per-guild `try/except` following the
`events.py:103-113` pattern, so one bad guild cannot abort the tick for the others.

### H-19 — Every `/ask` leaks an `httpx.AsyncClient`
`rsc/llm/agent/service.py:124-131`, `rsc/llm/llm.py:863-883`

```python
ctx = AgentContext(
    cog=cog, guild=guild,
    client=AsyncOpenAI(api_key=api_key, organization=org),
    ...
)
```

`build_agent_context` is called per question and nothing ever closes `ctx.client`. Each
`AsyncOpenAI` owns an `httpx.AsyncClient` with its own connection pool.

This contradicts two deliberate designs in the same codebase. `rsc/abc.py:96-105` keeps a
long-lived `ApiClient` per guild specifically because *"the previous `async with ApiClient(...)`
pattern paid a fresh TCP + TLS handshake on every single call."* And `rsc/llm/summarize.py:65-104`
creates the same OpenAI client and correctly does `await http_client.aclose()` in a `finally`. The
agent path is the one that got missed.

**Consequence:** unbounded socket/FD growth proportional to `/ask` volume across four guilds, a TLS
handshake per question, and `Unclosed client session` warnings at GC. The fix is to copy
`summarize.py:104`.

### H-20 — 93% of API calls have no request timeout
`rsc/const.py:10-14` + 101 call sites

The rule is written down:

> `# rscapi defaults to a 300 second per-request timeout, which lets a hung API stall startup for`
> `# five minutes with empty caches. Pass API_TIMEOUT explicitly on calls where waiting that long`
> `# is never the right answer.`

It is applied at 7 of 101 `await api.*` sites — `tiers.py` (3), `events.py` (2), `franchises.py` (1),
`teams.py` (1). Zero in the highest-traffic modules: `members.py` (18 calls), `transactions.py` (14),
`leagues.py` (10), `trackers.py` (9), `matches.py` (8), `seasons.py` (6).

Combined with `API_RETRIES = 3` and `ExponentialRetry` (`core.py:319-322`), a hung GET/PUT/DELETE
can block for **~900 seconds**. A deferred interaction token is dead after 15 minutes, so the user
sees nothing, ever. `paged_players` (`leagues.py:358-403`) and `paged_members`
(`members.py:1047-1082`) loop these untimed calls with no overall deadline, and
`sync_discord_roles:85` iterates the entire league through `paged_players` that way.

Worth noting the fix is one line in the shared `Configuration` rather than 94 edits — setting the
default there covers every call site at once.

### H-21 — `rsc/transactions/roles.py` repeats the same reconciliation 11 times, and fixes land in one copy

Eleven top-level `update_*_discord` functions each re-implement a ~60-line role-reconciliation
sequence. The file contains 83 occurrences of `in player.roles:` and 52 `get_*_role(guild)` calls.

The danger is demonstrated in-tree. `roles.py:733-742` records a real bug fix:

```python
# `league_player.status`, not `player.status`: `player` is a discord.Member,
# whose `status` is online/idle/offline and never equals a league Status. As
# written before, the IR role was never added and always removed -- which hit
# AGM IR members in particular.
ir_role = await utils.get_ir_role(guild)
if league_player.status in [Status.IR, Status.AGMIR] and ir_role not in player.roles:
```

That fix exists in **exactly one** of the five IR blocks. The other four (`:624-626`, `:854-856`,
`:976-978`, `:1052-1054`) are still the unconditional-remove form. That may be correct per-status —
but nothing in the code says so, and no shared helper enforces it, so the next status added will
silently inherit the wrong branch.

H-7 and H-18 in this report are both instances of the same failure mode. This is the largest
maintainability liability in the repository, and the one I would fix last — after CI exists, because
the regression risk is real.

### H-13 — `/signup` makes three API round-trips before acknowledging the interaction
`rsc/members/members.py:472-526`

```python
signup_season = await self.next_signup_season(guild)                              # HTTP #1
plist = await self.players(guild, season=signup_season.id, discord_id=..., limit=1)   # HTTP #2
prev_list = await self.players(guild, season_number=..., discord_id=..., limit=1)     # HTTP #3
signup_view = SignupView(interaction)
await signup_view.prompt()      # FIRST acknowledgement
```

Discord's initial-response deadline is **3 seconds**. There is no `defer()` on this path, and the
codebase already has the right helper — `rsc/utils/utils.py:173-196 safe_defer()` — which is simply
not used here.

On signup night with the API under load at 1.5s per call, `prompt()` fires at T+4.5s and
`interaction.response.send_message` raises `NotFound` (10062 Unknown Interaction). The user sees
"The application did not respond." Under load this fails for **everyone simultaneously** — precisely
when the command matters most.

Note the fix is structural, not a one-liner: `prompt()` (`signup.py:393-395`) uses
`interaction.response.send_message`, so adding a `defer()` in front would raise
`InteractionResponded`. The view has to send via `followup`.

The correct pattern already exists in this codebase — `IntentDMButton.callback`
(`rsc/admin/views.py:192-296`) defers first, with an explicit comment about the 3-second budget. The
inconsistency is the bug.

### H-14 — The signup flow can outlive its own interaction token
`rsc/members/views/signup.py:366`

The 600s view timeout is **per step**, refreshed on each interaction, across seven steps — so the
flow may legitimately run ~70 minutes. Every terminal message is delivered via
`interaction.edit_original_response` on the *original* command interaction (`signup.py:441`;
`members.py:538, 546, 574, 585, 593, 624`; `views.py:55`). An interaction token is valid for
**15 minutes, total**.

A user who reads the rules link carefully, agrees at T+8min, and submits the modal at T+16min gets:
`edit_original_response` raises `NotFound` at `signup.py:441`, but `self.stop()` on the line above
already ran — so `members.py` proceeds with `state == FINISHED`, **calls the API successfully**,
applies roles, and then dies on `edit_original_response` at `:624`.

The player is signed up, has roles, and sees a stale form with no confirmation. They re-run
`/signup` and land in the 409 path. `AuthorOnlyLayoutView.on_timeout` (`views.py:47-55`) has the
same exposure with no `try/except`.

### H-15 — The signup succeeds in the API, then the command dies applying Discord roles
`rsc/members/members.py:611-622` (identical at `:731-741`)

```python
# The sign up itself is already recorded in the API, so a discord
# problem here must not be reported back as a failed sign up.
nickname_note = ""
try:
    await update_league_player_discord(...)
except DiscordNameTooLong as exc:
```

The comment states the intent correctly and the code implements only one case of it. The call chain
raises several other things that are not caught:

- `rsc/utils/utils.py:213-218, 261-290` — every `get_*_role` helper raises bare `ValueError` when
  the role is missing from the guild.
- `rsc/transactions/roles.py:997-1000` — `add_roles`/`remove_roles` raise `discord.Forbidden` /
  `discord.HTTPException`.
- `rsc/transactions/roles.py:1125, 1160, 1171` — `raise ValueError` on unexpected API status.

**Scenario:** the `Draft Eligible` role gets renamed during off-season cleanup.
`get_draft_eligible_role` raises `ValueError`; it escapes `_member_signup`. The API has the signup;
the player has no league role, no DE role, no nickname, and a form with no result. `/signupstatus`
reports them as signed up, so nobody diagnoses it. Because `interaction.response` was already
consumed by `prompt()`, Red's error handler cannot surface anything either.

Widening the `except` to `(DiscordNameTooLong, ValueError, discord.Forbidden, discord.HTTPException)`
would make the code match its own comment.

### H-16 — `except LeagueNotConfigured` is dead code on every signup path
`rsc/members/members.py:479-488`, `rsc/seasons/seasons.py:63-73`

```python
try:
    signup_season = await self.next_signup_season(guild)
except LeagueNotConfigured:
    return await interaction.response.send_message(embed=YellowEmbed(title="Not Configured", ...))
```

```python
async def next_signup_season(self, guild) -> Season | None:
    async with self.api_client(guild) as client:
        league_id = self._league[guild.id]      # raises KeyError, not LeagueNotConfigured
```

`LeagueNotConfigured` is raised in exactly one place in the codebase — `seasons.py:28`, inside
`next_season()`, a *different* method. The friendly "Not Configured" embed can never fire; an
unconfigured guild gets `KeyError` and "The application did not respond."

The same dead handler is copy-pasted at `members.py:139, 242, 333`, `admin/members.py:667`,
`admin/intents.py:204`, `admin/stats.py:42, 121, 276`. `admin/intents.py:290-291` documents this
exact trap and works around it with an explicit `_api_conf`/`_league` presence check — so the
problem was understood, and the member-facing path just never got the fix. This is the root cause
behind H-3 and M-0.

### H-17 — A duplicate FA check-in permanently kills the expiry loop
`rsc/freeagents/freeagents.py:168-242`, `:376-388`, `:68-72`

`is_checked_in()` is consulted at `:169`, *before* the confirmation view; `add_checkin()` runs at
`:242` with no re-check, and is itself an unsynchronised read-modify-write over Red `Config`
(`:376-381`). Then:

```python
async def remove_checkin(self, guild, player: CheckIn):
    current = await self._get_check_ins(guild)
    current.remove(player)          # ValueError if absent
```

**Scenario:** the FA confirm button never acknowledges its own interaction
(`rsc/freeagents/views.py:33-53` accepts `interaction` and never defers or edits it), so every user
who clicks Confirm sees the message update *and* a red "This interaction failed" toast. They
reasonably conclude it did not work and click again — both invocations passed the `:169` guard, so
two identical `CheckIn` dicts are stored. `/freeagent checkout` removes one; they still show as
available. Next day the expiry loop hits the stale duplicate, `list.remove` raises `ValueError`,
and `discord.ext.tasks` terminates the loop.

**Still open, but no longer permanent.** Before the C-5 fix this meant FA availability never expired
again until the bot restarted, and GMs made roster decisions off days-old data. The loop now
auto-restarts — but it will hit the same stale duplicate on the next tick and crash again, so
expiry stays broken and the log fills with restarts until the duplicate is cleared. The root causes
are untouched: the `:169` guard is checked before the confirmation view rather than before the
write, `add_checkin` is an unsynchronised read-modify-write, and `remove_checkin` uses
`list.remove` without guarding for absence.

### H-18 — Stale tier roles survive a re-signup
`rsc/members/members.py:613-619` + `rsc/transactions/roles.py:923-937`

`update_league_player_discord` is called **without** `tiers=`, which defaults to `None` → `[]`
(`roles.py:1116-1117`). Inside `update_draft_eligible_discord`:

```python
if tiers and league_player.tier and league_player.tier.name:
    for r in player.roles: ...          # dead: tiers == []
elif tiers:
    ...                                 # dead: tiers == []
```

Both tier-*removal* branches are unreachable, while `:969-972` still *adds* the new tier role.

A player who was `Elite`, got dropped, and re-signs into `Master` ends up holding **both** tier
roles plus any `EliteFA` role. Every tier-scoped channel permission, ping, and role-keyed lookup
now sees them in two tiers until an admin runs a full sync. `admin/members.py:623-629` has the same
omission.

### M-1 — Tracker links receive zero validation
`rsc/members/views/signup.py:437`, `rsc/members/members.py:555` / `:676`

```python
self.trackers = links_input.value.splitlines()
...
tracker_list = list(filter(None, signup_view.trackers))
```

The only checks are a `min_length=50` on the whole paragraph field and a falsy-filter. A line of
spaces is truthy and survives. Nothing verifies the lines are URLs, are tracker URLs, are deduped,
or are stripped. `validators` is a declared dependency used exactly once in the entire codebase
(`rsc/core.py:535`) — the obvious tool is already present and unused here. Garbage flows straight
into `SignupDetailsRequest.tracker_links` and lands in the league database for a human to clean up.

### M-2 — Cancelling a signup still creates an API member record
`rsc/members/members.py:525-535` (and `:646-656`)

```python
signup_view = SignupView(interaction)
await signup_view.prompt()

# Create a member just in case
await self.create_member(guild, interaction.user, rsc_name=interaction.user.display_name)

await signup_view.wait()
```

`create_member` fires while the form is still open. A user who cancels, times out, or closes the
modal leaves behind a member record seeded with their Discord display name. There is no
compensating delete. "Just in case" is doing load-bearing work in a comment.

### M-3 — Timeout produces two contradictory messages
`rsc/views.py:47-55` + `rsc/members/members.py:545-552`

`AuthorOnlyLayoutView.on_timeout` edits the original response to "Time Out", then `wait()` returns
and `members.py` immediately overwrites it with *"Signup failed for an unknown reason. Please try
again, if the issue persists contact a staff member."* The user is told to contact staff about a
plain timeout. `on_timeout` also calls `edit_original_response` with no `try/except`, so a dismissed
ephemeral message or expired token raises inside the timeout task.

### M-4 — Joke command posts targeted content naming a real user
`rsc/moderator/thread.py:286-294`

```python
@app_commands.command(name="feet", description="Moar feet pics!!!")
@app_commands.checks.has_permissions(manage_guild=True)
async def _this_is_a_secret(self, interaction: discord.Interaction):
    """This is a secret. Nobody say anything... :shh:"""
    await interaction.response.send_message(
        "@everyone send <@!249326300148269058> some feet pics!",
        allowed_mentions=discord.AllowedMentions.none(),
    )
```

`allowed_mentions=none()` suppresses the ping but not the text. Any user with `manage_guild` in any
RSC discord can post a public message soliciting sexual content directed at a specific, identifiable
person. This is a moderation liability in a league bot serving a community with minors, and it is
undocumented and unreviewable by the servers running it.

### M-5 — ~120 lines duplicated verbatim between the two signup commands
`rsc/members/members.py:470-634` vs `:636-752`

Cancel handling, failure handling, tracker filtering, the 409/405/default error match, dev-league
role resolution, `update_league_player_discord` + `DiscordNameTooLong` handling, and the success
view are copy-pasted. H-3 and H-4 are both direct consequences: the copies have already drifted.
(`"permenent"` at `:747` is also a typo in user-facing text.)

### H-9 — The backup script deletes the only remote backup before creating a new one
`scripts/bot_backup.sh`

```bash
#!/bin/bash

tar -czvf $HOME/backup/rsc_bot_backup.tar.gz $HOME/.local/share/Red-DiscordBot
gcloud storage rm gs://rsc-storage-bucket/rsc_bot_backup.tar.gz
gcloud storage cp $HOME/backup/rsc_bot_backup.tar.gz gs://rsc-storage-bucket/rsc_bot_backup.tar.gz
```

Delete-then-write, with no `set -euo pipefail` and no exit-status check on any step. Any failure in
the `cp` — expired gcloud credentials, network blip, full disk during `tar`, bucket permission
change — leaves the bucket **empty**. If `tar` fails, the script cheerfully deletes the good remote
copy and uploads a truncated or stale local file. There is one rolling backup with no versioning or
retention, so a corrupt run also destroys the last good state.

That archive is `~/.local/share/Red-DiscordBot`, which holds every guild's Config — including the
stored RSC API keys and all bot settings. Write-then-swap (upload to a timestamped object, then
delete old ones) plus `set -euo pipefail` and quoted `"$HOME"` would fix it. Enabling object
versioning on the bucket would make the whole class of failure survivable.

### H-10 — A committed script load-tests production, and documents an unauthenticated endpoint
`scripts/brute_test_combines_check_in.py:13-21`

```python
CHECKIN_URL = "https://devleague.rscna.com/c-api/check_in"

def combines_check_in(discord_id: int) -> int:
    params = {"discord_id": discord_id}
    r = requests.get(url=CHECKIN_URL, params=params, timeout=10)
```

Two separate problems. First, a repo-committed tool ("Brute Force Break Blisters Shit") points at
the **production** host by default, takes a file of Discord IDs, and fires check-ins with no
`--dry-run`, no staging default, no confirmation prompt, and no rate limiting. Anyone who clones
the repo can abuse production in one command.

Second, and more important: the script demonstrates that the combines check-in endpoint is an
unauthenticated **GET** keyed on nothing but `discord_id`. Any third party who knows a player's
Discord ID — which is trivially obtainable — can check that player in, or check in the entire
league, with `curl`. Check-in drives combine lobby assignment, so this is a griefing vector against
live combines.

That endpoint lives in the RSC web API, not this repository, so it is outside the scope of a fix
here — but this repo is where the evidence sits, and it should be raised with whoever owns that
service.

### H-22 — 51 raw `self._league[guild.id]` indexes defeat the `LeagueNotConfigured` taxonomy
`rsc/seasons/seasons.py:26-28`, `rsc/exceptions.py:131`, and 51 call sites

This is the root cause behind H-3, H-16, and M-0, and it deserves its own entry because the fix is
one helper.

`LeagueNotConfigured` exists (`exceptions.py:131`) and nine command handlers catch it to give the
user an actionable message. But the only place that raises it does so *after* an unguarded index:

```python
league_id = self._league[guild.id]          # KeyError here on an unconfigured guild
if not league_id:
    raise LeagueNotConfigured("Guild does not have a league configured.")
```

`_league` is only populated by `prepare_league()`, which `_setup_guild` skips entirely when the
guild has no API config (`core.py:227-231`). So on an unconfigured guild all nine handlers miss and
the user gets a bare "This interaction failed". 51 raw indexes vs 10 `.get()` calls.

The codebase documented the workaround instead of fixing it —
`rsc/admin/intents.py:291-292`, repeated verbatim at `admin/views.py:221` and `:436`:

> `# next_signup_season indexes _api_conf/_league directly, so an unconfigured guild raises`
> `# KeyError rather than LeagueNotConfigured. Same guard as rsc.decorator.apicall.`

**And the guard it points at is dead and broken.** `rsc/decorator.py`:

```python
def apicall(f):
    @wraps(f)
    def wrapper(self: RSCMixIn, guild: discord.Guild, *args, **kwargs):
        if not self._league.get(guild.id): raise ValueError(...)
        if not self._api_conf.get(guild.id): raise ValueError(...)
        return f(self, *args, **kwargs)      # drops `guild`
```

It is applied to **zero** functions, and applying it to any of the 51 sites would break them
immediately, because it forwards `*args` without `guild`. A comment in three files points readers
at a decorator that has never worked.

One `_require_league(guild) -> int` helper replacing the 51 indexes would make the nine existing
handlers fire, and `rsc/decorator.py` should be deleted.

### H-23 — `getProgressBar` returns a `discord.File` over a closed buffer
`rsc/utils/images.py:83-89`

```python
with io.BytesIO() as buf:
    progress_bar.save(buf, format="PNG")
    buf.seek(0)
    dFile = discord.File(filename="progress.jpeg", fp=buf)

return dFile            # buf.__exit__ already ran
```

The test suite already says this out loud — `tests/test_images.py:90-92`:

> `# getProgressBar builds the buffer inside a with io.BytesIO() block and returns a File wrapping`
> `# it. That only survives because discord.File stubs out fp.close(). If that ever changes the`
> `# buffer arrives closed.`

Called 8× across `rsc/admin/sync.py`. A discord.py minor-version bump that stops monkey-patching
`fp.close` breaks all four `/admin sync` progress commands simultaneously. Writing the test that
documents the landmine, and then leaving the landmine, is the wrong end of the trade — the fix is to
build the buffer without the `with`.

(Secondary: the filename is `progress.jpeg` while the payload is PNG. `test_images.py:107-110`
documents this as load-bearing because `sync.py` references `attachment://progress.jpeg`.)

### H-24 — `/transactions captain` reports failures as successes and names the wrong player
`rsc/transactions/transactions.py:1373-1451`

Three bugs in one command:

```python
argv = locals()                                     # :1373 — reflection over parameters
...
for captain in captains:
    plist = await self.players(guild, discord_id=captain.id, limit=1)
    if not plist:
        await interaction.followup.send(
            content=f"{player.mention} is not a league player. Skipping...",   # :1387
```

`player` is the *first* command parameter (`:1359`), not the loop variable `captain`. Every "not a
league player" message names player #1 regardless of which of the seven actually failed.

```python
    except ValueError as exc:
        await interaction.followup.send(embed=ErrorEmbed(description=str(exc)))   # :1437
        # no `continue` — unlike the RscException arm at :1435
    results.append(captain)                                                       # :1443
```

A `ValueError` from `update_team_captain_discord` (missing Captain role, etc.) still appends to
`results`, and the final embed reports **"Captains Updated"**. The command tells an admin the
operation succeeded when it did not.

```python
embed.add_field(name="Players", value="\n".join([m.mention for m in results]), inline=False)  # :1451
```

If every candidate was skipped, `results == []` → `value=""` → Discord rejects an empty field value
with a 400 and the command dies on a raw HTTP error.

Also `argv = locals()` + `k.startswith("player")` is reflective parameter discovery that will
silently misbehave if a future parameter is named `player_override` or `players`.

### M-16 — `/admin franchise delteam` adds to the cache instead of removing
`rsc/admin/franchise.py:133-135`

```python
# Update team cache
if team in self._team_cache[guild.id]:
    self._team_cache[guild.id].append(team)
```

Inverted condition: a deleted team is *duplicated* in the autocomplete cache rather than removed.
Both correct forms exist in the same file — `:81-82` (`if name not in ...: append`) and `:436-437`
(`if franchise in ...: remove`). Deleted teams stay autocompletable, and accumulate duplicate
entries on repeat, until a cog reload.

### M-17 — File-descriptor leak in the sub-contract expiry loop
`rsc/transactions/transactions.py:169-171`

```python
for s in subs:
    sub_date = datetime.fromisoformat(s["date"])
    dFiles = [discord.File(img_path)]        # opened for EVERY sub
    if sub_date.date() <= yesterday.date():  # ...only used inside this branch
```

`discord.File(path)` opens the file immediately. A `File` for a non-expiring substitute is created,
never sent, never closed, and released only at GC — one FD per substitute per daily run. It is also
synchronous disk I/O on the event loop. Moving the construction inside the `if` fixes both.

### M-18 — Blocking CPU and disk work on the event loop, inconsistently with the codebase's own pattern

- `rsc/utils/utils.py:101-113` `resize_image` and `:116-123` `img_to_thumbnail` are `async def` with
  **no `await` in the body** — pure synchronous PIL. The `async` is misleading: it provides no
  concurrency and hides the blocking.
- `rsc/utils/images.py:57-89` `getProgressBar` — `Image.new` + draw + PNG encode, called from async
  handlers *inside a loop*, every 10 players (`sync.py:1135, 1208, 1333`).
- `rsc/admin/sync.py:445` — `fa_img_path.read_bytes()`, sync disk read inside the tier-sync loop.
- `rsc/llm/agent/tools/docs.py:54` and `rsc/llm/rulebook.py:306` — sync `read_text` in async paths.

The right pattern is already in use elsewhere: `rsc/ballchasing/process.py:192, 212`
(`await asyncio.to_thread(...)`), `rsc/llm/rulebook.py:330`, and `aiofiles` in `developer.py:58` and
`ruleloader.py:287`. It simply was not applied here.

### M-19 — N+1 API patterns with no concurrency limit anywhere

There is no `asyncio.Semaphore` and no rate limiter anywhere in `rsc/`.

| Site | Pattern |
|---|---|
| `rsc/admin/sync.py:85-134` | iterate whole league → `franchises()` + `should_get_devleague_role()` + role edits, per player |
| `rsc/transactions/transactions.py:2721-2810` | `players(discord_id=...)` and `teams(...)` per traded player |
| `rsc/transactions/transactions.py:2688-2711` | `await utils.remove_prefix(m)` per GM-role member — an `async def` doing pure `str.split` |
| `rsc/admin/sync.py:628-691` | `get_franchise_transaction_channel()` then `channel.send()` per franchise |

Additionally the four sync commands call `interaction.edit_original_response(attachments=[dFile])`
every 10 items, **re-uploading a PNG each time** — on a 1,000-player league that is 100 Discord
attachment uploads per run.

Unbounded fetches sit next to working pagination: `limit=10000` at `admin/sync.py:1254`,
`admin/stats.py:231`, `admin/inactivity.py:312`; `limit=1000` at `teams/teams.py:425` and
`freeagents/freeagents.py:421, 425` — while `_sync_freeagent_cmd` right next door correctly uses
`paged_players`. Pagination itself is implemented four times with divergent shapes
(`leagues.py:358` checks `next` *outside* the `async with`; `members.py:1047` *inside*).

### M-20 — `/admin dmcancel` purges the DM queues of all four guilds
`rsc/core.py:140`, `rsc/utils/dm.py:127-158`, `rsc/admin/admin.py:178-196`

One process-wide `DMHelper()` is correct — Discord rate limiting is a global constraint. The problem
is that global operations are exposed through per-guild commands with no scoping:

`purge()` drains the entire `asyncio.Queue` and clears `_scheduled`. `_admin_dmcancel_cmd` is a
per-guild slash command with, by design, **no confirmation gate** (`admin.py:194-195`). An NA 3v3
admin aborting an NA 3v3 batch silently destroys EU's and SSA's queued intent-to-play DMs — with no
warning and no way to tell what was lost.

`_success` / `_failed` / `_total` / `_failed_members` are likewise global, so `/admin dmstatus`
reports the whole bot's numbers. The code documents this as a known caveat (`dm.py:104-106`,
`admin/admin.py:165-167`) rather than fixing it. Head-of-line blocking compounds it: a 2,000-DM
batch at `DEFAULT_RATE = 1.5s` delays every other guild's DMs by ~50 minutes.

Given how good the rest of `dm.py` is, adding a `guild_id` to `DMTask` and filtering `purge()` and
the counters on it is a small change with a large correctness payoff.

### M-21 — Structural duplication: ~400 lines that should not exist

- **The signup-season preamble is inlined 7 times** while an extracted helper sits nearly unused.
  `_signup_season_or_error()` exists at `rsc/admin/intents.py:283-300` and is called twice. The same
  ~15-line `try/except` is inlined at `members/members.py:138, 241, 332, 480`,
  `admin/stats.py:41, 120, 275`, `admin/members.py:666`, `admin/intents.py:203`. Because it is
  inlined, only `intents.py` carries the `.get()` guard from H-22 — the other seven still `KeyError`.
- **`rsc/admin/match.py:57-137` ≡ `:152-232`** — ~80 lines of team resolution and validation copied
  verbatim between `_matches_create_cmd` and `_matches_playoff_cmd`.
- **Four `/admin sync` commands** (`sync.py:721, 837, 1039, 1247`) share an identical ~110-210 line
  scaffold differing only in which `update_*_discord` they call — and have already diverged
  (`_sync_freeagent_cmd` paginates, `_sync_drafteligible_cmd` uses `limit=10000`).
- **`rsc/utils/utils.py:205-324` — 14 `get_*_role()` functions**, each an identical 8-line
  `discord.utils.get` / log / `raise ValueError`. ~120 lines that should be one
  `get_role(guild, name)`.
- **Dead branch:** `rsc/admin/sync.py:1055-1070` checks `if not tiers:` twice in a row with
  different embed classes; the second is unreachable.

### M-12 — Three guards that were written but never wired up

A recurring pattern worth calling out as a class, because the fixes are mechanical and each is
independently testable:

**`/welcome toggle` is pure theatre.** `on_join_welcome` (`rsc/welcome/welcome.py:25-43`) reads
`_get_welcome_roles`, `_get_welcome_channel`, and `_get_welcome_msg` — it never calls
`_get_welcome_status`. That accessor exists at `:193-194` and is read only by `/welcome settings`
(`:63`) and `/welcome toggle` (`:88`) itself. An admin who disables welcomes during a raid gets
"Welcome message has been **disabled**" and the bot keeps granting welcome roles and posting
messages for every joining account. (Verified by grep: three references, none in the listener.)

**The FA `visible` back-fill can never fire.** `rsc/freeagents/freeagents.py:291-299`:

```python
v = c.get("visible")
if v is None:
    c["visible"] = True
# Skip if not visible (False)
if not v:
    continue
```

The repair writes `c["visible"]` but the guard tests the stale local `v`, still `None`. `not None`
is `True`, so the player is skipped anyway — and the mutation is never persisted (`_save_check_ins`
is not called), so it repeats forever. Legacy check-ins written before the `visible` key existed are
permanently invisible to `/freeagent availability`, while `/freeagent checkin` insists the player is
already checked in. The comment ("Yes this happened... the first day I wrote this code") shows the
author intended the opposite behaviour.

**The `_2V2_GUILD_ID` branch validates nothing.** `signup.py:68` changes the *displayed* "50 games"
requirement between 2v2 and 3v3. Nothing enforces it anywhere.

### M-13 — `RscException` silently loses status and reason at 24 call sites
`rsc/exceptions.py:50-58` + 24 raise sites

```python
except ApiException as exc:
    raise RscException(exc)          # positional
```

The constructor pops `response` from **kwargs** (`exceptions.py:51`). Passed positionally,
`self.response is None`, the `isinstance(self.response, RscApiException)` branch at `:58` is skipped,
and `self.status`, `self.reason`, and `self.type` all stay `None`.

24 sites raise positionally (`leagues/leagues.py:215, 224, 233, 242, 251, 287, 322, 356, 399`;
`teams/teams.py:653-756`; `members/members.py:1045-1179`; `matches/matches.py:691`) against 65 that
correctly use `response=`.

**Consequences:** `ApiExceptionErrorEmbed` (`embeds.py:245-260`) renders "An unknown error
occurred… Status: None" for all of them, and every `exc.status == 409` branch — `members.py:573`,
`admin/views.py:275` — silently never matches. So the "You are already signed up" message a player
should see becomes a generic red error, depending on which internal helper raised.

This is the same root defect as H-4 and H-5, seen from a third angle: `RscException`'s constructor
signature is easy to call wrongly and fails silently when you do.

### M-14 — Returning players get 30 seconds to declare intent
`rsc/members/members.py:879` → `rsc/views.py:62` → `rsc/const.py:7`

`IntentToPlayView` takes the `DEFAULT_TIMEOUT = 30.0`. The flow requires reading a prompt, opening
a dropdown, choosing an option, and pressing a separate Confirm button
(`rsc/members/views/intent.py:71-81`).

The signup view deliberately uses 600s; the intent flow — which `/signup` *silently redirects
returning players into* (`members.py:511, 520`) — kept the 30s default. Combined with M-3, a
returning player who hesitates for half a minute is told *"Something went wrong declaring your
intent to play. Please submit a modmail for assistance"* (`members.py:898-906`). During an intent
push that is a lot of avoidable noise pointed at staff.

### M-15 — Combines lobby creation crashes after creating channels
`rsc/combines/runner.py:248`, `rsc/combines/combines.py:182`

```python
home_fmt[0] += " (Makes Lobby)"     # IndexError when lobby.home is empty
```

Reached from `create_combine_lobby_channel` (`:219`) **after** both voice channels are already
created (`:204-215`). `start_combines_game`'s `try` only catches `pydantic.ValidationError`
(`:78-84`), so the `IndexError` escapes to aiohttp as a 500. Orphaned `elite-4471-home` /
`-away` channels accumulate and no player is told the lobby exists. The external service sees a 500
and retries, which then hits the "Combine lobby already exists" early-return at `:129-137` and
returns `[]` silently.

Separately, `combines.py:182` uses `zip(result.home, result.away, strict=True)`, which raises
`ValueError` on any uneven lobby (a 3v2, a forfeit) with no handler and no response sent yet.

### M-7 — `default_permissions` is the only authorization control for nearly every privileged command

`default_member_permissions` is a Discord-side *default*. A guild administrator can reassign it
per-role and per-channel in Server Settings → Integrations, after which the bot performs **no**
server-side re-check. That is the sole guard on:

| Group | Declared at |
|---|---|
| `/admin *` (bulkretire, directmessage, dmcancel, …) | `rsc/admin/admin.py:75-79` |
| `/admin sync *` (7 role-rewriting commands) | `rsc/admin/sync.py:147-152` |
| `/admin members *` (create, delete, patch, transfer, changename) | `rsc/admin/members.py:46-51` |
| `/admin franchise *` (create, delete, rebrand, transfer, logo) | `rsc/admin/franchise.py:51-56` |
| `/transactions *` (all 9 mutators) | `rsc/transactions/transactions.py:412-416` |
| `/accolades *` | `rsc/utils/trophy.py:27-31` |

The codebase already has the right mechanism and barely uses it: `elevated_role_required()`
(`rsc/checks.py:45-88`) re-validates against the RSC API and explicitly **fails closed** on API
error (`:73-75`). It is applied to exactly three commands, all in `rsc/trackers/trackers.py`.
Combined with C-3, the blast radius of a mis-scoped Integrations override is total.

### M-8 — Inconsistent trust level for configuring credentials

`/rsc key` requires `@bot_owner_required()` (`rsc/core.py:423-425`), but `/llm apikey`
(`rsc/llm/llm.py:352-360`) and `/ballchasing key` (`rsc/ballchasing/ballchasing.py:249-253`) accept
`manage_guild`. The docstring on `bot_owner_required` (`rsc/checks.py:20-25`) states the rationale —
*"some settings (API credentials…) are destructive enough that guild managers should not be able to
change them"* — and then the rule was applied to one of three credentials.

Neither key can be read back, so this is substitution/denial rather than disclosure: a Manage-Server
holder can swap in their own OpenAI key to redirect traffic, or blank it to disable the AI. Note
also that all three take the key as a plain slash-command string option, which puts it in the
invoker's client-side Discord command history.

### M-9 — Ungated member enumeration, and an unbounded gateway-query DoS

Six commands in `rsc/utils/utils.py` carry `@app_commands.guild_only` and nothing else:
`/getreactlist` (`:659`), `/getmassid` (`:710`), `/getid` (`:729`), `/userinfo` (`:742`, and **not**
ephemeral), `/serverinfo` (`:849`, not ephemeral), `/getallwithrole` (`:1049`).

`/getallwithrole` is the sharpest — any member enumerates the full membership of e.g.
`@Admin ∩ @General Manager` with raw snowflakes (`:1096-1100`), which is ready-made targeting data
for DM phishing.

`/getmassid` is additionally a resource-exhaustion vector: `GreedyMemberTransformer.transform`
(`rsc/transformers.py:78-105`) splits input on whitespace and, for each token missing from cache,
issues `guild.query_members(lookup, limit=100)` — one gateway round trip per token, unbounded,
invocable by anyone. A few hundred tokens per invocation will get the bot rate-limited off the
gateway.

### M-10 — Admin-set welcome message is evaluated as a Python format string
`rsc/welcome/welcome.py:38-42`

```python
wmsg = await self._get_welcome_msg(member.guild)
if wmsg:
    await wchan.send(
        content=wmsg.format(member=member),
```

`str.format` on a stored, user-authored template permits attribute traversal. A template containing
`{member.guild._state.http.token}` walks the object graph to the **bot token**, and the result is
posted publicly to the welcome channel on the next join. Setting the template requires
`manage_roles` (`:47-51`), so this is privilege *retention* rather than escalation — but it converts
"can edit the welcome text" into "can read the bot token", which is a much larger grant than the
permission implies. `string.Template.safe_substitute` or an explicit `.replace("{member}", ...)`
avoids the whole class.

### M-11 — `aiohttp==3.9.5` is pinned old, and the audit that would flag it is disabled
`requirements.txt:9`, `.pre-commit-config.yaml:31-34`

Every other dependency is current (`certifi==2026.2.25`, `pillow==12.3.0`, `openai==2.28.0`,
`discord-py==2.7.1`), making `aiohttp==3.9.5` (mid-2024) a clear outlier. It is pinned transitively
by `red-discordbot==3.5.24`. Versions below 3.10.11 carry published advisories including HTTP
request smuggling and a multipart-parsing DoS — and this project runs an aiohttp `web.Application`
server (H-0), so the *server-side* advisories are directly in scope, not theoretical.

The `uv-audit` hook is deliberately disabled with honest reasoning (Red's `==` pins make it
unpassable), but the effect is that no dependency vulnerability is ever surfaced, including ones
that could actually be fixed.

**Supply chain, secondary:** `[tool.uv.sources]` (`pyproject.toml:157-162`) pulls two runtime
dependencies from a personal GitHub account with no `rev=` pin, so `uv lock` regeneration resolves
whatever HEAD is. `requirements.txt` does pin commits and carries 1061 `--hash=` entries, so
installs from it are reproducible — the gap is lock regeneration. `replay-parser` is the one that
parses attacker-supplied `.replay` bytes from `/reportmatch`, which is the worst pairing of
"unpinned personal repo" and "untrusted input". Separately, `pyproject.toml:12` lists `pip>=26.1.2`
as a *runtime* dependency, which is unusual and needlessly expands the installed surface.

### L-2 — Assorted lower-severity security items

- **API internals posted publicly.** `rsc/admin/members.py:72, :112, :174, :188, :223` (and ~12
  more) send `ApiExceptionErrorEmbed(exc)` with `ephemeral=False`. `rsc/embeds.py:242-260` renders
  `exc.reason`, every key of `exc.extra`, and `exc.status` into a public embed.
- **Extension-only file validation.** `rsc/ballchasing/validation.py:8-10` is
  `return bool(replay.filename.endswith(".replay"))`. `/reportmatch` is open to any member; there is
  no size ceiling and no magic-byte check before the bytes reach the third-party parser.
- **No content validation on franchise logos.** `rsc/admin/franchise.py:143-196` enforces a 200 KB
  cap but no MIME or image-magic check despite the description saying "(PNG)".
- **Unvalidated tracker URL rendered as a clickable button.** `rsc/trackers/trackers.py:51-71` puts
  a free-form string into `LinkButton(...)` and posts it **non-ephemerally** as an official-looking
  "Tracker Link". `validators` is used correctly for the API URL at `core.py:535` — the finding is
  the inconsistency. No SSRF; the bot never fetches these.
- **`trust_env=True`** on `rsc/combines/api.py:14, :42, :66, :79` and `rsc/devleague/api.py:15, :25`
  honours `HTTP_PROXY`/`HTTPS_PROXY` from the environment; `devleague/api.py:35` inconsistently omits it.
- **Silent denials.** `rsc/checks.py:58-61` and `rsc/numbers/numbers.py:105-106, :161-162` return
  without responding, so the user sees "The application did not respond." A denial becomes
  indistinguishable from a crash, which trains users to ignore both.
- **`/logs tail`** (`rsc/developer/developer.py:41-69`) exposes 1984 bytes of process-wide log to any
  `manage_guild` holder — on a multi-guild deployment that includes other guilds' data. Ephemeral,
  and no credential is ever logged, hence Low.
- **Prompt injection reaches the model** through RSC-API-sourced names (`rsc/llm/agent/prompts.py:85`
  via `service.py:99`) and transaction notes (`rsc/llm/agent/tools/schedule.py:107-115`). Impact is
  genuinely low — all 15 tools are read-only and output passes through `safety.py` — but `/ask`
  replies are public (`llm.py:229`) and `sanitize_response` does not defang markdown links, so an
  injected phishing URL could surface inside an official-looking "RSC AI" embed.

### L-3 — Assorted lower-severity reliability items

- **A registered command is a stub.** `rsc/leagues/leagues.py:64-83` `/leagueinfo` calls
  `utils.not_implemented(interaction)` with its body commented out and `# TODO - Is this useful?`.
  Only two TODO markers exist repo-wide, both here.
- **Empty-embed-field 400s.** `"\n".join(...)` feeding `add_field(value=...)` with a possibly empty
  iterable at `leagues.py:52, 57`, `franchises.py:81, 86, 91`, `combines/combines.py:256-257`,
  `moderator/thread.py:109-110`, `transactions.py:1451, 1546-1548`, `welcome.py:77, 154`. Discord
  rejects `value=""`. `rsc/embeds.py` already has `add_long_field`; a `value or "None"` fallback
  there fixes all of them centrally.
- **`pytz` retained for a string list.** `core.py:409, 411, 556` use `pytz.common_timezones` purely
  to populate an autocomplete; everything else correctly uses `zoneinfo`.
  `zoneinfo.available_timezones()` removes the dependency.
- **Unbounded memory growth.** `CooldownTracker._last` (`rsc/llm/agent/budget.py:88`) is keyed on
  `(guild_id, user_id)` and entries are never expired.
- **`logging.basicConfig()` at import.** `rsc/__init__.py:7` adds a root handler inside a Red host
  process that owns its own logging config — can duplicate log lines.
- **27 cross-module `self.X()` calls are absent from `RSCMixIn`.** All 120 declared abstract methods
  *are* implemented, but `core.py` calls four that are not declared (`close_ballchasing_sessions`
  `:171`, `_populate_free_agent_cache` `:246`, `prepare_ballchasing` `:248`,
  `setup_persistent_activity_check` `:253`). Renaming any of those would pass `ty check` and fail at
  startup.
- **`/combines active` is missing `@active_combines`**, which its three siblings all carry
  (`combines.py:200-206` vs `:69, 106, 146`).
- **Cog metadata is incomplete for Red's Downloader.** The root `info.json` has no `requirements`,
  `min_bot_version`, or `min_python_version` — and the README instructs installation via
  `[p]cog install`, which is exactly the path that relies on `requirements` to pull `rscapi`,
  `pillow`, `openai`, and the rest. Downloader never reads `pyproject.toml`.

### L-1 — No CI; quality gates are local-only and opt-out
No `.github/` directory exists. `.pre-commit-config.yaml` runs ruff, ty, codespell, and uv-lock/sync/
export, but **not pytest** — 18.5k lines of tests never run automatically, and every hook is
bypassable with `git commit --no-verify`. `uv-audit` is deliberately disabled
(`.pre-commit-config.yaml:32-34`) because Red-DiscordBot's `==` pins make it unpassable, so
dependency CVEs are checked only when someone remembers.

**Test coverage gaps that matter.** 44 files / ~6,470 LOC (18% of `rsc/`) are never imported by any
test. Ranked by risk: `rsc/combines/` (1,111 LOC — handles the unauthenticated webhooks and
creates/tears down channels), `rsc/members/views/signup.py` (448 — the onboarding funnel, and the
site of C-0), `rsc/moderator/thread.py` (357 — C-4 lives here), `rsc/admin/match.py` (307),
`rsc/ballchasing/process.py` (292), `rsc/views.py` (265 — the base classes everything inherits), and
`rsc/welcome/welcome.py` (197 — runs on every member join, and the site of M-10).

Note the correlation: **C-0, C-4, M-10, M-15 and H-0 all live in modules with zero test coverage.**
That is not a coincidence, and it is the strongest argument for the CI item.

Where tests do exist they are genuinely behavioural rather than coverage padding — `test_images.py:88-118`
reasons about discord.py's `fp.close` monkey-patch, and `conftest.py:60-77` converts staging
transport errors and 5xx into *skips* rather than failures, which is a mature distinction. The
`pytest-timeout` setup (10s unit, 30s integration via a collection hook) is well judged.

One smell in the test tree itself: `tests/` is excluded from ruff (`pyproject.toml:36`). Running
ruff against it anyway surfaces **20 `F841` unused variables** and **10 `RUF059` unused unpacked
variables** — in a test, an assigned-but-never-used result is frequently an assertion that was never
written.

---

## What is done well

A review that only lists defects gives a false picture. Several things here are above the bar for a
volunteer-run community bot, and they are worth naming because they set the standard the rest of
the codebase should be held to.

**`rsc/utils/dm.py` is the best module in the repository.** It is the one place where the failure
modes were clearly thought through in advance rather than patched in after an incident: jittered
rate limiting (`:110-112`) to avoid Discord's mass-DM flagging, a bounded `deque` for failed
recipients with the reasoning written down (`:16-18`), a `precheck` hook that re-validates each
recipient immediately before send and explicitly fails open (`:30-33`), a `purge()` abort path for
a batch that should not have gone out (`:127`), and an honest docstring caveat that
`failed_members` is process-wide rather than per-batch (`:104-107`). This is what the rest of the
codebase should look like.

**Static analysis discipline is real.** `ruff check` reports 4 findings across 35.5k lines, all
`PLC0415` (import-outside-top-level). `uv run ty check` passes clean. There is exactly one
`type: ignore` in the entire package, and `noqa` suppressions are few and cosmetic (11×`SIM108`,
8×`PERF401`, 6×`S311`). No `DTZ` suppressions at all, which for a bot that schedules matches across
four regional discords is a meaningful signal.

**Secrets handling is correct.** `.env` is gitignored and has never been committed (verified against
full history). No hardcoded credentials in any tracked file. `/rsc settings` reports the API key as
`"Configured"/"Not Configured"` rather than echoing it (`core.py:466`, `:490`), and
`tests/test_llm_safety.py:135` shows token redaction is actually tested with a realistic fake token.

**Test volume is respectable** — 18.5k lines across 57 files against 35.5k lines of source, including
API contract tests, enum parity tests, and LLM safety/budget tests.

**Async correctness came back almost entirely clean**, which is rare at this size and worth stating
explicitly since it was in scope:

- No `time.sleep`, `requests`, `subprocess`, or `pandas` anywhere in `rsc/`.
- Both `asyncio.gather` sites handle exceptions correctly — `core.py:209-219` uses
  `return_exceptions=True` with a per-guild `isinstance(result, BaseException)` sweep and a comment
  explaining why; `llm/agent/loop.py:183` gathers `_dispatch`, which is documented and implemented
  never to raise.
- **No dropped tasks.** All three `create_task` sites keep references — `runner.py:60-62` via a
  module-level set with a done-callback (the correct fire-and-forget idiom, and easy to get wrong),
  `dm.py:123, 125` on `self`.
- `TaskGroup` usage in `core.py:242-285` and `ballchasing/groups.py:21` has full `except*` coverage
  including a trailing `except* Exception`, with a comment explaining the
  `RscException`-escapes-`ApiException` case.
- Session lifecycle is right for the two clients that matter: `abc.py:96-127` (long-lived per-guild
  `ApiClient` plus `close_api_clients`), `core.py:301-306` (invalidate on reconfigure), and
  `ballchasing.py:113-135` — the latter with a comment about deliberately not closing a session out
  from under an in-flight `/reportmatch`. `cog_unload` (`core.py:157-177`) cancels all five loops and
  cleans up the web runner. The OpenAI client (H-19) is the single one that got missed.
- Retry configuration is deliberate and well-reasoned: `const.py:16-27` and `core.py:314-322` set an
  explicit `ExponentialRetry(exceptions=...)` because *"aiohttp_retry's default `exceptions` set is
  EMPTY"*, and POST is excluded from `ALLOW_RETRY_METHODS` so no transaction is ever replayed. There
  is even a `scripts/test_throttling.py` written to empirically probe the API's 429 behaviour.

**Caches are correctly guild-keyed.** `_api_conf`, `_api_clients`, `_league`, `_franchise_cache`,
`_team_cache`, `_tier_cache`, `_check_ins`, `_bc_group_cache`, `_event_state`,
`_elevated_role_cache` — all scoped per guild, and the LLM `ToolCache` key includes `guild_id`
(`rsc/llm/agent/cache.py:67-68`). Exactly one module-level mutable dict is shared across guilds,
`rsc/llm/rulebook.py:164 _INDEXES = {}`, and rulebook content genuinely *is* global, so that is
correct. For a bot running in four separate discords this is the bug I most expected to find and did
not.

**`IntentDMButton` (`rsc/admin/views.py:147-327`) is the model the signup command should copy.** It
defers first with an explicit 3-second rationale, distinguishes "never recorded" from "recorded but
the reply failed" via a `self.declared` flag, re-checks `_api_conf`/`_league` presence before
indexing, treats `next_signup_season` as the authoritative deadline rather than trusting the
button's `custom_id`, and handles the stale-season case. Nearly every High finding in the signup
section is something this file already gets right. The fix for much of C-0/H-13/H-15/H-16 is
"do what `admin/views.py` does."

**No cross-guild or cross-user state leakage on the signup path** — checked specifically because it
is the classic Discord-bot bug. `RSCMixIn` (`abc.py:71-93`) declares only type annotations, not
class-level mutable defaults; every dict is per-instance and keyed by `guild.id`.
`SignupLayoutView`, `AgreementPhase`, and `SelectPhase` are constructed per invocation, and
`PlayerInfoModal` adds its items in `__init__` rather than as class attributes, avoiding
`Modal.__init_subclass__`'s shared children registry. The forms are ephemeral and
`AuthorOnlyLayoutView.interaction_check` correctly blocks other users.

**`elevated_role_required` (`checks.py:45-88`) fails closed on API error** — the right default, and
easy to get wrong. The problem is only that it is applied to three commands.

**`MemberTransformer` / `GreedyMemberTransformer` (`transformers.py`)** resolve strictly against the
invoking guild and raise `TransformerError` rather than returning partial results.

**Path traversal was actively designed out.** `rsc/llm/agent/tools/docs.py:20-33` uses an explicit
allowlist dict with a comment stating why a glob would be a traversal bug, and constrains the
`topic` parameter with a JSON-schema `enum` at `:43`. All 15 LLM agent tools are read-only — the
model cannot reach a create, update, or delete call.

**The comments explain "why", not "what".** `members.py:477-478`, `sync.py:71-72`,
`transactions/roles.py` and `pyproject.toml:32-34` all document reasoning behind non-obvious
choices. That is unusually good practice and makes this codebase far easier to audit than most.

The gap in all of this is enforcement: none of the lint, type, or test discipline is checked
anywhere except a bypassable local hook.
