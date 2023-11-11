import discord


class SuccessEmbed(discord.Embed):
    """Generic Success Embed"""

    def __init__(self, **kwargs):
        super().__init__(title="Success", color=discord.Color.green(), **kwargs)


class ErrorEmbed(discord.Embed):
    """Generic Error Embed"""

    def __init__(self, **kwargs):
        super().__init__(title="Error", color=discord.Color.red(), **kwargs)


class ExceptionErrorEmbed(discord.Embed):
    """Generic Error Embed"""

    def __init__(self, exc_message: str, **kwargs):
        self.add_field(name="Reason", value=exc_message, inline=False)
        super().__init__(title="Error", color=discord.Color.red(), **kwargs)
