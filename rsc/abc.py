from abc import ABCMeta
from discord.ext.commands import CogMeta as DPYCogMeta
from rscapi import Configuration


class RSCMeta(ABCMeta):
    api_conf: Configuration


class CompositeMetaClass(DPYCogMeta, RSCMeta):
    pass
