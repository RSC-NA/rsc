from abc import ABCMeta
import discord
from discord.ext.commands import CogMeta as DPYCogMeta
from rscapi import Configuration

from typing import Dict

class RSCMeta(ABCMeta):
    _api_conf: Dict[discord.Guild, Configuration]
    _league: Dict[discord.Guild, int]


class CompositeMetaClass(DPYCogMeta, RSCMeta):
    pass
