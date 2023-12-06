import discord

from rsc.exceptions import RscException


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


class BlueEmbed(discord.Embed):
    """Generic Blue Embed"""

    def __init__(self, **kwargs):
        super().__init__(color=discord.Color.blue(), **kwargs)


class LoadingEmbed(discord.Embed):
    """Generic Loading Embed"""

    def __init__(self, **kwargs):
        title = kwargs.pop("title", "Processing")
        super().__init__(
            title=title,
            description="Working on your request. This can take some time...",
            color=discord.Color.yellow(),
            **kwargs
        )


class ApiExceptionErrorEmbed(discord.Embed):
    """Generic Error Embed"""

    def __init__(self, exc: RscException, **kwargs):
        title = kwargs.pop("title", "API Error")
        super().__init__(title=title, color=discord.Color.red(), **kwargs)
        self.description = exc.reason
        self.add_field(name="Status", value=exc.status, inline=True)
        self.add_field(name="Type", value=exc.__class__.__name__, inline=True)


class ApiExceptionErrorEmbed(discord.Embed):
    """Generic Error Embed"""

    def __init__(self, exc: RscException, **kwargs):
        title = kwargs.pop("title", "API Error")
        super().__init__(title=title, color=discord.Color.red(), **kwargs)
        self.description = exc.reason
        self.add_field(name="Status", value=exc.status, inline=True)
        self.add_field(name="Type", value=exc.__class__.__name__, inline=True)


class ExceptionErrorEmbed(discord.Embed):
    """Generic Error Embed"""

    def __init__(self, exc_message: str, **kwargs):
        title = kwargs.pop("title", "Error")
        super().__init__(title=title, color=discord.Color.red(), **kwargs)
        self.add_field(name="Reason", value=exc_message, inline=False)
