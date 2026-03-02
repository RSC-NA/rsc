"""RSC Abstract Base Classes and Metaclasses.

This module provides metaclasses for combining discord.py's Cog system
with ABCMeta, and re-exports RSCProtocol as RSCMixIn for backward compatibility.

For new code, prefer importing from rsc.protocols directly:
    from rsc.protocols import RSCProtocol
"""

from abc import ABCMeta

from discord.ext.commands import CogMeta as DPYCogMeta


class CompositeMetaClass(DPYCogMeta, ABCMeta):
    """
    This allows the metaclass used for proper type detection to
    coexist with discord.py's metaclass
    """


# Deprecated: Use RSCProtocol directly instead
class MixInMetaClass(ABCMeta):
    """Deprecated metaclass. Use RSCProtocol instead."""
