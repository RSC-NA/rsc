# LLM

**Package:** [rsc/llm/](../../rsc/llm/) · **Mixin(s):** `LLMMixIn`

The "RSC AI". Members can ask questions about the rulebooks, franchises, rosters, players, schedules, standings, stats and transactions. They ask with `/ask` or by mentioning the bot. An OpenAI model answers by calling a fixed set of tools. The tools read live data through the RSC API and search the rulebooks in memory. The model never answers league questions from its own memory. Staff can also have the AI summarize a private ModMail ticket channel.

The feature costs money on every question, so spending limits are built in: a per-user cooldown, per-user and per-server daily question caps, and hard limits on iterations, tool calls and tokens for each question.

## Using it

**Server admins (Manage Server)** set it up once:

1. `/llm apikey` with the league's OpenAI key. Add `/llm organization` if the key belongs to an organization. Ticket summaries need both.
2. `/llm toggle` to turn it on. It is off by default.
3. Optionally, `/llm cooldown` and `/llm dailycap` to tune the limits, and `/llm blacklist add` for channels where the bot must not answer.
4. `/llm settings` shows the current configuration. `/llm usage` shows today's questions and token spend, for the whole server or for one member.

**Anyone** can ask:

- `/ask question:...` posts the answer publicly as an embed. Rate-limit and error messages are only visible to the asker.
- Mentioning the bot in a message (for example `@RSC who leads Elite in goals?`) gets a plain-text reply. A mention inside a reply to another message is ignored. So are mentions in announcement channels, `@everyone` messages, and messages from bots.
- Answers know who is asking. "My team" or "my stats" questions work for rostered players, because the bot looks up the asker in the RSC API.
- Rule answers cite the book and rule number, for example "RSC Rules 5.7.3" or "Behavioral 3.1.1".

**Limits members run into:**

- Cooldown: by default 20 seconds between questions per user. The bot reacts with an hourglass and posts a short notice that deletes itself after 8 seconds.
- Daily caps: by default 15 questions per user and 400 per server, counted per calendar day in the server's timezone. Reaching the user cap gets a bar-chart reaction. Reaching the server cap gets a no-entry reaction.
- Members who hold a league staff position (an "elevated" position in the RSC API) skip the per-user cap but still count toward the server cap and still have the cooldown. Members with Manage Server skip every limit.

**Staff with Manage Server** can summarize a ticket: run `/llm summarize` inside a private ticket channel or thread, or pass `channel:`. Only you see the summary. It has fixed sections: Issue, Key Timeline, Actions Taken, Current Status and Recommended Next Step. Images in the ticket are sent to the model too.

## Commands

**Public**

| Command | Who can run it | What it does |
|---|---|---|
| `/ask question` | Anyone (server only) | Ask the RSC AI a question. Needs the AI to be enabled, `/ask` to be allowed on the server (`LLMPublicAsk`), and the channel to be off the blacklist. |
| Mention the bot | Anyone | Same agent as `/ask`, replying in the channel as plain text split into 2000-character messages. |

**`/llm`** (group default permission: Manage Server, server only)

| Command | Who can run it | What it does |
|---|---|---|
| `/llm settings` | Manage Server | Show enabled state, OpenAI organization, whether a key is set, `/ask` state, cooldown, daily caps and blacklist. |
| `/llm toggle` | Manage Server | Turn the AI on or off. |
| `/llm organization name` | Manage Server | Set the OpenAI organization. |
| `/llm apikey key` | Manage Server | Set the OpenAI API key. |
| `/llm cooldown seconds` | Manage Server | Seconds between questions per user, 0 to 3600. 0 disables the cooldown. |
| `/llm dailycap [per_user] [per_guild]` | Manage Server | Daily question caps. 0 disables a cap. Omitted values stay unchanged. |
| `/llm usage [member]` | Manage Server | Questions and tokens used today, for the server or one member. |
| `/llm summarize [channel] [message_limit]` | Manage Server, and the caller must be able to view the channel | Summarize a private ticket text channel or thread. `message_limit` is 25 to 200 (default 120). |

**`/llm blacklist`** (Manage Server)

| Command | Who can run it | What it does |
|---|---|---|
| `/llm blacklist show` | Manage Server | List channels where the AI will not answer. |
| `/llm blacklist add channel` | Manage Server | Add a text channel to the blacklist. |
| `/llm blacklist rm channel` | Manage Server | Remove a text channel from the blacklist. |

## Configuration

Two Red `Config` custom groups. Everything is per guild. There are no environment variables.

**`LLM`** (identifier: guild id)

| Key | Default | Set by |
|---|---|---|
| `LLMActive` | `False` | `/llm toggle` |
| `OpenAIKey` | `None` | `/llm apikey` |
| `OpenAIOrg` | `None` | `/llm organization` |
| `LLMUserCooldown` | `20` (seconds) | `/llm cooldown` |
| `LLMUserDailyCap` | `15` | `/llm dailycap per_user` |
| `LLMGuildDailyCap` | `400` | `/llm dailycap per_guild` |
| `LLMPublicAsk` | `True` | No command. Only changeable in Config or code. |
| `LLMBlacklist` | `None` (empty list) | `/llm blacklist add` / `rm` |

**`LLMUsage`** (identifiers: guild id, user id; user id `0` is the server-wide total) stores `day` (`YYYY-MM-DD` in the guild timezone), `count` and `tokens`. A record resets the first time it is written on a new day.

**Code constants** in [config.py](../../rsc/llm/config.py). Changing these needs a code change:

| Constant | Value | Meaning |
|---|---|---|
| `OPENAI_AGENT_MODEL`, `OPENAI_SUBAGENT_MODEL`, `OPENAI_SUMMARY_MODEL` | `gpt-5.4-mini` | Models for the main agent, the rules sub-agent and ticket summaries |
| `AGENT_MAX_ITERATIONS` | 4 | Model round trips per question before a forced answer |
| `AGENT_MAX_TOOL_CALLS` | 8 | Server-side cap on tool calls per response |
| `AGENT_MAX_OUTPUT_TOKENS` / `SUBAGENT_MAX_OUTPUT_TOKENS` | 900 / 600 | Output token ceilings |
| `AGENT_MAX_TOTAL_TOKENS` | 60,000 | Token ceiling per question, sub-agent included |
| `TOOL_RESULT_MAX_CHARS` | 6,000 | Tool output is cut on a line boundary past this |
| `TOOL_TIMEOUT` / `AGENT_TOTAL_TIMEOUT` / `OPENAI_REQUEST_TIMEOUT` | 20s / 60s / 45s | Timeouts |
| `RULES_SUBAGENT_MAX_SECTIONS` / `RULES_SUBAGENT_MAX_CONTEXT_CHARS` | 5 / 48,000 | How much rule text the sub-agent sees |
| `API_CACHE_TTL` / `API_CACHE_MAXSIZE` | 300s / 256 | Tool result cache |
| `PROMPT_VERSION` | 2 | Part of the prompt cache key. Bump it when the system prefix changes shape. |

The OpenAI client is the `openai` Python SDK with its default endpoint. The code sets no base URL.

## Background work

- **`on_message` listener** (`llm_reply_to_mention`): answers mentions of the bot when the AI is enabled. It skips bots, `@everyone` messages, announcement channels, replies, and blacklisted channels.
- **Rulebook load at startup**: `setup()` in [core.py](../../rsc/core.py) calls `load_rulebooks()` once, in a worker thread. If that fails, the first question builds the index instead.
- There are no task loops, persistent views or DMs.

## How it works

### Files

- [llm.py](../../rsc/llm/llm.py): `LLMMixIn`. The Discord surface: `/ask`, the mention listener, the `/llm` command group, ticket summarization helpers (transcript and image collection, privacy check) and Config accessors. `answer_with_agent()` is the single entry point for both `/ask` and mentions.
- [config.py](../../rsc/llm/config.py): models, ceilings and timeouts (table above).
- [summarize.py](../../rsc/llm/summarize.py): the ModMail ticket summary. One multimodal Chat Completions call with no tools.
- [rulebook.py](../../rsc/llm/rulebook.py): the in-memory rulebook index and BM25 search.
- [loaders/ruleloader.py](../../rsc/llm/loaders/ruleloader.py): `RuleDocumentLoader`, the Markdown parser for rule files and glossaries.
- [agent/](../../rsc/llm/agent/): the tool-calling agent.
  - [service.py](../../rsc/llm/agent/service.py): glue between the cog and the agent. Spend checks (`check_budget`, `record_usage`, `usage_today`), identity lookup, and `build_agent_context`.
  - [loop.py](../../rsc/llm/agent/loop.py): `run_agent`, the iteration loop, tool dispatch and the forced final answer.
  - [registry.py](../../rsc/llm/agent/registry.py): the `@tool` decorator, the `TOOLS` registry and argument cleanup.
  - [prompts.py](../../rsc/llm/agent/prompts.py): the cached system prefix and the per-question user block.
  - [subagents.py](../../rsc/llm/agent/subagents.py): the rules sub-agent behind `ask_rulebook`.
  - [safety.py](../../rsc/llm/agent/safety.py): `sanitize_response`, applied to every answer.
  - [budget.py](../../rsc/llm/agent/budget.py): token accounting, the in-memory cooldown tracker and the usage log line.
  - [cache.py](../../rsc/llm/agent/cache.py): `ToolCache`, a TTL cache with single-flight locking.
  - [context.py](../../rsc/llm/agent/context.py): `AgentContext` (per-question state) and `UserIdentity`.
  - [format.py](../../rsc/llm/agent/format.py): compact pipe-delimited renderers, `clamp()` and status naming.
  - [tools/](../../rsc/llm/agent/tools/): the tools, registered when the package is imported.

### Question flow

1. `answer_with_agent()` makes sure an OpenAI key is set, then runs `check_budget()`. Members with Manage Server pass at once. Everyone else is checked in this order: cooldown, server cap, then user cap. Elevated members skip the user cap. A refusal raises `BudgetError`, carrying the reason and the retry time.
2. The cooldown starts *before* the model is called, so one user cannot queue several questions behind a slow one. If the agent fails with `AgentError`, the cooldown is cleared.
3. `build_agent_context()` makes sure the rulebooks are loaded, looks up the asker in the RSC API (`players(discord_id=...)`) to get name, team, franchise, tier and status, creates an `AsyncOpenAI` client from the guild's key and organization, and resolves the current season id and number.
4. `run_agent()` runs the loop on the OpenAI **Responses API** with `store=False`, `prompt_cache_key=rsc-agent-v{PROMPT_VERSION}-{guild_id}`, parallel tool calls, and `max_tool_calls=8`:
   - The **system prefix** holds the persona and hard limits, a one-line description of each of the three rulebooks, the table of contents of every book, and the glossary from `RSC Rules.md`. It is kept byte-identical between requests so OpenAI's prompt cache hits.
   - The **user block** holds the current date and time in the guild timezone, the current season, a one-line description of the asker, and the question. These change on every question, so they stay out of the prefix.
   - On each iteration the model either answers or asks for tool calls. Tool calls run concurrently, each with a 20 second timeout. A tool failure (RSC API error, timeout, bad arguments) goes back to the model as an `ERROR: ...` string, not to the user.
   - When the iteration cap (4) or the 60k token ceiling is hit, one more call is made with `tool_choice="none"` and a developer message telling the model to answer from what it already has.
   - The whole run is capped at 60 seconds. A rate-limit error is retried once after 2 seconds. Nothing else is retried.
5. `record_usage()` adds one question and the tokens used to both the user's and the server's `LLMUsage` records.
6. The answer leaves the loop through `sanitize_response()`, then goes to Discord with `AllowedMentions.none()`.

### Tools

Nineteen tools, registered with `@tool(name, description, properties, required, cacheable=...)`. Tools marked "cached" are served from a per-cog `ToolCache` (5 minutes, keyed by guild, tool and arguments, single-flight so two people asking at once do not both fetch).

| File | Tools | Backing calls |
|---|---|---|
| [league.py](../../rsc/llm/agent/tools/league.py) | `list_franchises`, `get_franchise`, `list_teams`, `get_team_roster`, `list_tiers`, `get_season_info` (cached); `find_player`, `list_players` | `franchises`, `fetch_franchise`, `franchise_by_id`, `franchise_standings`, `teams`, `team_id_by_name`, `team_players`, `players`, `player_count`, `tiers`, `current_season`, `_get_dates` |
| [schedule.py](../../rsc/llm/agent/tools/schedule.py) | `get_schedule`, `get_standings`, `get_transactions` (never cached) | `next_match`, `season_matches`, `matches`, `franchise_standings`, `tier_standings`, `transaction_history` |
| [stats.py](../../rsc/llm/agent/tools/stats.py) | `top_players`, `top_teams`, `get_team_stats` (cached); `get_player_stats` | `tier_player_stats`, `tier_team_stats`, `team_stats`, `player_stats` |
| [rules.py](../../rsc/llm/agent/tools/rules.py) | `ask_rulebook`, `get_rule`, `search_rules` | The in-memory rulebook index |
| [docs.py](../../rsc/llm/agent/tools/docs.py) | `get_help_doc` (cached) | An allowlist of Markdown files under `rsc/resources/help/` and `rsc/resources/funny/` |

All league data comes from the cog's own mixin methods, which call the RSC API through `rscapi`. The tools do not call the API directly.

`AgentTool.clean_arguments()` drops placeholder values from optional parameters, such as `discord_id: 0`, `""` or `null`. Models tend to fill every declared property, and a blank like `discord_id=0` would otherwise reach the API as a real filter.

### Rules sub-agent

`ask_rulebook` does not put rule text into the main loop's context. Every later iteration would pay for that text again. Instead:

1. `select_book()` picks a book by summing BM25 scores per book, unless the model named one. No model call is made for this.
2. `_gather_sections()` takes the top hits, collects up to 5 enclosing sections (each depth-2 rule with its children), and caps the text at 48,000 characters. With no lexical hits at all, it uses the whole book, truncated.
3. One Responses call with `gpt-5.4-mini` and 600 output tokens answers from that text and cites rules as "{book} {number}". Its token usage counts toward the same per-question total.

`get_rule` returns one rule by number. Without a book it checks all three and labels each match, since numbers repeat across books. `search_rules` returns short excerpts.

### Rulebooks: files, parsing and regeneration

Rule files live in [rsc/resources/rules/](../../rsc/resources/rules/). Three are indexed:

| Book (`RuleBook`) | File | Citation label |
|---|---|---|
| `competitive` | `RSC Rules.md` | `RSC Rules` |
| `behavioral` | `Behavioral Rules.md` | `Behavioral` |
| `elevated` | `Elevated Rules.md` | `Elevated` |

`Old RSC Rules.md` sits in the same folder and is deliberately not indexed.

**How a file is parsed** (`RuleDocumentLoader.parse_rule_nodes`):

- A line is a rule when it matches `RULE_LINE_RE`: optional `#` heading marks, an optional list bullet, optional `**`, then a number like `5`, `5.7` or `5.7.3` with an optional trailing dot, then the text. The number decides the hierarchy: `5.7.3` is a child of `5.7`, which is a child of `5`.
- Following lines that are not rules attach to the last rule. Lines before the first rule are dropped, and so are lines starting with `|`. That drops Markdown tables, such as the table of contents at the top of `RSC Rules.md`.
- Parsing stops at a heading reading `Disclaimer`, `Release`, `Release:` or `Changelog` (ignoring `#`, `*` and `_`).
- Only rules introduced by a Markdown **heading** line (`## 5.7 Substitutions`) appear in the table of contents in the system prompt. Numbered body lines are still searchable and fetchable, but they are not section titles.
- A heading reading `General Glossary` starts the glossary. Entries look like `"Term", "Alias" - definition`, and the glossary ends at the first rule line. Only the `RSC Rules.md` glossary goes into the system prompt.
- `Behavioral Rules.md` has a section 1 heading that does not start with a digit, so `SYNTHETIC_HEADINGS` in [rulebook.py](../../rsc/llm/rulebook.py) adds "1 Introduction" for it.

**Search** is BM25 over one index that spans every book (k1 = 1.5, b = 0.75). It adds a bonus for a phrase match (+2.0) and for a title match (+0.5), and a penalty for rules that have children (−0.75). A stopword list includes "rsc" and "rule(s)". A query that contains a rule number such as `5.7.3` goes straight to that rule.

**Regenerating from a PDF** (from the top-level [README](../../README.md)):

1. Put the source PDF in `./inputpdf` and run:
   ```sh
   marker_single ./inputpdf --output_dir ./converted/ --output_format markdown --force_ocr
   ```
2. Review the Markdown in `./converted/`, then replace the matching file in `rsc/resources/rules/`, keeping the existing filename. Check OCR mistakes, leftover table-of-contents debris, and the numbered headings.
3. Keep section rules as Markdown headings with the number in the heading text (`## 1.1 ...`, `### 2.3.1 ...`) so they show up in the table of contents. Keep the `General Glossary` heading and the `"Term" - definition` entry format, or the glossary will come out empty.
4. Run `uv run pytest tests/test_llm_rulebook.py`. It checks that all three books parse, that some known rules exist (for example `5.7.1` to `5.7.3`, the substitution rules under `5.6.3`, and `3.1` existing in more than one book), and that the Elevated table of contents lists `3.1 Active Committees`.
5. Reload the cog or restart the bot. The index is built once and kept in memory, and no command rebuilds it.

### Safety

`sanitize_response()` in [safety.py](../../rsc/llm/agent/safety.py) runs on every agent answer and every ticket summary:

- Strips tool calls the model wrote out as text (`to=functions.<name> {...}`) and special tokens.
- Replaces anything shaped like a credential with `[redacted]`: OpenAI `sk-` keys, Discord bot tokens, `Bearer` / `Api-Key` headers, and `token=`/`password:` style pairs.
- Wraps command-like line starts (`!ban`, `.mute`, `?kick` and similar) in backticks so other bots ignore them.
- Breaks `@everyone` and `@here` with a zero-width space.

Every reply is also sent with `AllowedMentions.none()`.

### Ticket summaries

`/llm summarize` checks, in order:

- the target is a text channel or thread, and the caller can view it;
- both the OpenAI organization and key are set;
- the channel is private: `@everyone` cannot view it, and a text channel has at most 40 members;
- the channel has no more than 300 messages of history.

It then builds a transcript of the newest `message_limit` messages (in order, at most 20,000 characters, images marked `[image-N]`). It attaches up to 10 images, 20 MB in total, as base64 data URLs and calls Chat Completions with `gpt-5.4-mini`. The result is sanitized, cut to 2,000 characters and shown only to the caller.

### What gets logged

- `red.rsc.llm.usage` (INFO): one line per question, `llm.usage guild=... user=... surface=mention|slash iters=... calls=... tools=... in=... cached=... out=... reasoning=... model=... elapsed=...`. It is written even when the run fails.
- `red.rsc.llm` (DEBUG): `Original Question: ...` and `Question sent to the agent: ...` for mentions. Declined mentions are logged with their reason.
- `red.rsc.llm.agent` (WARNING/INFO): tool API errors, timeouts and bad arguments; token-ceiling and iteration-cap cutoffs; OpenAI errors and rate-limit retries.
- `red.rsc.llm.agent.safety` (WARNING): leaked tool-call text that was stripped.
- With Red at DEBUG level, the live logs also carry the OpenAI client library's request logging. That includes the full request payload: the user block, tool-call `arguments` and each `function_call_output`. Grep for `Original Question`, `'arguments':` and `red.rsc.llm.usage` when working out why an answer was wrong.

## Gotchas

- `LLMPublicAsk` has no command. If it is ever set to `False`, only a Config edit turns `/ask` back on.
- Ticket summaries need both the OpenAI organization and the key. `/ask` and mentions only need the key.
- `/llm summarize` does not check whether the AI is enabled, and it is not counted against the cooldown, the caps or `LLMUsage`.
- The ModMail check in `/llm summarize` is commented out. Any private channel or thread that passes the privacy check can be summarized.
- `/llm blacklist rm` on a channel that is not on the list fails with an error, because the code calls `list.remove()`. `add` does not check for duplicates.
- Mentioning the bot inside a reply to another message is ignored on purpose. Users have to start a new message.
- The cooldown lives only in memory (one `CooldownTracker` per cog), so it resets on reload. The daily counts are in Config and survive a reload.
- Daily caps count questions, not tokens. Tokens are recorded but never enforced, apart from the 60k ceiling per question.
- `get_team_roster` is marked cacheable, so roster answers can be up to 5 minutes old. The registry comment says data that moves intraday should not be cached.
- `get_player_stats` and `get_transactions` with a player filter only work for players who are still in the Discord server, because the underlying calls are keyed by Discord member.
- The cached system prefix includes the rulebook table of contents. Editing a rule file changes the prefix, which costs prompt-cache misses until the cache warms again. It does not break anything.
