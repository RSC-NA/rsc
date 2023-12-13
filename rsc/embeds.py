import discord

from rsc.exceptions import RscException


class BlueEmbed(discord.Embed):
    """Generic Blue Embed"""

    def __init__(self, **kwargs):
        super().__init__(color=discord.Color.blue(), **kwargs)

class YellowEmbed(discord.Embed):
    """Generic Yellow Embed"""

    def __init__(self, **kwargs):
        super().__init__(color=discord.Color.yellow(), **kwargs)

class OrangeEmbed(discord.Embed):
    """Generic Orange Embed"""

    def __init__(self, **kwargs):
        super().__init__(color=discord.Color.orange(), **kwargs)


class RedEmbed(discord.Embed):
    """Generic Red Embed"""

    def __init__(self, **kwargs):
        super().__init__(color=discord.Color.red(), **kwargs)

class GreenEmbed(discord.Embed):
    """Generic Green Embed"""

    def __init__(self, **kwargs):
        super().__init__(color=discord.Color.green(), **kwargs)


class LoadingEmbed(YellowEmbed):
    """Generic Loading Embed"""

    def __init__(self, **kwargs):
        title = kwargs.pop("title", "Processing")
        super().__init__(title=title, description="Working on your request. Please wait...", **kwargs)


class SuccessEmbed(GreenEmbed):
    """Generic Success Embed"""

    def __init__(self, **kwargs):
        title = kwargs.pop("title", "Success")
        super().__init__(title=title, **kwargs)


class ErrorEmbed(RedEmbed):
    """Generic Error Embed"""

    def __init__(self, **kwargs):
        title = kwargs.pop("title", "Error")
        super().__init__(title=title, **kwargs)

class WarningEmbed(OrangeEmbed):
    """Generic Warning Embed"""

    def __init__(self, **kwargs):
        title = kwargs.pop("title", "Error")
        super().__init__(title=title, **kwargs)


class CooldownEmbed(YellowEmbed):
    """Generic Cooldown Embed"""

    def __init__(self, **kwargs):
        title = kwargs.pop("title", "Error")
        desc= kwargs.pop("description", "This command has a cool down period. Please wait a bit before trying again...")
        super().__init__(title=title, description=desc, **kwargs)


class ApiExceptionErrorEmbed(RedEmbed):
    """Generic Error Embed"""

    def __init__(self, exc: RscException, **kwargs):
        title = kwargs.pop("title", "API Error")
        super().__init__(title=title, **kwargs)
        self.description=exc.reason
        self.add_field(name="Status", value=exc.status, inline=True)
        self.add_field(name="Type", value=exc.__class__.__name__, inline=True)

class ExceptionErrorEmbed(RedEmbed):
    """Generic Error Embed"""

    def __init__(self, exc_message: str, **kwargs):
        title = kwargs.pop("title", "Error")
        super().__init__(title=title, **kwargs)
        self.add_field(name="Reason", value=exc_message, inline=False)


class RapidQuotaEmbed(OrangeEmbed):

    def __init__(self, **kwargs):
        title = kwargs.pop("title", "Quota Exceeded")
        desc = kwargs.pop("description", "We have exceeded the maximum number of requests for today.")
        super().__init__(title=title, description=desc, **kwargs)


class RapidTimeOutEmbed(OrangeEmbed):

    def __init__(self, **kwargs):
        title = kwargs.pop("title", "API Timeout")
        desc = kwargs.pop("description", "Request to API has timed out. Please try again later.")
        super().__init__(title=title, description=desc, **kwargs)

class NotImplementedEmbed(RedEmbed):

    def __init__(self, **kwargs):
        super().__init__(title="Not Implemented", description="Command has not been implemented yet.", **kwargs)
