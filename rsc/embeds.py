import discord


class SuccessEmbed(discord.Embed):
    """Generic Success Embed"""

    def __init__(self, **kwargs):
        title = kwargs.pop("title", "Success")
        super().__init__(title=title, color=discord.Color.green(), **kwargs)


class ErrorEmbed(discord.Embed):
    """Generic Error Embed"""

    def __init__(self, **kwargs):
        title = kwargs.pop("title", "Error")
        super().__init__(title=title, color=discord.Color.red(), **kwargs)


class ExceptionErrorEmbed(discord.Embed):
    """Generic Error Embed"""

    def __init__(self, exc_message: str, **kwargs):
        title = kwargs.pop("title", "Error")
        super().__init__(title=title, color=discord.Color.red(), **kwargs)
        self.add_field(name="Reason", value=exc_message, inline=False)
