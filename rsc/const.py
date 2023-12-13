import discord
import re

# Views
DEFAULT_TIMEOUT = 30.0

# Role Names
GM_ROLE = "General Manager"
LEAGUE_ROLE = "League"
MUTED_ROLE = "Muted"
CAPTAIN_ROLE = "Captain"
PERM_FA_ROLE = "PermFA"
FREE_AGENT_ROLE = "Free Agent"
DEV_LEAGUE_ROLE = "Dev League Interest"
SUBBED_OUT_ROLE = "Subbed Out"
FORMER_GM_ROLE = "Former GM"
SPECTATOR_ROLE = "Spectator"
IR_ROLE = "IR"

# Emoji
TROPHY_EMOJI = "\U0001F3C6"  # :trophy:
STAR_EMOJI = "\U00002B50"  # :star:
DEV_LEAGUE_EMOJI = "\U0001F451" # :crown:

# Links

BALLCHASING_URL = "https://ballchasing.com"
BEHAVIOR_RULES_URL = (
    "https://docs.google.com/document/d/1AR241UmyNos8xflYqrzmpHE6Cy6xDcCtfn-32gdtPdI/"
)
RAPIDAPI_URL = "https://rocket-league1.p.rapidapi.com"
RSC_TRACKER_URL = ""

# Moderation

DEFAULT_MUTE_LENGTH = 30 # Default 30 minute mute
DEFAULT_BAN_LENGTH = 30 # Default 30 minute mute

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

# Regex

SEASON_TITLE_REGEX = re.compile(r"^S\d+")