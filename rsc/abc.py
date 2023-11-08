from abc import ABC
from discord.ext.commands import CogMeta as BaseMeta


class RSCMeta(ABC):
    pass


class CoreMeta(BaseMeta, RSCMeta):
    pass
