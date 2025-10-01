# flake8: noqa

import re

import discord

# Views
DEFAULT_TIMEOUT = 30.0

# Role Names
AGM_ROLE = "Assistant GM"
ADMIN_ROLE = "Admin"
CAPTAIN_ROLE = "Captain"
DEV_LEAGUE_ROLE = "Dev League Interest"
DRAFT_ELIGIBLE = "Draft Eligible"
FORMER_ADMIN_ROLE = "Former Admin"
FORMER_GM_ROLE = "Former GM"
FORMER_PLAYER_ROLE = "Former Player"
FORMER_STAFF_ROLE = "Former Staff"
FREE_AGENT_ROLE = "Free Agent"
GM_ROLE = "General Manager"
IR_ROLE = "IR"
LEAGUE_ROLE = "League"
MUTED_ROLE = "Muted"
PERM_FA_ROLE = "PermFA"
SPECTATOR_ROLE = "Spectator"
SUBBED_OUT_ROLE = "Subbed Out"
PERM_FA_WAITING_ROLE = "PermFA in Waiting"

# NICKM
NICKM_ID = 138778232802508801

# Emoji
TROPHY_EMOJI = "\U0001f3c6"  # :trophy:
STAR_EMOJI = "\U00002b50"  # :star:
DEV_LEAGUE_EMOJI = "\U0001f451"  # :crown:
COOKIE_EMOJI = "\U0001f36a"  # :cookie:
COMBINE_CUP_EMOJI = "\U0001f964"  # :cup_with_straw:

# Links

BALLCHASING_URL = "https://ballchasing.com"
BEHAVIOR_RULES_URL = "https://docs.google.com/document/d/1AR241UmyNos8xflYqrzmpHE6Cy6xDcCtfn-32gdtPdI/"
RSC_TRACKER_URL = "https://docs.google.com/spreadsheets/d/1WVQEfU1DuFMm4s4XUXKI6mdU7k54c8OmdHvjLlDTWX0"

# Moderation

DEFAULT_MUTE_LENGTH = 30  # Default 30 minute mute
DEFAULT_BAN_LENGTH = 30  # Default 30 minute mute

# Permissions


FRANCHISE_ROLE_PERMS = discord.Permissions(
    view_channel=True,
    create_instant_invite=True,
    send_messages=True,
    embed_links=True,
    attach_files=True,
    add_reactions=True,
    use_external_emojis=False,
    read_message_history=True,
    connect=True,
    speak=True,
    stream=True,
    use_embedded_activities=True,
)
GM_ROLE_PERMS = discord.Permissions(
    view_channel=True,
    create_instant_invite=True,
    send_messages=True,
    embed_links=True,
    attach_files=True,
    add_reactions=True,
    use_external_emojis=False,
    read_message_history=True,
    connect=True,
    speak=True,
    stream=True,
    request_to_speak=True,
    use_voice_activation=True,
    use_embedded_activities=True,
    use_application_commands=True,
)
GENERIC_ROLE_PERMS = discord.Permissions(
    view_channel=True,
    create_instant_invite=True,
    send_messages=True,
    embed_links=True,
    attach_files=True,
    add_reactions=True,
    use_external_emojis=False,
    read_message_history=True,
    read_messages=True,
    connect=True,
    speak=True,
    stream=True,
    use_voice_activation=True,
    use_embedded_activities=True,
    use_application_commands=True,
)
MUTED_ROLE_PERMS = discord.Permissions(
    view_channel=True,
    send_messages=False,
    send_messages_in_threads=False,
    create_private_threads=False,
    create_public_threads=False,
    embed_links=False,
    attach_files=False,
    add_reactions=False,
    use_external_emojis=False,
    read_message_history=True,
    read_messages=True,
    send_tts_messages=False,
    send_voice_messages=False,
    connect=True,
    speak=False,
    stream=False,
    use_application_commands=True,
    use_soundboard=False,
)

# Regex

SEASON_TITLE_REGEX = re.compile(r"^S\d+")


# Combines

COMBINES_HELP_1 = """
# :test_tube: RSC Combines Beta Test :test_tube:
## A New Way To Ball :soccer:
Historically, combines have been a mix of experiences for everyone. For some, it's their first time playing games and participating in RSC. For others, it's a casual time during the offseason to either scout around for future teammates or try to make a case for being a valuable player to draft. But due to limitations in our technology, we've always just created tons of empty 10-person voice-channels and let everyone come and go in lobbies throughout the night. This is great for the folks looking for some casual games, but for a new player trying to prove themselves, trying to play a serious game of RL in a 10-person VC with everyone chatting and goofing around isn't the best environment for showing off your skills. **We can do better!**
## New Tech, New Options :desktop:
By leveraging the Dev League software, we've created a new system for Combines that combines the best of Discord with the power of the RSC Numbers Committee and creates a new experience. Now, combines will be individual 4-game series that start in batches every 15-20 minutes every **Monday, Wednesday, and Friday** from **8PM ET** through to **11PM ET** (or when participation starts to dwindle).

This system also allows us (for the first time) to do a full, in-depth analysis of each player's skill directly compared against other people in that same "tier" and skill level. We're going to hopefully use these serious Combine games to help our Numbers Committee get a better sense of how each player plays in relation to the other people in their tier. **More Data == More Competitive Tiers!** :teacher_tone1::first_place:
""".strip()

COMBINES_HELP_2 = """
# How Do I Play?
Every Monday, Wednesday, and Friday, go to https://devleague.rscna.com and check in for a Combines Match. Every 15=20 minutes new lobbies will be generated. You'll receive an invite to join a specific VC channel with your team and will receive information about the lobby. If you are selected as the person to make the lobby, please make sure that you have the game set as a normal 3v3 with no modifiers, in US-E, and on one of the normal legal maps authorized for use in RSC (DFH Stadium, Mannfield, Urban Central, Champions Field, Wasteland, Aquadome).

## Joining the Game
Once all 6 players are in the match, the game will begin using normal RSC Rules. The Home Team will have a person designated to make the lobby. All 6 players should join the lobby immediately. Once all six are in the game, the Away team will join the field and the Home team will follow immediately thereafter. Each session is a **4-Game Series**. It is **NOT** a Best of 5 or a Best of 3. It is a 4-game series. It is possible to have a 2-2 tie in RSC, and this is critical for stat capture.
## Replays
The Away Team will be responsible for capturing Replays for **ALL FOUR GAMES**. If you are on a console or otherwise unable to capture a replay when you are selected as the replay person, **YOU** are responsible for having someone else on your team grab the replays. Your entire lobby will be unable to check in for another series until the scores have been reported **AND** all four replays have been uploaded.
## Score Reporting
Once the four-game series is complete, the two team captains from _BOTH_ teams must report the score, either on the RSC Dev League website (https://devleague.rscna.com) or via the Discord bot commands (`/combine score HOME_SCORE AWAY_SCORE`) Once the score has been reported and verified, the Away team must upload all four replays onto the website or through the bot.
""".strip()

COMBINES_HELP_3 = """
## Player Bot Commands
- `/combines checkin` - Check in to a combines match
- `/combines checkout` - Check out of combines waiting list
- `/combines lobbyinfo` - Get your combine lobby info

## Scout Bot Commands
- `/combines active <player> <tier>` - Search for active combine games to scout!
- `/combines lobbyinfo <LobbyID>` - Get the lobby game information.

""".strip()


COMBINES_HOW_TO_PLAY_1 = (
    "## Log In\n\n"
    "Navigate to https://devleague.rscna.com in your browser and login with Discord then click on the check in button. \n\n**You cannot check in until 10 minutes prior to combines starting.**\n"
)
COMBINES_HOW_TO_PLAY_2 = '## Check In\n\nCheck in on the same page by hitting the "Check In" button.\n'
COMBINES_HOW_TO_PLAY_3 = (
    "## Wait for a discord ping containing your match info\n\n"
    "Now that you are checked in, keep an eye on the #combines-announcements channel for a ping that your lobby is ready. Lobby info along with a direct link to your voice chat channel will be included. **The home team creates the lobby and the away team uploads the replays.**\n"
)
COMBINES_HOW_TO_PLAY_4 = (
    "## Report score and upload replays\n\n"
    "After you have played your 3 matches, the away team will need to upload the replays. The person that created the lobby will report the score and the person from the away team that is uploading the replays will verify the score **after** uploading the replays. It is usually the person on the top of the list that is responsible for uploading the replays. If you are unsure how or are on a console, coordinate with your teammates on who will upload the replays. You can also ask the home team if you don't have anyone on your team capable of uploading them.\n\n"
    "Note: Replays can usually be found in the following directory. `Documents\My Games\Rocket League\TAGame\Demos`\n"
)
COMBINES_HOW_TO_PLAY_5 = (
    "## Queue again!\n\n"
    "If you want to play another series, you **MUST CHECK IN AGAIN**. Just repeat the steps above!\n\n"
    "Thanks to <@!308295592033910784> for putting this guide together"
)
