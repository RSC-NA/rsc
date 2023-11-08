import discord
import logging

from redbot.core import app_commands, checks

from rscapi import ApiClient, NumbersApi

from rsc.embeds import ErrorEmbed

from typing import Optional

log = logging.getLogger("red.rsc.members")


class MembersMixIn:
    pass
