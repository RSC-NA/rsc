# Command reference

Every slash command the bot registers, with its options and who can run it. For how and when to use them, see the [module pages](modules/README.md) and the [staff guide](staff-guide.md).

This page is generated from the code by `uv run python -m rsc.command_reference`. Do not edit it by hand. Change the command in code and run the generator again.

Server admins can change who sees a command under Server Settings > Integrations, so "Who can run it" is the default the bot ships with.

## Index

| Command | Description | Commands |
|---|---|---|
| [/8ball](#8ball) | Ask the magic 8 ball a question | 1 |
| [/accolades](#accolades) | Manage player accolades and season rewards | 5 |
| [/accounts](#accounts) | Display rocket league accounts associated with a player | 1 |
| [/addrole](#addrole) | Add a role to the specified user | 1 |
| [/admin](#admin) | Admin Only Commands | 69 |
| [/ask](#ask) | Ask a question about RSC rules, players, teams or schedules | 1 |
| [/assign](#assign) | Assign the current modmail to a specific group | 1 |
| [/ballchasing](#ballchasing) | Ballchasing commands and configuration | 8 |
| [/bulkaddrole](#bulkaddrole) | Add a role a list of user(s) or another role | 1 |
| [/bulkremoverole](#bulkremoverole) | Remove a role a list of user(s) | 1 |
| [/captains](#captains) | Get information on team captains | 3 |
| [/clearallavailability](#clearallavailability) | Clear free agent availability for all tiers | 1 |
| [/clearavailability](#clearavailability) | Clear free agent availability for a specified tier | 1 |
| [/combinemanager](#combinemanager) | Manage combines | 7 |
| [/combines](#combines) | Play in RSC Combines | 4 |
| [/dates](#dates) | Display important RSC dates | 1 |
| [/devleague](#devleague) | RSC Dev league commands | 5 |
| [/devleaguemanager](#devleaguemanager) | Manage dev league | 6 |
| [/devtest](#devtest) | Test command for development purposes | 1 |
| [/drafteligible](#drafteligible) | Display draft eligible players | 1 |
| [/franchises](#franchises) | Get a list of all RSC franchises | 1 |
| [/freeagent](#freeagent) | List of free agent commands for match check in | 3 |
| [/freeagents](#freeagents) | List free agents in a specified tier | 1 |
| [/getallwithrole](#getallwithrole) | Get all users with the specified role(s). (Max 4 roles) | 1 |
| [/getid](#getid) | Lookup discord member account identifiers | 1 |
| [/getmassid](#getmassid) | Mass lookup version of /getid. | 1 |
| [/getreactlist](#getreactlist) | Get a list of users who reacted to a message | 1 |
| [/help](#help) | Display a help for RSC Bot or a specific command. | 1 |
| [/intent](#intent) | Declare or check status of player intent to play | 3 |
| [/leagueinfo](#leagueinfo) | Show league and current season information | 1 |
| [/leagues](#leagues) | Show all RSC leagues | 1 |
| [/llm](#llm) | Configure the RSC LLM | 11 |
| [/logs](#logs) | Display information from bot log files | 2 |
| [/match](#match) | Get information about your upcoming match | 1 |
| [/mod](#mod) | Moderator commands and configuration | 8 |
| [/numbers](#numbers) | Configuration and commands for Numbers Committee | 4 |
| [/permfa](#permfa) | Sign up as a permanent free agent | 1 |
| [/playerinfo](#playerinfo) | Display league information about a player | 1 |
| [/playerstats](#playerstats) | Display RSC stats for a player | 1 |
| [/playoffs](#playoffs) | Display the playoff hunt for a tier | 1 |
| [/removerole](#removerole) | Remove a role to the specified user | 1 |
| [/reportmatch](#reportmatch) | Report the results of your RSC match | 1 |
| [/resolve](#resolve) | Send resolved message to a modmail thread | 1 |
| [/roll](#roll) | Roll a random number | 1 |
| [/roster](#roster) | Get roster for a team | 1 |
| [/rps](#rps) | Rock, Paper, Scissors | 1 |
| [/rsc](#rsc) | RSC API Configuration | 18 |
| [/schedule](#schedule) | Display your team or another teams entire schedule | 1 |
| [/season](#season) | Display current RSC season for league | 1 |
| [/serverinfo](#serverinfo) | Display information about the discord server | 1 |
| [/setchannelperm](#setchannelperm) | Modify channel permissions for a role or member | 1 |
| [/signup](#signup) | Sign up for the next RSC season | 1 |
| [/signupstatus](#signupstatus) | Check your status for the next RSC season | 1 |
| [/staff](#staff) | Display RSC Committees and Staff | 1 |
| [/standings](#standings) | Display standings across the league | 2 |
| [/teams](#teams) | Get a list of teams in RSC | 2 |
| [/teamstats](#teamstats) | Display RSC stats for an RSC team | 1 |
| [/thread](#thread) | View and configure mod thread settings | 6 |
| [/tiers](#tiers) | Get a list of all league tiers | 1 |
| [/trackers](#trackers) | RSC Player Tracker Links | 10 |
| [/transactions](#transactions) | Transaction commands and configuration | 30 |
| [/unassign](#unassign) | Move thread back to the primary ModMail category | 1 |
| [/userinfo](#userinfo) | Display discord user information for a user | 1 |
| [/waivers](#waivers) | Display players currently on waivers | 1 |
| [/welcome](#welcome) | Welcome settings for new members | 5 |
| [/whatami](#whatami) | What am I? | 1 |

## /8ball

Ask the magic 8 ball a question

**Who can run it:** Anyone

| Option | Type | Required | Description |
|---|---|---|---|
| `question` | Text | Yes |  |

## /accolades

Manage player accolades and season rewards

### /accolades addcombinecup

Add a combine cup trophy

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `player` | Member | Yes |  |

### /accolades adddevleague

Add a dev league championship trophy

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `player` | Member | Yes |  |

### /accolades addstar

Add a star for MVP/All-Star season

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `player` | Member | Yes |  |

### /accolades addtrophy

Add a trophy for a championship win

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `player` | Member | Yes |  |

### /accolades masstrophy

Add multiple trophies at once by discord IDs

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `trophy` | Text | Yes | One of: Championship, Star, Dev League, Combine Cup |

## /accounts

Display rocket league accounts associated with a player

**Who can run it:** Anyone

| Option | Type | Required | Description |
|---|---|---|---|
| `player` | Member | Yes | RSC Discord Member |

## /addrole

Add a role to the specified user

**Who can run it:** Manage Roles

| Option | Type | Required | Description |
|---|---|---|---|
| `role` | Role | Yes | Discord role to add |
| `member` | Member | Yes | Player discord name |

## /admin

Admin Only Commands

### /admin agm add

Add an Assistant GM to a franchise

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `franchise` | Text | Yes | Franchise name. Suggestions as you type |
| `agm` | Member | Yes | Player to promote to AGM |

### /admin agm message

Configure the AGM promotion message

**Who can run it:** Manage Server

### /admin agm remove

Remove an Assistant GM from a franchise

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `franchise` | Text | Yes | Franchise name. Suggestions as you type |
| `agm` | Member | Yes | Player to remove from AGM |

### /admin audit search

Search server audit log for an action

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `action` | Whole number | No | Suggestions as you type |
| `before` | Text | No |  |
| `after` | Text | No |  |
| `user` | Member | No |  |
| `limit` | Whole number | No | Default: 20 |

### /admin bulkretire

Bulk retire players by Discord ID

**Who can run it:** Manage Server

### /admin dates

Configure the dates command output

**Who can run it:** Manage Server

### /admin directmessage

Send a direct message to a user

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `member` | Member | Yes | Discord member to DM |
| `message` | Text | Yes | Message content to send |
| `send_at` | Text | No | Schedule the DM for a future date/time (ISO 8601, e.g. 2025-04-20T18:00) |

### /admin dmcancel

Abort all pending bot DMs

**Who can run it:** Manage Server

### /admin dmstatus

Check the status of the bot DM queue

**Who can run it:** Manage Server

### /admin franchise addteam

Add a new team to a franchise

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `franchise` | Text | Yes | Franchise name. Suggestions as you type |
| `tier` | Text | Yes | Team Tier. Suggestions as you type |
| `name` | Text | Yes | Team Name |

### /admin franchise create

Create a new franchise in the league

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `name` | Text | Yes | Franchise name |
| `prefix` | Text | Yes | Franchise prefix (Ex: "TG") |
| `gm` | Member | Yes | General Manager |

### /admin franchise delete

Delete a franchise

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `franchise` | Text | Yes | Franchise name. Suggestions as you type |

### /admin franchise delteam

Remove a team from a franchise

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `franchise` | Text | Yes | Franchise name. Suggestions as you type |
| `tier` | Text | Yes | Team Tier. Suggestions as you type |
| `team` | Text | Yes | Team to delete. Suggestions as you type |

### /admin franchise logo

Upload a logo for the franchise

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `franchise` | Text | Yes | Franchise name. Suggestions as you type |
| `logo` | File | Yes | Franchise logo file (PNG) |

### /admin franchise rebrand

Rebrand a franchise

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `franchise` | Text | Yes | Franchise to rebrand. Suggestions as you type |
| `override` | True/False | No | Admin only override. Default: False |

### /admin franchise transfer

Transfer ownership of a franchise

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `franchise` | Text | Yes | Franchise name. Suggestions as you type |
| `gm` | Member | Yes | General Manager |

### /admin inactivecheck dm

DM players who have not completed the activity check

**Who can run it:** Manage Server

### /admin inactivecheck manual

Manually change a players activity check status

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `player` | Member | Yes | RSC discord member |
| `status` | Whole number | Yes | Active or Not Active. One of: NotActive, Active |
| `override` | True/False | No | Default: False |

### /admin inactivecheck ping

Ping players who have not completed the activity check

**Who can run it:** Manage Server

### /admin inactivecheck populate

Populate the missing activity check role on players who haven't completed it

**Who can run it:** Manage Server

### /admin inactivecheck role

Set the role to assign to players missing their activity check

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `role` | Role | Yes | Role to assign to players who have not completed the activity check |

### /admin inactivecheck start

Create a channel and ping for inactive check. (DE players only)

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `category` | Channel | Yes |  |

### /admin inactivecheck stop

End inactivity check and delete channel.

**Who can run it:** Manage Server

### /admin inactivecheck testmsg

Preview the activity check DM by sending it to yourself

**Who can run it:** Manage Server

### /admin intents dm

DM players who have not declared their Intent to Play

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `member` | Member | No | DM only this player instead of everyone with a missing intent |
| `message` | Text | No | Custom message to include in the DM (optional) |

### /admin intents dmtest

Preview the Intent to Play DM by sending it to yourself

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `message` | Text | No | Custom message to include in the DM (optional) |

### /admin intents missingchannel

Configure the Intent to Play missing channel

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `channel` | Channel | Yes |  |

### /admin intents missingmsg

Configure the Intent to Play missing message on ping

**Who can run it:** Manage Server

### /admin intents missingrole

Configure the Intent to Play missing discord role

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `role` | Role | Yes |  |

### /admin intents ping

Send a ping to all players with missing intents

**Who can run it:** Manage Server

### /admin intents populate

Apply Intent Missing role to applicable players

**Who can run it:** Manage Server

### /admin intents set

Manually set intent for a player

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `member` | Member | Yes | Discord member to declare intent on |
| `returning` | True/False | Yes | Returning status. (True for returning, False for not returning) |
| `override` | True/False | No | Admin override. Default: False |

### /admin intents setbyid

Manually set intent for a discord ID

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `member` | Whole number | Yes | Discord ID to declare intent on |
| `returning` | True/False | Yes | Returning status. (True for returning, False for not returning) |
| `override` | True/False | No | Admin override. Default: False |

### /admin matches bulk

Create bulk RSC matches

**Who can run it:** Manage Server

### /admin matches create

Create a regular season RSC match

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `match_type` | Text | Yes | One of: REGULAR, PRESEASON, POSTSEASON, FINALS, ANY |
| `format` | Text | Yes | One of: GAME_SERIES, BEST_OF_THREE, BEST_OF_FIVE, BEST_OF_SEVEN |
| `home_team` | Text | Yes | Suggestions as you type |
| `away_team` | Text | Yes | Suggestions as you type |
| `day` | Whole number | No | Default: 0 |

### /admin matches fix

Correct a reported match result

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `home` | Text | Yes | Home team of the match. Suggestions as you type |
| `away` | Text | Yes | Away team of the match. Suggestions as you type |
| `home_wins` | Whole number | Yes | Games the home team won |
| `away_wins` | Whole number | Yes | Games the away team won |

### /admin matches playoff

Create an RSC playoff match

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `round` | Whole number | Yes | One of: PLAYOFF, WILDCARD, QUARTERFINALS, SEMIFINALS, FINALS |
| `format` | Text | Yes | One of: GAME_SERIES, BEST_OF_THREE, BEST_OF_FIVE, BEST_OF_SEVEN |
| `home_team` | Text | Yes | Suggestions as you type |
| `away_team` | Text | Yes | Suggestions as you type |

### /admin members changename

Change RSC name for a member

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `member` | Member | Yes | RSC discord member |
| `name` | Text | Yes | New player name |
| `tracker` | Text | No | Add a tracker link to the user. (Optional) |
| `override` | True/False | No | Admin override (Optional). Default: False |

### /admin members create

Create an RSC member in the API

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `member` | Member | Yes | Discord member being added |
| `rsc_name` | Text | No | RSC player name (Defaults to members display name) |

### /admin members delete

Delete an RSC member in the API

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `member` | Member | Yes | RSC discord member |

### /admin members elevatedroles

Display API elevated roles for a member

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `member` | Member | Yes | RSC discord member |

### /admin members list

Fetch a list of members based on specified criteria.

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `rsc_name` | Text | No | RSC in-game player name (Do not include prefix) |
| `discord_username` | Text | No | Player discord username without discriminator |
| `discord_id` | Text | No | Player discord ID |
| `limit` | Whole number | No | Number of results to return (Default: 10, Max: 64). Default: 10 |
| `offset` | Whole number | No | Return results starting at specified offset (Default: 0). Default: 0 |

### /admin members namehistory

Get an RSC discord members API name history

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `member` | Member | Yes | RSC discord member |

### /admin members notinserver

Report current season league players who are no longer in the discord server

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `status` | Text | No | Only check league players with this status. Defaults to every status except Former, Banned, and…. One of: DRAFT_ELIGIBLE, FREE_AGENT, ROSTERED, RENEWED, IR, WAIVERS, AGMIR, FORMER, BANNED, UNSIGNED_GM, PERM_FA, PERMFA_W, WAIVER_CLAIM, WAIVER_RELEASE, DROPPED |

### /admin members patch

Patch a league player in the API

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `player` | Member | Yes | Discord member to patch |
| `status` | Text | No | Player status. One of: DRAFT_ELIGIBLE, FREE_AGENT, ROSTERED, RENEWED, IR, WAIVERS, AGMIR, FORMER, BANNED, UNSIGNED_GM, PERM_FA, PERMFA_W, WAIVER_CLAIM, WAIVER_RELEASE, DROPPED |
| `tier` | Text | No | Tier name. Suggestions as you type |
| `team` | Text | No | Team name. Suggestions as you type |
| `base_mmr` | Whole number | No | Base MMR |
| `current_mmr` | Whole number | No | Current MMR |
| `contract_length` | Whole number | No | Contract Length |
| `waiver_period` | Text | No | Waiver start date (Example: "2025-01-25") |

### /admin members signup

Sign a player up for the latest RSC season

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `player_type` | Text | Yes | New or Former Player. One of: NEW, FORMER |
| `member` | Member | Yes | Discord member being added |
| `rsc_name` | Text | No | RSC player name (Defaults to members display name) |
| `tracker` | Text | No | Rocket league tracker link |
| `platform` | Text | No | Preferred platform. One of: STEAM, PLAYSTATION, XBOX, EPIC, SWITCH. Default: STEAM |
| `override` | True/False | No | Admin override. Default: False |

### /admin members signupstatus

Find the signup status for a member

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `member` | Member | Yes | Discord member to check signup status for |
| `season` | Whole number | No | Season to check signup status for (defaults to next season) |

### /admin members transfer

Transfer membership to a new Discord account

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `old` | Text | Yes | Old Discord ID |
| `new` | Member | Yes | New Discord Member |

### /admin permfa close

Close a tier's PermFA conversion poll early

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `tier` | Text | Yes | Tier to close (Ex: "Elite"). Suggestions as you type |

### /admin permfa dmtest

Send a preview of the PermFA conversion poll DM to a member

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `member` | Member | Yes | Member to send the preview to (yourself, for example) |
| `reminder` | True/False | No | Preview the reminder version of the DM. Default: False |

### /admin permfa poll

DM a tier's PermFAs asking if they want to convert to Free Agents

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `tier` | Text | Yes | Tier to poll (Ex: "Elite"). Suggestions as you type |

### /admin permfa remind

Re-DM PermFAs who have not answered the conversion poll

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `tier` | Text | Yes | Tier to remind (Ex: "Elite"). Suggestions as you type |

### /admin permfa responses

Show PermFA answers for a tier's conversion poll

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `tier` | Text | Yes | Tier to show (Ex: "Elite"). Suggestions as you type |

### /admin retire audit

Toggle the daily departed player audit report on or off

**Who can run it:** Manage Server

### /admin retire departed

Review and retire league players who are no longer in the server

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `apply` | True/False | No | Actually retire the listed players. Defaults to a dry run that only shows them. Default: False |

### /admin settings

Display RSC Admin settings.

**Who can run it:** Manage Server

### /admin stats current

Current season statistics

**Who can run it:** Manage Server

### /admin stats intentbyfranchise

Intent to Play statistics by Franchise

**Who can run it:** Manage Server

### /admin stats intents

Intent to Play statistics

**Who can run it:** Manage Server

### /admin stats signups

RSC sign-up statistics

**Who can run it:** Manage Server

### /admin sync drafteligible

Sync all draft eligibile players in discord

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `dryrun` | True/False | No | Do not modify any users. Default: False |

### /admin sync franchiseroles

Check if all franchise roles exist. If not, create them.

**Who can run it:** Manage Server

### /admin sync freeagent

Sync all free agent players in discord

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `dryrun` | True/False | No | Do not modify any users. Default: False |

### /admin sync member

Sync an individual members from the API to discord

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `member` | Member | Yes | RSC Discord member to sync |

### /admin sync nonplaying

Sync all non playing discord members. (Long Execution Time)

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `dryrun` | True/False | No | Do not modify any users. Default: False |

### /admin sync players

Sync all league players in discord members. (Long Execution Time)

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `dryrun` | True/False | No | Do not modify any users. Default: False |

### /admin sync requiredroles

Check if all base required roles exist. If not, create them.

**Who can run it:** Manage Server

### /admin sync tiers

Check if all tier roles and channels exist. If not, create them.

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `chatcategory` | Channel | No | Existing category for tier chats. (Optional) |
| `scorecategory` | Channel | No | Existing score reporting category. (Optional) |

### /admin sync transactionchannels

Check if all franchise transaction channels. If not, create them.

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `category` | Channel | Yes | Guild category that holds all franchise transaction channels |
| `delete_stale` | True/False | No | Delete channels in the category that no longer match an active franchise. Default: False |

## /ask

Ask a question about RSC rules, players, teams or schedules

**Who can run it:** Anyone

| Option | Type | Required | Description |
|---|---|---|---|
| `question` | Text | Yes | What do you want to know? |

## /assign

Assign the current modmail to a specific group

**Who can run it:** Manage Channels

| Option | Type | Required | Description |
|---|---|---|---|
| `group` | Text | Yes | Assignable ModMail group name. Suggestions as you type |

## /ballchasing

Ballchasing commands and configuration

### /ballchasing category

Configure the score reporting category for the server

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `category` | Channel | Yes |  |

### /ballchasing key

Configure the Ballchasing API key for the server

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `key` | Text | Yes |  |

### /ballchasing log

Configure the logging channel for Ballchasing commands (Ex: #stats-committee)

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `channel` | Channel | Yes |  |

### /ballchasing manager

Configure the ballchasing management role (Ex: @Stats Committee)

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `role` | Role | Yes |  |

### /ballchasing ping

Test the Ballchasing API key connectivity

**Who can run it:** Manage Server

### /ballchasing scanmissing

Find missing matches in ballchasing

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `matchday` | Whole number | No | Match day to report (Optional: Defaults to current match day) |
| `matchtype` | Text | No | Match type to find. (Default: Regular Season). One of: REGULAR, PRESEASON, POSTSEASON, FINALS, ANY. Default: REGULAR |

### /ballchasing settings

Display settings for ballchasing replay management

**Who can run it:** Manage Server

### /ballchasing toplevelgroup

Configure the top level ballchasing group for RSC

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `group` | Text | Yes | Ballchasing group string (Ex: "rsc-v4rxmuxj6o") |

## /bulkaddrole

Add a role a list of user(s) or another role

**Who can run it:** Manage Roles

| Option | Type | Required | Description |
|---|---|---|---|
| `role` | Role | Yes | Discord role to add |
| `members` | Text | No | Space delimited discord IDs to apply role. (Example: "138778232802508801 352600418062303244")… |
| `to_role` | Role | No | Add the role to everyone in this role. (Optional) |

## /bulkremoverole

Remove a role a list of user(s)

**Who can run it:** Manage Roles

| Option | Type | Required | Description |
|---|---|---|---|
| `role` | Role | Yes | Discord role to remove |
| `members` | Text | No | Space delimited discord IDs to remove role. (Example: "138778232802508801 352600418062303244") |

## /captains

Get information on team captains

### /captains franchise

Display captains of all teams in a franchise

**Who can run it:** Anyone

| Option | Type | Required | Description |
|---|---|---|---|
| `franchise` | Text | Yes | Franchise name. Suggestions as you type |

### /captains team

Team to query

**Who can run it:** Anyone

| Option | Type | Required | Description |
|---|---|---|---|
| `team` | Text | Yes | Suggestions as you type |

### /captains tier

Display captains of all teams in a tier

**Who can run it:** Anyone

| Option | Type | Required | Description |
|---|---|---|---|
| `tier` | Text | Yes | Tier to query. Suggestions as you type |

## /clearallavailability

Clear free agent availability for all tiers

**Who can run it:** Manage Server

## /clearavailability

Clear free agent availability for a specified tier

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `tier` | Text | Yes | Free agent tier (Ex: "Elite"). Suggestions as you type |

## /combinemanager

Manage combines

### /combinemanager api

Configure the API url for combines

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `url` | Text | Yes | Combines API location (Ex: https://devleague.rscna.com/c-api/) |

### /combinemanager category

Configure the combines category channel

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `category` | Channel | Yes | Combines Category Channel |

### /combinemanager guide

Post the combines how-to-play guide

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `channel` | Channel | No | Where to post it. Defaults to #how-to-play in the combines category. |
| `overwrite` | True/False | No | Update the guide that's already posted there with the current one. Default: False |

### /combinemanager settings

Display combine settings

**Who can run it:** Manage Server

### /combinemanager start

Begin RSC combines and create channels

**Who can run it:** Manage Server

### /combinemanager stop

End RSC combines and delete channels

**Who can run it:** Manage Server

### /combinemanager teardown

End combine lobbies that are still up in Discord

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `lobby_id` | Whole number | No | Lobby to end. Leave empty to end every lobby. |

## /combines

Play in RSC Combines

### /combines active

Display active combine games

**Who can run it:** Anyone

| Option | Type | Required | Description |
|---|---|---|---|
| `player` | Member | No | Only show games with containing discord member (Optional) |
| `tier` | Text | No | Only show games with average tier (Optional). Suggestions as you type |

### /combines checkin

Check in for an RSC combines match

**Who can run it:** Anyone

### /combines checkout

Check out of RSC combines

**Who can run it:** Anyone

### /combines lobbyinfo

Get your active combines game lobby info

**Who can run it:** Anyone

| Option | Type | Required | Description |
|---|---|---|---|
| `lobby_id` | Whole number | No |  |

## /dates

Display important RSC dates

**Who can run it:** Anyone

## /devleague

RSC Dev league commands

### /devleague checkin

Check in for dev league

**Who can run it:** Anyone

### /devleague checkout

Check out of dev league

**Who can run it:** Anyone

### /devleague optin

Opt in to dev league (role will be added)

**Who can run it:** Anyone

### /devleague optout

Opt out of dev league (role will be removed)

**Who can run it:** Anyone

### /devleague status

Check your status for Dev League

**Who can run it:** Anyone

## /devleaguemanager

Manage dev league

### /devleaguemanager announcements

Configure the dev league game announcement channel

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `channel` | Channel | Yes | Channel that new dev league games are announced in |

### /devleaguemanager category

Configure the dev league game channel category

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `category` | Channel | Yes | Category that dev league game channels are created in |

### /devleaguemanager disable

Disable dev league game channel creation

**Who can run it:** Manage Server

### /devleaguemanager enable

Enable dev league game channel creation

**Who can run it:** Manage Server

### /devleaguemanager settings

Display dev league settings

**Who can run it:** Manage Server

### /devleaguemanager teardown

End Dev League matches that are still up in Discord

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `match_id` | Whole number | No | Match to end. Leave empty to end every match. |

## /devtest

Test command for development purposes

**Who can run it:** Manage Server

## /drafteligible

Display draft eligible players

**Who can run it:** Anyone

| Option | Type | Required | Description |
|---|---|---|---|
| `tier` | Text | Yes | Tier to search. Suggestions as you type |
| `season` | Whole number | No | RSC Season (Default: current) |
| `limit` | Whole number | No | Max number of results to display (Default: 50). Default: 50 |

## /franchises

Get a list of all RSC franchises

**Who can run it:** Anyone

## /freeagent

List of free agent commands for match check in

### /freeagent availability

Get list of available free agents for specified tier

**Who can run it:** Anyone

| Option | Type | Required | Description |
|---|---|---|---|
| `tier` | Text | Yes | Free agent tier (Ex: "Elite"). Suggestions as you type |

### /freeagent checkin

Check in as an available free agent for the current match day

**Who can run it:** Anyone

### /freeagent checkout

Check out as an available free agent for the current match day

**Who can run it:** Anyone

## /freeagents

List free agents in a specified tier

**Who can run it:** Anyone

| Option | Type | Required | Description |
|---|---|---|---|
| `tier` | Text | Yes | Free agent tier (Ex: "Elite"). Suggestions as you type |

## /getallwithrole

Get all users with the specified role(s). (Max 4 roles)

**Who can run it:** Anyone

| Option | Type | Required | Description |
|---|---|---|---|
| `role` | Role | Yes |  |
| `role2` | Role | No |  |
| `role3` | Role | No |  |
| `role4` | Role | No |  |

## /getid

Lookup discord member account identifiers

**Who can run it:** Anyone

| Option | Type | Required | Description |
|---|---|---|---|
| `member` | Member | Yes | RSC Discord Member |

## /getmassid

Mass lookup version of /getid.

**Who can run it:** Anyone

| Option | Type | Required | Description |
|---|---|---|---|
| `members` | Text | Yes | Space delimited list of any string or ID that could identify a user. |

## /getreactlist

Get a list of users who reacted to a message

**Who can run it:** Anyone

| Option | Type | Required | Description |
|---|---|---|---|
| `channel` | Channel | Yes | Channel containing the message |
| `message_id` | Text | Yes | The discord message ID to fetch reacts from |
| `filter` | Text | No | Only list users who reacted with this emoji |
| `by_tier` | True/False | No | Group users by their tier role (Default: False). Default: False |

## /help

Display a help for RSC Bot or a specific command.

**Who can run it:** Anyone

| Option | Type | Required | Description |
|---|---|---|---|
| `command` | Text | No | Display help for a specific command. Suggestions as you type |

## /intent

Declare or check status of player intent to play

### /intent declare

Declare your intent to play next season of RSC

**Who can run it:** Anyone

### /intent search

Search for intent to play status (Limit: 50)

**Who can run it:** Anyone

| Option | Type | Required | Description |
|---|---|---|---|
| `player` | Member | No | Discord member to search |
| `missing` | True/False | No | Display missing intents |
| `returning` | True/False | No | Display returning or not intents |
| `franchise` | Text | No | Filter by franchise name. Suggestions as you type |
| `team` | Text | No | Filter by team name. Suggestions as you type |

### /intent status

Display intent to play status for next season

**Who can run it:** Anyone

## /leagueinfo

Show league and current season information

**Who can run it:** Anyone

## /leagues

Show all RSC leagues

**Who can run it:** Anyone

## /llm

Configure the RSC LLM

### /llm apikey

Configure the OpenAI API key

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `key` | Text | Yes | OpenAI API Key |

### /llm blacklist add

Add a channel to the LLM blacklist

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `channel` | Channel | Yes | Discord text channel to blacklist |

### /llm blacklist rm

Remove a channel from the LLM blacklist

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `channel` | Channel | Yes | Discord text channel to remove |

### /llm blacklist show

Display the LLM channel blacklist

**Who can run it:** Manage Server

### /llm cooldown

Seconds a user must wait between AI questions

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `seconds` | Whole number | Yes | Cooldown in seconds (0 disables) |

### /llm dailycap

Daily AI question limits

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `per_user` | Whole number | No | Questions per user per day (0 disables) |
| `per_guild` | Whole number | No | Questions across the server per day (0 disables) |

### /llm organization

Configure the OpenAI organization

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `name` | Text | Yes | OpenAI Organization |

### /llm settings

Display LLM settings

**Who can run it:** Manage Server

### /llm summarize

Summarize a private ModMail ticket channel or thread

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `channel` | Channel | No | Ticket text channel or thread to summarize (defaults to current channel) |
| `message_limit` | Whole number | No | Number of recent messages to summarize (max 200). Default: 120 |

### /llm toggle

Toggle llm on or off

**Who can run it:** Manage Server

### /llm usage

AI questions and tokens used today

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `member` | Member | No | Show one member's usage instead of the server total |

## /logs

Display information from bot log files

### /logs tail

Tail the latest log file (Max 1984 bytes)

**Who can run it:** Manage Server

### /logs traceback

Show a recent exception the bot logged

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `exception` | Text | No | A recent exception (default: the newest). Suggestions as you type |

## /match

Get information about your upcoming match

**Who can run it:** Anyone

| Option | Type | Required | Description |
|---|---|---|---|
| `team` | Text | No | Get match information for a specific team (Franchise Management Only). Suggestions as you type |
| `day` | Whole number | No | Get match information for a specific match day |

## /mod

Moderator commands and configuration

### /mod ban

Ban a player from the RSC discord server

**Who can run it:** Ban Members, Kick Members and Manage Roles

| Option | Type | Required | Description |
|---|---|---|---|
| `member` | Member | Yes | Discord member to ban from server |
| `days` | Whole number | No | Number of days. Default: 0 |
| `hours` | Whole number | No | Number of hours. Default: 0 |
| `minutes` | Whole number | No | Number of minutes. Default: 0 |

### /mod history

Display mod action history for a player (Default: Last 90 days)

**Who can run it:** Ban Members, Kick Members and Manage Roles

| Option | Type | Required | Description |
|---|---|---|---|
| `member` | Member | Yes | Discord member to fetch history for |
| `days` | Whole number | No | Past number of days to display history for. Default: 90 |

### /mod kick

Kick a player from the RSC discord server

**Who can run it:** Ban Members, Kick Members and Manage Roles

| Option | Type | Required | Description |
|---|---|---|---|
| `member` | Member | Yes | Discord member to kick from server |

### /mod mute

Mute a player for a period of time (Default: 30 minutes)

**Who can run it:** Ban Members, Kick Members and Manage Roles

| Option | Type | Required | Description |
|---|---|---|---|
| `member` | Member | Yes | Discord member to mute |
| `days` | Whole number | No | Number of days. Default: 0 |
| `hours` | Whole number | No | Number of hours. Default: 0 |
| `minutes` | Whole number | No | Number of minutes. Default: 0 |

### /mod notify

Notify a user via direct message

**Who can run it:** Ban Members, Kick Members and Manage Roles

| Option | Type | Required | Description |
|---|---|---|---|
| `member` | Member | Yes | Discord member to notify |

### /mod recent

Display all recent moderator actions (Default: Last 30 days)

**Who can run it:** Ban Members, Kick Members and Manage Roles

| Option | Type | Required | Description |
|---|---|---|---|
| `days` | Whole number | No | Past number of days to display history for. Default: 30 |

### /mod rules

Display list of RSC rules

**Who can run it:** Ban Members, Kick Members and Manage Roles

### /mod strike

Issue a strike to a player

**Who can run it:** Ban Members, Kick Members and Manage Roles

| Option | Type | Required | Description |
|---|---|---|---|
| `member` | Member | Yes | Discord member to strike |
| `rule` | Text | Yes | Strike rule # |
| `action` | Text | No | Perform a optional moderator action afterwards (Ex: Mute). One of: MUTE, KICK, BAN |
| `days` | Whole number | No | Number of days. Default: 0 |
| `hours` | Whole number | No | Number of hours. Default: 0 |
| `minutes` | Whole number | No | Number of minutes. Default: 0 |

## /numbers

Configuration and commands for Numbers Committee

### /numbers gamesplayed

Display tracker games played for a pysonix season

**Who can run it:** Anyone

| Option | Type | Required | Description |
|---|---|---|---|
| `player` | Member | Yes | RSC Discord Member |
| `psyonix_season` | Whole number | Yes | Pysonix season to display |

### /numbers peaks

Display player MMR peaks for a psyonix season

**Who can run it:** Anyone

| Option | Type | Required | Description |
|---|---|---|---|
| `player` | Member | Yes | RSC Discord Member |
| `psyonix_season` | Whole number | No | Pysonix season to display |

### /numbers role

Configure the Number Committee role

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `role` | Role | Yes |  |

### /numbers settings

Configure numbers module settings

**Who can run it:** Manage Server

## /permfa

Sign up as a permanent free agent

**Who can run it:** Anyone

## /playerinfo

Display league information about a player

**Who can run it:** Anyone

| Option | Type | Required | Description |
|---|---|---|---|
| `player` | Member | Yes | Player discord name to query |

## /playerstats

Display RSC stats for a player

**Who can run it:** Anyone

| Option | Type | Required | Description |
|---|---|---|---|
| `player` | Member | No | RSC Discord Member |
| `season` | Whole number | No |  |
| `postseason` | True/False | No | Default: False |

## /playoffs

Display the playoff hunt for a tier

**Who can run it:** Anyone

| Option | Type | Required | Description |
|---|---|---|---|
| `tier` | Text | No | League tier (Default: your tier). Suggestions as you type |
| `season` | Whole number | No | Season number (Default: current season) |
| `text` | True/False | No | Show the text race board instead of the graphic. Default: False |

## /removerole

Remove a role to the specified user

**Who can run it:** Manage Roles

| Option | Type | Required | Description |
|---|---|---|---|
| `role` | Role | Yes | Discord role to remove |
| `member` | Member | Yes | Player discord name |

## /reportmatch

Report the results of your RSC match

**Who can run it:** Anyone

| Option | Type | Required | Description |
|---|---|---|---|
| `home` | Text | Yes | Home team name. Suggestions as you type |
| `away` | Text | Yes | Away team name. Suggestions as you type |
| `day` | Whole number | No | Match day (Optional) |
| `override` | True/False | No | Admin or stats only override. Default: False |

## /resolve

Send resolved message to a modmail thread

**Who can run it:** Manage Messages

## /roll

Roll a random number

**Who can run it:** Anyone

| Option | Type | Required | Description |
|---|---|---|---|
| `number` | Whole number | No | Default: 100 |

## /roster

Get roster for a team

**Who can run it:** Anyone

| Option | Type | Required | Description |
|---|---|---|---|
| `team` | Text | Yes | Team name to search. Suggestions as you type |

## /rps

Rock, Paper, Scissors

**Who can run it:** Anyone

| Option | Type | Required | Description |
|---|---|---|---|
| `your_choice` | Text | Yes | One of: rock, paper, scissors |

## /rsc

RSC API Configuration

### /rsc events channel

Set the channel league events are logged to.

**Who can run it:** Bot owner only

| Option | Type | Required | Description |
|---|---|---|---|
| `channel` | Channel | Yes | Text channel or thread to post league events in |

### /rsc events cursor

Manually move the league event cursor.

**Who can run it:** Bot owner only

| Option | Type | Required | Description |
|---|---|---|---|
| `id` | Whole number | Yes | Event ID to resume from. Events at or below this are treated as processed. |

### /rsc events filter

Choose which league events are posted to the log channel.

**Who can run it:** Bot owner only

### /rsc events global

Toggle logging of league events not scoped to any league.

**Who can run it:** Bot owner only

### /rsc events interval

Set how often the league event poller runs.

**Who can run it:** Bot owner only

| Option | Type | Required | Description |
|---|---|---|---|
| `seconds` | Whole number | Yes | Poll interval in seconds (30-3600) |

### /rsc events private

Toggle logging of non-public league events.

**Who can run it:** Bot owner only

### /rsc events replay

Re-render a single league event. Does not move the cursor.

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `id` | Whole number | Yes | Event ID to fetch from the API |
| `post` | True/False | No | Send to the configured event log channel instead of replying privately. Default: False |

### /rsc events settings

Display the current league event integration settings.

**Who can run it:** Manage Server

### /rsc events status

Display league event poller health and cursor position.

**Who can run it:** Manage Server

### /rsc events toggle

Toggle the league event poller on or off.

**Who can run it:** Bot owner only

### /rsc key

Configure the RSC API key.

**Who can run it:** Bot owner only

| Option | Type | Required | Description |
|---|---|---|---|
| `key` | Text | Yes |  |

### /rsc league

Set the league this guild correlates to in the API

**Who can run it:** Bot owner only

### /rsc loglevel

Modify the log level of the bot (Development Feature)

**Who can run it:** Bot owner only

| Option | Type | Required | Description |
|---|---|---|---|
| `level` | Text | Yes | One of: CRITICAL, ERROR, WARNING, INFO, DEBUG |

### /rsc modmailbot

Configure the ModMail bot players are directed to.

**Who can run it:** Bot owner only

| Option | Type | Required | Description |
|---|---|---|---|
| `member` | Member | Yes |  |

### /rsc settings

Display the current RSC API settings.

**Who can run it:** Manage Server

### /rsc setup

Perform some basic first time setup for the server

**Who can run it:** Bot owner only

### /rsc timezone

Set the desired time zone for the guild

**Who can run it:** Bot owner only

| Option | Type | Required | Description |
|---|---|---|---|
| `timezone` | Text | Yes | Common time zone string (Ex: America/New_York). Suggestions as you type |

### /rsc url

Configure the RSC API web address.

**Who can run it:** Bot owner only

| Option | Type | Required | Description |
|---|---|---|---|
| `url` | Text | Yes |  |

## /schedule

Display your team or another teams entire schedule

**Who can run it:** Anyone

| Option | Type | Required | Description |
|---|---|---|---|
| `team` | Text | No | Get the schedule for a specific team (Optional). Suggestions as you type |
| `preseason` | True/False | No | Include preseason matches (Default: False). Default: False |

## /season

Display current RSC season for league

**Who can run it:** Anyone

## /serverinfo

Display information about the discord server

**Who can run it:** Anyone

| Option | Type | Required | Description |
|---|---|---|---|
| `details` | True/False | No | Increase verbosity. Default: False |

## /setchannelperm

Modify channel permissions for a role or member

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `channel` | Channel | Yes | Channel to modify permissions |
| `target` | Member or role | Yes | Member or role |
| `permission` | Text | Yes | Permission to modify. One of: AddReactions, AttachFiles, Connect, EmbedLinks, ExternalEmojis, ExternalStickers, MentionEveryone, ReadMessageHistory, ReadMessages, SendMessages, SendMessagesInThread, SendPolls, SendTTSMessages, SendVoiceMessages, Speak, Stream, UseAppCommands, UseEmbeddedActivities, UseExternalApps, UseExternalEmojis, UseExternalSounds, UseExternalStickers, UseSoundsboard, ViewChannel |
| `value` | Text | Yes | Value of permission (Allow/Inherit/Deny). One of: ALLOW, INHERIT, DENY |

## /signup

Sign up for the next RSC season

**Who can run it:** Anyone

## /signupstatus

Check your status for the next RSC season

**Who can run it:** Anyone

## /staff

Display RSC Committees and Staff

**Who can run it:** Anyone

## /standings

Display standings across the league

### /standings franchise

Display franchise standings for season

**Who can run it:** Anyone

| Option | Type | Required | Description |
|---|---|---|---|
| `season` | Whole number | No |  |

### /standings tier

Display tier standings for season

**Who can run it:** Anyone

| Option | Type | Required | Description |
|---|---|---|---|
| `tier` | Text | Yes | Suggestions as you type |
| `season` | Whole number | No |  |

## /teams

Get a list of teams in RSC

### /teams franchise

Get a list of teams for a franchise

**Who can run it:** Anyone

| Option | Type | Required | Description |
|---|---|---|---|
| `franchise` | Text | Yes | Teams in a franchise. Suggestions as you type |

### /teams tier

Get a list of teams in a tier

**Who can run it:** Anyone

| Option | Type | Required | Description |
|---|---|---|---|
| `tier` | Text | Yes | Teams in a league tier. Suggestions as you type |

## /teamstats

Display RSC stats for an RSC team

**Who can run it:** Anyone

| Option | Type | Required | Description |
|---|---|---|---|
| `team` | Text | Yes | Suggestions as you type |
| `postseason` | True/False | No | Default: False |
| `season` | Whole number | No |  |

## /thread

View and configure mod thread settings

### /thread category

Primary category for incoming modmails

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `category` | Channel | Yes | Primary ModMail category |

### /thread groups add

Add an assignable group for modmail threads

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `name` | Text | Yes | Assignable ModMail group name |
| `category` | Channel | Yes | ModMail group discord category |
| `role` | Role | Yes | ModMail group discord role |

### /thread groups list

List of current configured ModMail groups

**Who can run it:** Manage Server

### /thread groups rm

Delete an assignable group for modmail threads

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `group` | Text | Yes | Assignable ModMail group name. Suggestions as you type |

### /thread role

Management role for ModMail threads

**Who can run it:** Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `role` | Role | Yes | Management role for assigning ModMail threads |

### /thread settings

Current configuration for ModMail thread handling

**Who can run it:** Manage Server

## /tiers

Get a list of all league tiers

**Who can run it:** Anyone

## /trackers

RSC Player Tracker Links

### /trackers add

Add a new player tracker

**Who can run it:** Manage Server, or staff position: Admin, Numbers, Numbers Head

| Option | Type | Required | Description |
|---|---|---|---|
| `player` | Member | Yes | RSC Discord Member |
| `tracker` | Text | Yes | Rocket League tracker link |

### /trackers byid

Get information on a tracker ID

**Who can run it:** Manage Server, or staff position: Admin, Numbers, Numbers Head

| Option | Type | Required | Description |
|---|---|---|---|
| `tracker_id` | Whole number | Yes | Tracker ID to query |

### /trackers delete

Delete a tracker (Must have zero MMR pulls)

**Who can run it:** Manage Server, or staff position: Admin, Numbers, Numbers Head

| Option | Type | Required | Description |
|---|---|---|---|
| `tracker_id` | Whole number | Yes | Tracker API ID |

### /trackers link

Link a tracker from player

**Who can run it:** Manage Server, or staff position: Admin, Numbers, Numbers Head

| Option | Type | Required | Description |
|---|---|---|---|
| `tracker_id` | Whole number | Yes | Tracker API ID |
| `player` | Member | Yes | RSC Discord Member |

### /trackers list

List the trackers

**Who can run it:** Manage Server, or staff position: Admin, Numbers, Numbers Head

| Option | Type | Required | Description |
|---|---|---|---|
| `player` | Member | Yes | RSC Discord Member |
| `ids` | True/False | No | Show tracker ids. Default: False |

### /trackers merge

Merge tracker pulls

**Who can run it:** Manage Server, or staff position: Admin, Numbers, Numbers Head

| Option | Type | Required | Description |
|---|---|---|---|
| `source` | Whole number | Yes | Source tracker ID |
| `dest` | Whole number | Yes | Destination tracker ID |

### /trackers old

Display number of outdated RSC tracker links

**Who can run it:** Manage Server, or staff position: Admin, Numbers, Numbers Head

| Option | Type | Required | Description |
|---|---|---|---|
| `status` | Text | No | Tracker status to query (Default: Pulled). One of: NEW, STALE, PULLED, FAILED, MISSING, REPULL, INVALID. Default: PULLED |
| `days` | Whole number | No | Number of days since last update (Default: 90). Default: 90 |

### /trackers recent

Show most recent RL tracker pulls

**Who can run it:** Manage Server, or staff position: Admin, Numbers, Numbers Head

| Option | Type | Required | Description |
|---|---|---|---|
| `status` | Text | No | Tracker status to query (Default: Pulled). One of: NEW, STALE, PULLED, FAILED, MISSING, REPULL, INVALID. Default: PULLED |

### /trackers stats

Display RSC tracker link stats

**Who can run it:** Manage Server, or staff position: Admin, Numbers, Numbers Head

### /trackers unlink

Unlink a tracker from player

**Who can run it:** Manage Server, or staff position: Admin, Numbers, Numbers Head

| Option | Type | Required | Description |
|---|---|---|---|
| `tracker_id` | Whole number | Yes | Tracker API ID |
| `player` | Member | Yes | RSC Discord Member |

## /transactions

Transaction commands and configuration

### /transactions announce

Perform a generic announcement to the transactions channel.

**Who can run it:** Manage Roles

### /transactions announcetrade

Announce a trade between two franchises to the transaction chanenl

**Who can run it:** Manage Roles

### /transactions captain

Promote player(s) to captain of their team

**Who can run it:** Manage Roles

| Option | Type | Required | Description |
|---|---|---|---|
| `player` | Member | Yes | RSC Discord Member |
| `player1` | Member | No |  |
| `player2` | Member | No |  |
| `player3` | Member | No |  |
| `player4` | Member | No |  |
| `player5` | Member | No |  |
| `player6` | Member | No |  |

### /transactions cut

Release a player from their team

**Who can run it:** Manage Roles

| Option | Type | Required | Description |
|---|---|---|---|
| `player` | Member | Yes | Player to cut |
| `notes` | Text | No | Transaction notes (Optional) |
| `announce` | True/False | No | Announce to server (Default: True). Default: True |
| `override` | True/False | No | Admin only override. Default: False |

### /transactions cutmsg

Configure the player cut message

**Who can run it:** Manage Roles and Manage Server

### /transactions draft

Process a draft pick and announce it

**Who can run it:** Manage Roles

| Option | Type | Required | Description |
|---|---|---|---|
| `player` | Member | Yes | RSC discord member being drafted |
| `team` | Text | Yes | Team name. Suggestions as you type |
| `round` | Whole number | Yes | Round player was drafted in |
| `pick` | Whole number | Yes | Pick number |
| `override` | True/False | No | Admin only override (Default: False). Default: False |

### /transactions expire

Manually expire a temporary FA contract

**Who can run it:** Manage Roles

| Option | Type | Required | Description |
|---|---|---|---|
| `player` | Member | Yes | RSC Discord Member |

### /transactions gmnotifications

Toggle GM notifications on or off

**Who can run it:** Manage Roles and Manage Server

### /transactions history

Fetch transaction history

**Who can run it:** Manage Roles

| Option | Type | Required | Description |
|---|---|---|---|
| `player` | Member | No | RSC Discord Member (Optional) |
| `executor` | Member | No | Transaction Executor (Optional) |
| `season` | Whole number | No | RSC Season Number. Example: "19" (Optional) |
| `type` | Text | No | Transaction Type (Optional). One of: NONE, CUT, PICKUP, TRADE, PLAYER_TRADE, SUBSTITUTION, TEMP_FA, PROMOTION, RELEGATION, RESIGN, INACTIVE_RESERVE, RETIRE, WAIVER_RELEASE, AGM_IR, IR_RETURN, IR_CUT, DRAFT, PATCH, INTENT_TO_PLAY, SIGN_UP, PERMANENT_FA_SIGN_UP |
| `limit` | Whole number | No | Max number of transactions to display (Default: 10). Default: 10 |

### /transactions ir

Modify inactive reserve status of a player

**Who can run it:** Manage Roles

| Option | Type | Required | Description |
|---|---|---|---|
| `action` | Whole number | Yes | Inactive Reserve Action. One of: MOVE, RETURN |
| `player` | Member | Yes | RSC Discord Member |
| `notes` | Text | No | Transaction notes (Optional) |
| `announce` | True/False | No | Announce to transactions channel (Default: True). Default: True |
| `override` | True/False | No | Admin only override. Default: False |

### /transactions leaderboard

Display transaction committee leaderboard

**Who can run it:** Manage Roles

| Option | Type | Required | Description |
|---|---|---|---|
| `season` | Whole number | No | RSC Season Number. Example: "23" (Default: Current Season) |
| `transaction_type` | Text | No | Transaction Type (Optional). One of: NONE, CUT, PICKUP, TRADE, PLAYER_TRADE, SUBSTITUTION, TEMP_FA, PROMOTION, RELEGATION, RESIGN, INACTIVE_RESERVE, RETIRE, WAIVER_RELEASE, AGM_IR, IR_RETURN, IR_CUT, DRAFT, PATCH, INTENT_TO_PLAY, SIGN_UP, PERMANENT_FA_SIGN_UP |
| `no_draft` | True/False | No | Exclude draft transactions (Default: False). Default: False |

### /transactions logchannel

Set the transactions committee log channel

**Who can run it:** Manage Roles and Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `channel` | Channel | Yes | Transaction committee log discord channel (Must be a text channel) |

### /transactions notifications

Toggle channel notifications on or off

**Who can run it:** Manage Roles and Manage Server

### /transactions redshirt

Move an AGM to redshirt status

**Who can run it:** Manage Roles

| Option | Type | Required | Description |
|---|---|---|---|
| `player` | Member | Yes | RSC Discord Member |
| `notes` | Text | No | Transaction notes (Optional) |
| `override` | True/False | No | Admin only override. Default: False |

### /transactions resign

Re-sign a player to their team.

**Who can run it:** Manage Roles

| Option | Type | Required | Description |
|---|---|---|---|
| `player` | Member | Yes | RSC Discord Member |
| `team` | Text | Yes | Name of team player resigning player. Suggestions as you type |
| `notes` | Text | No | Transaction notes (Optional) |
| `announce` | True/False | No | Announce to server (Default: True). Default: True |
| `override` | True/False | No | Admin only override. Default: False |

### /transactions retire

Retire a player from the league

**Who can run it:** Manage Roles

| Option | Type | Required | Description |
|---|---|---|---|
| `player` | Member | Yes | RSC discord member to retire |
| `notes` | Text | No | Transaction notes (Optional) |
| `override` | True/False | No | Admin only override (Default: False). Default: False |
| `announce` | True/False | No | Announce to transactions channel (Default: True). Default: True |

### /transactions role

Configure the transaction committee role

**Who can run it:** Manage Roles and Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `role` | Role | Yes | Transaction committee discord role |

### /transactions settings

Display current transactions settings

**Who can run it:** Manage Roles and Manage Server

### /transactions sign

Sign a player to the specified team

**Who can run it:** Manage Roles

| Option | Type | Required | Description |
|---|---|---|---|
| `player` | Member | Yes | Player to sign |
| `team` | Text | Yes | Team the player is being sign on. Suggestions as you type |
| `notes` | Text | No | Transaction notes (Optional) |
| `override` | True/False | No | Admin only override. Default: False |

### /transactions sub

Substitute a player on a team

**Who can run it:** Manage Roles

| Option | Type | Required | Description |
|---|---|---|---|
| `player_in` | Member | Yes | Player being subbed in on the team |
| `player_out` | Member | Yes | Player being subbed out on the team |
| `notes` | Text | No | Substitation notes (Optional) |
| `override` | True/False | No | Admin only override. Default: False |

### /transactions sublist

Fetch a list of all players with a temporary FA contract

**Who can run it:** Manage Roles

### /transactions toggledm

Toggle player direct messages on or off

**Who can run it:** Manage Roles and Manage Server

### /transactions tools clearsublist

Clear cached substitute list

**Who can run it:** Manage Roles and Manage Server

### /transactions tools processtrade

Announce a website trade by transaction ID and reapply player roles

**Who can run it:** Manage Roles and Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `transaction_id` | Whole number | Yes | Transaction ID from the RSC website |
| `roles` | True/False | No | Also reapply Discord roles and nicknames for traded players. Default: True |

### /transactions tools tradeannouncements

Toggle announcing trades performed on the RSC website

**Who can run it:** Manage Roles and Manage Server

### /transactions tools traderoleupdates

Toggle role and nickname updates for trades performed on the RSC website

**Who can run it:** Manage Roles and Manage Server

### /transactions tools validatefutures

Validate a franchise future board

**Who can run it:** Manage Roles

| Option | Type | Required | Description |
|---|---|---|---|
| `franchise` | Text | Yes | Franchise to validate. Suggestions as you type |

### /transactions tools validatefuturesall

Validate all franchise future boards

**Who can run it:** Manage Roles

| Option | Type | Required | Description |
|---|---|---|---|
| `ping` | True/False | No | Ping violating GMs in their franchise transaction channels. Default: False |

### /transactions trade

Process a trade between franchises

**Who can run it:** Manage Roles

| Option | Type | Required | Description |
|---|---|---|---|
| `notes` | Text | No |  |
| `override` | True/False | No | Admin only override. Default: False |
| `announce` | True/False | No | Default: True |

### /transactions transactionchannel

Configure the transaction announcement channel

**Who can run it:** Manage Roles and Manage Server

| Option | Type | Required | Description |
|---|---|---|---|
| `channel` | Channel | Yes | Transaction announcement discord channel (Must be a text channel) |

## /unassign

Move thread back to the primary ModMail category

**Who can run it:** Manage Channels

## /userinfo

Display discord user information for a user

**Who can run it:** Anyone

| Option | Type | Required | Description |
|---|---|---|---|
| `member` | Member | No | RSC Discord Member (Optional) |

## /waivers

Display players currently on waivers

**Who can run it:** Anyone

| Option | Type | Required | Description |
|---|---|---|---|
| `tier` | Text | Yes | Waiver tier name (Ex: "Elite"). Suggestions as you type |

## /welcome

Welcome settings for new members

### /welcome channel

Modify the welcome channel

**Who can run it:** Manage Roles

| Option | Type | Required | Description |
|---|---|---|---|
| `channel` | Channel | Yes | Channel to send welcome message in. (Must be text channel) |

### /welcome message

Modify the welcome message when a user joins the server (Max 512 characters)

**Who can run it:** Manage Roles

| Option | Type | Required | Description |
|---|---|---|---|
| `msg` | Text | Yes | Welcome message string to send (Accepts `{member.mention}`) |

### /welcome roles

Modify the roles a user receives when joining the server

**Who can run it:** Manage Roles

| Option | Type | Required | Description |
|---|---|---|---|
| `role1` | Role | Yes |  |
| `role2` | Role | No |  |
| `role3` | Role | No |  |
| `role4` | Role | No |  |

### /welcome settings

Display the current RSC welcome settings.

**Who can run it:** Manage Roles

### /welcome toggle

Toggle the welcome message on or off

**Who can run it:** Manage Roles

## /whatami

What am I?

**Who can run it:** Anyone

Also works in direct messages with the bot.
