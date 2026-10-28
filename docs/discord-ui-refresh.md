# Discord UI Refresh — Research, Findings and Phased Plan

**Started:** 2026-10-28, against `rsc` @ `d79c61f` (master).
**Published summary with mockups:** https://claude.ai/artifact/WYTJx7XV1zyXCtg3WQVeJe (private to the owner).
**Library:** discord.py **2.7.1**, pinned by `red-discordbot==3.5.24`. 2.7.1 (2026-03-03) is still the latest release.

This file is the working record for the refresh. Update the status table as phases land.

---

## Phase status

| Phase | Scope | Status |
|---|---|---|
| 1 | Fix the bugs listed under [Bugs](#bugs) | **Done** (2026-10-28, branch `discord-ui-phase-1`) |
| 2 | Shared building blocks: `rsc/layouts.py` (`Card`, `ConfirmLayoutView`), `LayoutView` support in `DMTask` | Open |
| 3 | Migrate public announcements: transactions and trades, combine and Dev League lobbies, help and guide posts | Open |
| 4 | Upgrade the modals: Report Match radios, Label descriptions on admin modals, `.replay` filter once discord.py ships it | Open |
| 5 | Optional: errors and logs stay as embeds unless `ResultView` gets a one-line constructor | Open |

---

## 1. What Discord shipped (bot-facing, roughly Oct 2025 – Oct 2026)

Components V2 launched in April 2025. Everything since builds on it, so it is listed for context.

| Date | Feature | Notes | discord.py 2.7.1 |
|---|---|---|---|
| 2025-04 | **Components V2** | Message flag `IS_COMPONENTS_V2` (`1<<15`). Types: Section (9), TextDisplay (10), Thumbnail (11), MediaGallery (12), File (13), Separator (14), Container (17). 40 components per message, counting nested ones. 4,000 characters of TextDisplay text (discord.py enforces this; `LayoutView` docstring). | Supported since 2.6 (`ui.LayoutView`, `Container`, `Section`, `TextDisplay`, `Thumbnail`, `MediaGallery`, `File`, `Separator`, `ActionRow`) |
| 2025-08-25 | **Label (18) in modals** | Wraps one input. Label text max 45, description max 100. String selects allowed in modals. ActionRow + `TextInput.label` in modals are deprecated. | Supported (`ui.Label`) |
| 2025-09-10 | **User/Role/Mentionable/Channel selects in modals; TextDisplay in modals** | Selects go inside a Label. | Supported. `TextDisplay`'s type var is bound to `LayoutView`, so type checkers may complain in a Modal (open PR #10510). |
| 2025-10-15 | **File Upload (19) in modals** | Inside a Label. 0–10 files. Size limit follows the channel upload limit. | Supported (`ui.FileUpload`, 2.7). We use it in `ReportMatchModal`. |
| 2026-02-12 | **Radio Group (21), Checkbox Group (22), Checkbox (23)** | All inside a Label. Radio: 2–10 options. Checkbox can't be required; use a one-option CheckboxGroup for a mandatory yes/no. | Supported (`ui.RadioGroup`, `ui.CheckboxGroup`, `ui.Checkbox`, `RadioGroupOption`, `CheckboxGroupOption`) |
| 2026-02-23 | **`PIN_MESSAGES` permission** enforced | Pinning moved out of Manage Messages. | We never pin. No impact (checked: no `.pin(`/`.unpin(` in `rsc/`). |
| 2026-03-03 | Context-menu limit 5 → 15 per type | | discord.py master only |
| 2026-08-05 | **Upload file-type filter** (`file_types` on File Upload and attachment options) | Max 10 entries: `image`, `video`, `audio` or `.ext`. Extension match only. | **Not supported** (open PR #10494) |
| 2026-09-03 | Upload limit 10 MiB → 20 MiB for bots, webhooks, interaction responses | | Server-side |
| 2026-09-11 | Multiline string options, fuzzy autocomplete | Client-side | Automatic |
| 2026-10-05 | **Component Embeds** | A *website* defines its own link preview as a V2 container (`<script id="discord:component-embed">`). 3,000-byte JSON, link buttons only. Candidate for devleague.rscna.com match/combine pages. | Website feature (open PR #10528) |
| — | Timestamp styles `s` / `S` | Short date + short/medium time. | `format_dt` supports them |

Other context: per-guild bot avatar/banner/bio (2025-09), attachment description/spoiler editing (2026-06, not in 2.7.1), channel obfuscation (2026-08, not in 2.7.1).

### "Animated" features

Discord has no animated-embed feature. A bot can show animation in three ways:

- **Animated GIF/WebP** in a MediaGallery or Section Thumbnail. Discord sets `IS_ANIMATED` on them. Gallery videos show a play button and don't autoplay. Thumbnails don't support video.
- **Animated emoji** on buttons and select options. This isn't new.
- **Gradient and holographic role colours** (2025-07). Holographic roles shimmer. A bot can set them with `Role.edit(secondary_colour=…, tertiary_colour=…)` if the guild has `ENHANCED_ROLE_COLORS`. Tier roles are a candidate.

Read-only cosmetics (no bot control): server tags (`Member.primary_guild`), nameplates and avatar decorations (`collectibles`), display-name styles.

### Rules to design around

- A V2 message has **no `content` and no `embeds`**, and an edit can't turn it back into an embed message. In discord.py, `View` and `LayoutView` can't be mixed, and a `LayoutView` message can't take `content=` or `embed=`.
- **No inline fields.** The three-column field grid is gone. Use Sections, label-and-value lines or stacked TextDisplays.
- 40 components and 4,000 characters of text per message. Large trades still need an overflow plan (link to the web UI).
- Each modal holds at most 5 top-level items. Every input must sit in a Label.
- Webhooks need `?with_components=true` (we don't send components via webhooks today).

### Mentions: embeds vs. TextDisplay (verified 2026-10-28)

- **Classic embeds do not ping.** Discord's message docs say `allowed_mentions` applies to "the message content" and "the content of components attached to that message". Embeds aren't on that list, and community reports agree that embed mentions render but don't notify. This is why `announce_transaction` sends the pings in `content` and then edits the content away.
- **V2 TextDisplay mentions do ping.** The component reference, Text Display section: *"When sent in a message, pingable mentions (@user, @role, etc) present in this component will ping and send notifications based on the value of the allowed mention object set in message.allowed_mentions."*
- Red's bot-wide default is `AllowedMentions(everyone=False, roles=False)`. Per-message `AllowedMentions(users=True)` merges on top of it, so `@everyone` and roles stay blocked.
- Before moving transactions to V2, send one test post in a staging guild.

Sources:
- https://docs.discord.com/developers/components/reference
- https://docs.discord.com/developers/resources/message
- https://docs.discord.com/developers/change-log
- https://discordpy.readthedocs.io/en/latest/whats_new.html
- https://discordjs.guide/popular-topics/components-v2

---

## 2. Where RSC stands (inventory at `d79c61f`)

- About **1,050** references to the embed helpers in `rsc/embeds.py`: `ErrorEmbed` 350, `BlueEmbed` 130, `ApiExceptionErrorEmbed` 128, `YellowEmbed` 124, `SuccessEmbed` 107, others. There are also 37 raw `discord.Embed(…)` calls.
- **Components V2 in use:** `/signup` and `/permfa` (`rsc/members/views/signup.py`), intent declaration (`rsc/members/views/intent.py`), and the shared `ResultView` / `AuthorOnlyLayoutView` (`rsc/views.py`).
- **Modals:** 13. Two use `Label` (`PlayerInfoModal`, `ReportMatchModal`), one uses `FileUpload`, and none use radios or checkboxes.
- **Persistent buttons:** 3 `DynamicItem`s, all in DMs (`IntentDMButton`, `ActivityCheckDMButton`, `PermFAPollButton` in `rsc/admin/views.py`).

Things that make migration harder:

- `announce_transaction` (`rsc/transactions/transactions.py`) uses the send-content-then-edit-away ping trick. V2 has no content, so pings move into a TextDisplay.
- `DMTask.view` in `rsc/utils/dm.py` is typed `discord.ui.View`, so it can't take a `LayoutView`.
- Timeouts look different depending on the base class: `AuthorOnlyView` shows an embed, while `AuthorOnlyLayoutView` shows a `ResultView`.

---

## Bugs

Each bug was checked against the installed discord.py 2.7.1 source. Line numbers are as of `d79c61f`.

| ID | Severity | Bug | Status |
|---|---|---|---|
| UI-1 | High | Closing the sign-up modal strands the user | Fixed |
| UI-2 | Medium | Player-card buttons stop working after 3 minutes | Fixed |
| UI-3 | Low | Two error messages for one bad score in Report Match | Fixed |
| UI-4 | Low (likely) | Button clicks never acknowledged in 11 handlers | Fixed |
| UI-5 | Minor | Modal waits that never end, plus small issues | Fixed |
| UI-6 | Medium | Intent view timeout replaced by "Something went wrong… submit a modmail" (found during the fix) | Fixed |
| UI-7 | Low | Cancelling a franchise rebrand says "You have cancelled deleting this franchise" (found during the fix) | Fixed |

### UI-1 — Closing the sign-up modal strands the user

`rsc/members/views/signup.py:484`, `rsc/members/members.py:548`.

- `PlayerInfoModal` has no timeout. `discord.ui.Modal` defaults to `timeout=None`, and Discord sends no event when a user closes a modal, so `await info_modal.wait()` never returns. The branch commented "User dismissed the modal" can't run on a dismissal.
- The referrer select is already disabled, so the user can't reopen the modal.
- Ten minutes after the last click, the view times out and shows "Time Out". The command then overwrites that with "Signup failed for an unknown reason" because the state is still `TRACKERS`.
- If the whole flow took more than 15 minutes, that edit fails because the interaction token has expired.

**Planned fix:** add a button to the last container that opens the modal again. Give the modal a timeout. When the view times out, don't overwrite the timeout message.

### UI-2 — Player-card buttons stop working after 3 minutes

`rsc/members/views/player_info.py:19`. `PlayerInfoView` is posted publicly with the default 180-second `View` timeout and has no `on_timeout`. After 3 minutes "Team Roster" and "Franchise Info" stay visible but fail with "This interaction failed".

**Planned fix:** make both buttons persistent `DynamicItem`s with the needed IDs in the `custom_id`, registered like the DM buttons.

### UI-3 — Two error messages for one bad score

`rsc/ballchasing/modals.py:64-70` → `rsc/ballchasing/ballchasing.py:436`. When `on_submit` rejects a score, it replies and returns. discord.py's `Modal._scheduled_task` still calls `stop()` after a clean return, so the caller continues with `replays == []` and sends a second, misleading "No replays provided."

**Planned fix:** set an error flag in the modal and return early in the caller. Phase 4's radio redesign removes the path entirely.

### UI-4 — Button clicks never acknowledged

These handlers edit the original message via `self.interaction.edit_original_response(...)`, or only call `stop()`, and never respond to the click interaction itself:

- `rsc/freeagents/views.py:33, 44, 84, 95`
- `rsc/admin/views.py:786, 890, 930, 935, 977, 982, 1030`
- `rsc/utils/views/bulk_role.py:49`

Discord requires every interaction to be acknowledged within 3 seconds, and clients usually show "This interaction failed" when it isn't. Not seen in a live guild, hence "likely".

**Planned fix:** respond to the click with `interaction.response.edit_message(...)` or `interaction.response.defer()`.

### UI-5 — Modal waits that never end, plus small issues

- All 13 `modal.wait()` call sites use modals with `timeout=None`. Each dismissed modal leaves a command coroutine waiting forever. This is a slow leak with no visible effect.
- "Sync Canelled" typo in `rsc/admin/views.py:790`.
- `TradeAnnouncementView` (`rsc/transactions/views.py:25`) is never used, and it ignores its `timeout` argument.
- `if not trade_modal.trade` (`rsc/transactions/transactions.py:1280`) tests the `TextInput` object, not its value, so the check always passes. It's harmless because the field is required.

### Phase 1 changes (verified: 1542 tests pass, ruff and format clean, ty at the baseline 9 warnings)

- UI-1: `signup.py` adds an "Enter name & trackers" button that reopens the modal. The modal times out with the view, and only the first submission counts. In `members.py`, `/signup`, `/permfa` and the intent flow return early when the view timed out (UI-6).
- UI-2: `player_info.py` adds a `PlayerInfoButton` `DynamicItem` (`player_info:{roster|franchise}:{name}`), registered and removed in `core.py` alongside the DM buttons. A name too long for a 100-character custom_id drops that button.
- UI-3: `ReportMatchModal.valid`; the caller returns when it is False.
- UI-4: `defer` added to 12 confirm/decline handlers (admin franchise and sync views, free agent check-in/out, bulk role).
- UI-5: shared `const.MODAL_TIMEOUT = 600` on all 13 modals, each caller returns on timeout (otherwise e.g. `/admin dates` would save an empty value). `BulkRetireModal` and `FranchiseRebrandModal` gained a `timeout` parameter. Removed the dead `TradeInfo`/`TradeAnnouncementView`. Fixed the typo and the `.trade.value` checks.
- Typing: no `cast()` in the new code. `PlayerInfoKind` is a `StrEnum`, the cog is narrowed with `isinstance(..., Red)` / `isinstance(..., RSCMixIn)`, `_PlayerInfoButton` is `Button["SignupLayoutView"]`, and `PlayerInfoModal` exposes `name_input`/`links_input`. Removed the unused `MixInMetaClass(RSCMixIn, ABCMeta)` from `rsc/abc.py`: as an `RSCMixIn` subclass that is itself a metaclass, it made `isinstance(x, RSCMixIn)` raise `TypeError` for any non-cog object.
- Tests: `tests/test_discord_ui_fixes.py` (new), additions to `tests/test_signup_view.py` and `tests/test_members.py`, and `tests/test_startup.py` updated for the new dynamic item.

**Not a bug (checked):** `AllowedMentions(users=True)` doesn't let `@everyone` through, because Red's bot-wide default is merged underneath it.

---

## 3. Redesign specs (Phases 3–4)

Each spec uses only what discord.py 2.7.1 supports. Mockups are in the published artifact.

### 01 — Transaction card (`build_transaction_embed`, `rsc/transactions/transactions.py`)

- `Container(accent_colour=tier colour)` contains:
  - a `MediaGallery` holding the transaction banner (`attachment://Signed.png` etc.) at the top;
  - a `Section` with the `## headline` and a detail line, and the franchise logo as a `Thumbnail` accessory (only when a logo exists);
  - a `Separator`;
  - a TextDisplay with player and GM mentions (these ping, see above);
  - an `ActionRow` with persistent "Player card" and "Team roster" `DynamicItem` buttons;
  - a `-#` subtext footer with the Discord ID and timestamp.
- This removes the send-then-edit ping step.
- Trades: one Section per franchise. When text would pass 4,000 characters, add a "Full trade" link button to the web UI.

Sketch:

```python
class TransactionCard(discord.ui.LayoutView):
    def __init__(
        self, *, banner: discord.File, headline: str, detail: str, logo: str | None, people: str, footer: str, colour: discord.Colour
    ):
        super().__init__(timeout=None)
        head = [TextDisplay(f"## {headline}"), TextDisplay(detail)]
        top = [Section(*head, accessory=Thumbnail(logo))] if logo else head
        self.add_item(
            Container(
                MediaGallery(discord.MediaGalleryItem(banner)),
                *top,
                Separator(),
                TextDisplay(people),
                ActionRow(PlayerCardButton(...), RosterButton(...)),
                TextDisplay(f"-# {footer}"),
                accent_colour=colour,
            )
        )


# await tchan.send(view=card, files=files, allowed_mentions=discord.AllowedMentions(users=True))
```

### 02 — Combine / Dev League lobby ready (`rsc/combines/runner.py:302`, `rsc/devleague/runner.py:314`)

- A Section with the title and `Lobby **name** · Password **pass**`, with the match page as a link-button accessory.
- Home ("creates lobby") and away ("uploads replays") team blocks with mentions. They stack vertically, since V2 has no columns.
- Voice-channel link buttons (`jump_url`).
- Subtext pointing to `/combines lobbyinfo`.
- Optional animated "LIVE" WebP, edited to "Finished" on teardown.

### 03 — Combines guide (`send_combines_how_to_play`, `rsc/combines/manager.py:363`)

- Replace the five messages with one Container: a header, a 4-image `MediaGallery` (login, check-in, announcement, report), five numbered steps, and buttons for "Open Dev League" and "Where are my replays?" (an ephemeral reply with the `Demos` path).
- The text is about 1,400 characters.

### 04 — Report Match modal (`rsc/ballchasing/modals.py`)

- A TextDisplay naming the matchup, then two `Label(RadioGroup)` score pickers with options generated from the match format (0–4 for best of 7, 0–2 for best of 3), then `Label(FileUpload)`. That's exactly 4 top-level items.
- Add `file_types=[".replay"]` once discord.py supports it. Until then, keep the description hint.
- Admin modals: add Label descriptions. A `Checkbox` could replace boolean options such as `announce`.

### 05 — Player card (`/playerinfo`, `rsc/members/members.py:817`)

- A Section with name, tier, team and status, and the avatar or franchise logo as the Thumbnail.
- Label-and-value lines for MMR, contract and trackers.
- Persistent Roster, Franchise and Trackers buttons.
- One builder can serve `/team` and `/franchise` too.


---

## 4. Action item: website match link on the report result (requested 2026-10-28)

`build_match_result_embed` (`rsc/ballchasing/ballchasing.py:862`) already returns a link-only `View` with a "Ballchasing Group" button. Adding a second link button for the frontend match page is straightforward: link buttons need no handler, and they work in both legacy views and V2 `ActionRow`s.

**URL pattern (confirmed 2026-10-28 from `~/dev/web-rsc-website`, read-only):**

```
https://www.rscna.com/matches/{match_id}/?league={league_id}&season={season_id}&source=matches
```

- Route `matches/<int:match_id>/` → `stats.views.public_web.match_detail` (`website/stats/web_urls.py:27`). The match is loaded by `match_id` alone, so the query parameters never change which match is shown.
- `league` is the league **id**; the bot has it as `self._league[guild.id]`. `season` is a season **id**, not a number (`core/context_processors.py` `league_season_selector`). Both are optional: they fall back to league 1 and the current season, and they only drive the page header/selector context.
- `source=matches` only builds the "Back to Matches" link (`_build_public_match_back_link`). `source=team-detail&team_id=…` builds "Back to Team Details" instead.
- The view is `@login_required`, so viewers who aren't signed in hit the website login first.
- The bot's `Match` model has `id` and `season_number` but no season id. Either look up the season id (e.g. `current_season(guild)` when the match is in the current season) or omit `season`. Omitting it is safe; an old-season match would then show with the current season selected in the header.
- The site base URL isn't configured anywhere in the bot. Add a constant (e.g. `RSC_WEBSITE_URL = "https://www.rscna.com"`) or a per-guild setting if staging bots should link to a staging site.

**Decisions (2026-10-28):**

- **Ships with Phase 3**, as part of the V2 match-result card (artifact mockup 06), not as a standalone change.
- **Website base URL:** derive it from the guild's configured API URL by dropping the `/api/…` suffix (`https://www.rscna.com/api/v1` → `https://www.rscna.com`). The same Django project serves `api/{version}/` and the web pages (`rsc_website/urls.py`), so staging bots get staging links automatically. No new setting.
- **Season id:** a per-guild season cache, built in `_setup_guild` alongside tiers/franchises/teams with one `seasons_list(league=…)` call, mapping number ↔ id both ways. On a miss (a season created while the bot is running), refetch once before giving up and omitting `season=`.

**Where it goes:** `build_match_result_embed` (`rsc/ballchasing/ballchasing.py:862`) already returns a link-only `View` with "Ballchasing Group". A "Match page" link button can be added there today without any V2 migration, and the V2 redesign (artifact mockup 06) keeps both buttons.

---

## 5. Migration compatibility and caveats (investigated 2026-10-28)

### Hard rules (from discord.py 2.7.1 source and Discord docs)

1. **A V2 message can never go back to an embed.** Any code that later edits a V2 message with `embed=`/`content=` gets a 400. Every "send now, edit later" pair must move to V2 in the same change.
2. **Legacy → V2 edits are allowed but must clear everything.** discord.py: pass `content=None, embed=None, attachments=None` explicitly if the old message had any. Clearing attachments also removes `attachment://` images, so re-upload them and reference them from a component.
3. Files on a V2 message only display when a component references them (`MediaGallery`, `Thumbnail`, `File`).
4. 4,000 characters of text across the whole message, versus 6,000 for an embed. 40 components, counting nested ones.
5. No author line, no footer, no inline fields. The small author icon on transaction embeds (FA tier icon, franchise logo) becomes the single Section thumbnail.

### Code that would break or needs to move together

| Where | Why |
|---|---|
| `transactions.py:221, 1537, 2270` | `tmsg.edit(content=None, embed=embed)` after sending (ping trick). Replace with a single V2 send with mentions in a TextDisplay. |
| `transactions.py` `attachment://` (6 refs) | Banner and author icons. They must become MediaGallery/Thumbnail references. |
| `admin/permfa_poll.py:590` | Preview click rebuilds from `message.embeds[0]`. On a V2 message it would silently fall back to a blank embed. |
| `admin/permfa_poll.py:788` | Poll close edits already sent DMs with `embed=`. DMs sent before a migration are legacy and DMs after are V2, so the close path must handle both (or migrate only when no poll is open). |
| `admin/inactivity.py:75, 176` | `InactiveCheckView` is re-attached to a long-lived posted message by `add_view(message_id=…)`. Keep its custom_ids, and clear embed/content when editing that old legacy message. |
| `DynamicItem` templates (intent, activity, PermFA, player info) | Already sent buttons match by regex. Changing a template string kills every old button. Keep templates stable. |
| `utils/dm.py` `DMTask.view: discord.ui.View` | Can't carry a `LayoutView`. Also the `embed` field must be None for V2 DMs. |
| `AuthorOnlyView.on_timeout`, `LeagueSelectView` | Edit with `embed=`, so they must never sit on a V2 message. Use `AuthorOnlyLayoutView`/`ResultView` for V2 flows. |
| `admin/sync.py:1102, 1309` | Progress image via `attachment://` in a loading embed. It stays legacy unless rewritten. |
| Tests | `test_transactions.py` (~68 embed assertions), `test_trade_announce.py` (~52), `test_permfa_poll.py` (~32), `test_events.py` (~28), `test_inactive_check_dm.py` (~14). These rewrite when their surface migrates. Combines/devleague runner and ballchasing tests don't assert on embed shape. |

### Safe or no impact

- The sign-up and intent flows are already V2 end to end. They only edit with `view=ResultView`/`view=self`, so nothing passes `embed=` to them.
- The LLM summarizer (`llm.py` `_build_summary_transcript`) reads `clean_content` and attachments only. It already skips embeds, so V2 cards aren't a regression; it could read `Message.components` later.
- Link-only `discord.ui.View()`s (ballchasing, combines, devleague, trackers, franchise logo) are not dispatched, so their timeouts don't matter.
- No webhooks, no `embed_requested`, and one Red menu use.
- Red's bot-wide `AllowedMentions(everyone=False, roles=False)` still applies to V2 mentions.

### To verify in a staging guild before Phase 3

- TextDisplay mentions notify (documented, not yet observed).
- What a push notification shows for a V2 message (there's no content field to preview).
- How older mobile clients render V2 messages.
- Whether a legacy message can be edited into a V2 view (discord.py documents it, but it hasn't been tried here).
