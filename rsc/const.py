import discord

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

# Emoji
TROPHY_EMOJI = "\U0001F3C6"  # :trophy:
STAR_EMOJI = "\U00002B50"  # :star:

# Links

BEHAVIOR_RULES_URL = (
    "https://docs.google.com/document/d/1AR241UmyNos8xflYqrzmpHE6Cy6xDcCtfn-32gdtPdI/"
)


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
