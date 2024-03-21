import re

import discord

# Views
DEFAULT_TIMEOUT = 30.0

# Role Names
GM_ROLE = "General Manager"
AGM_ROLE = "Assistant GM"
LEAGUE_ROLE = "League"
MUTED_ROLE = "Muted"
CAPTAIN_ROLE = "Captain"
PERM_FA_ROLE = "PermFA"
FREE_AGENT_ROLE = "Free Agent"
DEV_LEAGUE_ROLE = "Dev League Interest"
SUBBED_OUT_ROLE = "Subbed Out"
FORMER_GM_ROLE = "Former GM"
FORMER_PLAYER_ROLE = "Former Player"
FORMER_ADMIN_ROLE = "Former Admin"
FORMER_STAFF_ROLE = "Former Staff"
SPECTATOR_ROLE = "Spectator"
IR_ROLE = "IR"

# Emoji
TROPHY_EMOJI = "\U0001F3C6"  # :trophy:
STAR_EMOJI = "\U00002B50"  # :star:
DEV_LEAGUE_EMOJI = "\U0001F451"  # :crown:

# Links

BALLCHASING_URL = "https://ballchasing.com"
BEHAVIOR_RULES_URL = (
    "https://docs.google.com/document/d/1AR241UmyNos8xflYqrzmpHE6Cy6xDcCtfn-32gdtPdI/"
)
RSC_TRACKER_URL = "https://docs.google.com/spreadsheets/d/1HLd_2yMGh_lX3adMLxQglWPIfRuiSiv587ABYnQX-0s/"

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
    use_external_emojis=True,
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
    use_external_emojis=True,
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
    use_external_emojis=True,
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
