import discord


class ErrorEmbed(discord.Embed):
    """Generic Error Embed"""

    def __init__(self, **kwargs):
        super().__init__(title="Error", color=discord.Color.red(), **kwargs)
