from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from rscapi.exceptions import ApiException
from rscapi.models.team_standings import TeamStandings
from rscapi.models.tier import Tier

from rsc.exceptions import RscException
from rsc.tiers.tiers import TierMixIn

GUILD_ID = 395806681994493964


def _create_mixin(**attrs):
    """Create a TierMixIn instance bypassing ABC restrictions."""
    saved = TierMixIn.__abstractmethods__
    TierMixIn.__abstractmethods__ = frozenset()
    try:
        m = object.__new__(TierMixIn)
    finally:
        TierMixIn.__abstractmethods__ = saved
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


def _make_tier(id=1, name="Premier", color=0xFF0000, position=1):
    return Tier(id=id, name=name, color=color, position=position)


def _make_standings(franchise="Eagles", team="Eagles Blue", tier="Premier", rank=1, gp=10, gw=7, gl=3):
    return TeamStandings(
        franchise=franchise,
        team=team,
        tier=tier,
        rank=rank,
        games_played=gp,
        games_won=gw,
        games_lost=gl,
    )


# --- Cache / helper tests ---


class TestIsValidTier:
    async def test_returns_true_for_cached_tier(self, mock_guild):
        mixin = _create_mixin(_tier_cache={mock_guild.id: ["Premier", "Master"]})
        assert await mixin.is_valid_tier(mock_guild, "Premier") is True

    async def test_returns_false_for_missing_tier(self, mock_guild):
        mixin = _create_mixin(_tier_cache={mock_guild.id: ["Premier"]})
        assert await mixin.is_valid_tier(mock_guild, "Gold") is False

    async def test_returns_false_when_cache_empty(self, mock_guild):
        mixin = _create_mixin(_tier_cache={})
        assert await mixin.is_valid_tier(mock_guild, "Premier") is False

    async def test_returns_false_when_guild_not_in_cache(self, mock_guild):
        mixin = _create_mixin(_tier_cache={99999: ["Premier"]})
        assert await mixin.is_valid_tier(mock_guild, "Premier") is False


class TestTierFaRoles:
    async def test_returns_matching_fa_roles(self, mock_guild):
        premier_fa = MagicMock(spec=discord.Role, name="PremierFA")
        premier_fa.name = "PremierFA"
        master_fa = MagicMock(spec=discord.Role, name="MasterFA")
        master_fa.name = "MasterFA"
        mock_guild.roles = [premier_fa, master_fa]

        tier1 = _make_tier(id=1, name="Premier")
        tier2 = _make_tier(id=2, name="Master")

        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _tier_cache={},
        )
        with patch("rsc.tiers.tiers.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.tiers_list.return_value = [tier1, tier2]
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.tiers.tiers.TiersApi", return_value=mock_api):
                result = await mixin.tier_fa_roles(mock_guild)

        assert len(result) == 2
        assert premier_fa in result
        assert master_fa in result

    async def test_skips_missing_fa_roles(self, mock_guild):
        premier_fa = MagicMock(spec=discord.Role)
        premier_fa.name = "PremierFA"
        mock_guild.roles = [premier_fa]

        tier1 = _make_tier(id=1, name="Premier")
        tier2 = _make_tier(id=2, name="Master")

        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _tier_cache={},
        )
        with patch("rsc.tiers.tiers.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.tiers_list.return_value = [tier1, tier2]
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.tiers.tiers.TiersApi", return_value=mock_api):
                result = await mixin.tier_fa_roles(mock_guild)

        assert len(result) == 1
        assert premier_fa in result

    async def test_returns_empty_when_no_roles(self, mock_guild):
        mock_guild.roles = []

        tier1 = _make_tier(id=1, name="Premier")

        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _tier_cache={},
        )
        with patch("rsc.tiers.tiers.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.tiers_list.return_value = [tier1]
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.tiers.tiers.TiersApi", return_value=mock_api):
                result = await mixin.tier_fa_roles(mock_guild)

        assert result == []


class TestTierIdByName:
    async def test_returns_id_for_existing_tier(self, mock_guild):
        tier = _make_tier(id=42, name="Premier")
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _tier_cache={},
        )
        with patch("rsc.tiers.tiers.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.tiers_list.return_value = [tier]
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.tiers.tiers.TiersApi", return_value=mock_api):
                result = await mixin.tier_id_by_name(mock_guild, "Premier")

        assert result == 42

    async def test_raises_when_tier_not_found(self, mock_guild):
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _tier_cache={},
        )
        with patch("rsc.tiers.tiers.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.tiers_list.return_value = []
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.tiers.tiers.TiersApi", return_value=mock_api):
                with pytest.raises(ValueError, match="does not exist"):
                    await mixin.tier_id_by_name(mock_guild, "Nonexistent")

    async def test_raises_when_multiple_tiers_match(self, mock_guild):
        tier1 = _make_tier(id=1, name="Premier")
        tier2 = _make_tier(id=2, name="Premier")
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _tier_cache={},
        )
        with patch("rsc.tiers.tiers.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.tiers_list.return_value = [tier1, tier2]
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.tiers.tiers.TiersApi", return_value=mock_api):
                with pytest.raises(ValueError, match="more than one"):
                    await mixin.tier_id_by_name(mock_guild, "Premier")

    async def test_raises_when_tier_has_no_id(self, mock_guild):
        tier = _make_tier(id=None, name="Premier")
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _tier_cache={},
        )
        with patch("rsc.tiers.tiers.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.tiers_list.return_value = [tier]
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.tiers.tiers.TiersApi", return_value=mock_api):
                with pytest.raises(ValueError, match="does not have an ID"):
                    await mixin.tier_id_by_name(mock_guild, "Premier")


# --- API method tests ---


class TestTierByIdApi:
    async def test_returns_tier(self, mock_guild):
        tier = _make_tier(id=5, name="Master")
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.tiers.tiers.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.tiers_read.return_value = tier
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.tiers.tiers.TiersApi", return_value=mock_api):
                result = await mixin.tier_by_id(mock_guild, 5)

        assert result.id == 5
        assert result.name == "Master"
        mock_api.tiers_read.assert_awaited_once_with(5)


class TestTiersApi:
    async def test_returns_sorted_tiers(self, mock_guild):
        t1 = _make_tier(id=1, name="Prospect", position=1)
        t2 = _make_tier(id=2, name="Premier", position=3)
        t3 = _make_tier(id=3, name="Master", position=2)
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _tier_cache={},
        )

        with patch("rsc.tiers.tiers.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.tiers_list.return_value = [t1, t2, t3]
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.tiers.tiers.TiersApi", return_value=mock_api):
                result = await mixin.tiers(mock_guild)

        assert [t.name for t in result] == ["Premier", "Master", "Prospect"]

    async def test_populates_cache_on_first_call(self, mock_guild):
        t1 = _make_tier(id=1, name="Premier", position=2)
        t2 = _make_tier(id=2, name="Master", position=1)
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _tier_cache={},
        )

        with patch("rsc.tiers.tiers.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.tiers_list.return_value = [t1, t2]
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.tiers.tiers.TiersApi", return_value=mock_api):
                await mixin.tiers(mock_guild)

        assert set(mixin._tier_cache[mock_guild.id]) == {"Premier", "Master"}

    async def test_updates_cache_with_new_tiers(self, mock_guild):
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _tier_cache={mock_guild.id: ["Premier"]},
        )
        t1 = _make_tier(id=1, name="Premier", position=2)
        t2 = _make_tier(id=2, name="Master", position=1)

        with patch("rsc.tiers.tiers.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.tiers_list.return_value = [t1, t2]
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.tiers.tiers.TiersApi", return_value=mock_api):
                await mixin.tiers(mock_guild)

        assert "Master" in mixin._tier_cache[mock_guild.id]
        assert "Premier" in mixin._tier_cache[mock_guild.id]

    async def test_does_not_duplicate_cached_tiers(self, mock_guild):
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _tier_cache={mock_guild.id: ["Premier"]},
        )
        t1 = _make_tier(id=1, name="Premier", position=1)

        with patch("rsc.tiers.tiers.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.tiers_list.return_value = [t1]
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.tiers.tiers.TiersApi", return_value=mock_api):
                await mixin.tiers(mock_guild)

        assert mixin._tier_cache[mock_guild.id].count("Premier") == 1

    async def test_raises_when_tier_has_no_name(self, mock_guild):
        t1 = _make_tier(id=1, name="Premier", position=1)
        t2 = MagicMock(spec=Tier)
        t2.name = None
        t2.position = 2
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _tier_cache={},
        )

        with patch("rsc.tiers.tiers.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.tiers_list.return_value = [t1, t2]
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.tiers.tiers.TiersApi", return_value=mock_api):
                with pytest.raises(AttributeError, match="no name"):
                    await mixin.tiers(mock_guild)

    async def test_passes_name_filter(self, mock_guild):
        t1 = _make_tier(id=1, name="Premier", position=1)
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _tier_cache={},
        )

        with patch("rsc.tiers.tiers.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.tiers_list.return_value = [t1]
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.tiers.tiers.TiersApi", return_value=mock_api):
                await mixin.tiers(mock_guild, name="Premier")

        mock_api.tiers_list.assert_awaited_once_with(name="Premier", league=1)

    async def test_returns_empty_list(self, mock_guild):
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _tier_cache={},
        )

        with patch("rsc.tiers.tiers.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.tiers_list.return_value = []
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.tiers.tiers.TiersApi", return_value=mock_api):
                result = await mixin.tiers(mock_guild)

        assert result == []


class TestTierStandings:
    async def test_returns_sorted_standings(self, mock_guild):
        s1 = _make_standings(team="Bravo", rank=2)
        s2 = _make_standings(team="Alpha", rank=1)
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.tiers.tiers.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.tiers_standings.return_value = [s1, s2]
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.tiers.tiers.TiersApi", return_value=mock_api):
                result = await mixin.tier_standings(mock_guild, tier_id=1, season=5)

        assert result[0].rank == 1
        assert result[1].rank == 2
        mock_api.tiers_standings.assert_awaited_once_with(id=1, season=5)

    async def test_raises_rsc_exception_on_api_error(self, mock_guild):
        exc = ApiException(status=404, reason="Not Found")
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.tiers.tiers.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.tiers_standings.side_effect = exc
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.tiers.tiers.TiersApi", return_value=mock_api):
                with pytest.raises(RscException):
                    await mixin.tier_standings(mock_guild, tier_id=999, season=1)

    async def test_returns_empty_standings(self, mock_guild):
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.tiers.tiers.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.tiers_standings.return_value = []
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.tiers.tiers.TiersApi", return_value=mock_api):
                result = await mixin.tier_standings(mock_guild, tier_id=1, season=5)

        assert result == []


class TestCreateTier:
    async def test_creates_and_returns_tier(self, mock_guild):
        created = _make_tier(id=10, name="Bronze", color=0xCD7F32, position=0)
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.tiers.tiers.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.tiers_create.return_value = created
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.tiers.tiers.TiersApi", return_value=mock_api):
                result = await mixin.create_tier(mock_guild, name="Bronze", color=0xCD7F32, position=0)

        assert result.id == 10
        assert result.name == "Bronze"

    async def test_raises_rsc_exception_on_api_error(self, mock_guild):
        exc = ApiException(status=400, reason="Bad Request")
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.tiers.tiers.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.tiers_create.side_effect = exc
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.tiers.tiers.TiersApi", return_value=mock_api):
                with pytest.raises(RscException):
                    await mixin.create_tier(mock_guild, name="Bad", color=0, position=0)


class TestDeleteTier:
    async def test_deletes_tier(self, mock_guild):
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.tiers.tiers.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.tiers_delete.return_value = None
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.tiers.tiers.TiersApi", return_value=mock_api):
                result = await mixin.delete_tier(mock_guild, id=5)

        assert result is None
        mock_api.tiers_delete.assert_awaited_once_with(5)

    async def test_raises_rsc_exception_on_api_error(self, mock_guild):
        exc = ApiException(status=404, reason="Not Found")
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.tiers.tiers.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.tiers_delete.side_effect = exc
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.tiers.tiers.TiersApi", return_value=mock_api):
                with pytest.raises(RscException):
                    await mixin.delete_tier(mock_guild, id=999)


# --- Autocomplete tests ---


class TestTierAutocomplete:
    async def test_returns_matching_choices(self, mock_guild):
        mixin = _create_mixin(_tier_cache={mock_guild.id: ["Premier", "Prospect", "Master"]})
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild_id = mock_guild.id

        choices = await mixin.tier_autocomplete(interaction, "pr")

        names = [c.name for c in choices]
        assert "Premier" in names
        assert "Prospect" in names
        assert "Master" not in names

    async def test_returns_all_on_empty_input(self, mock_guild):
        mixin = _create_mixin(_tier_cache={mock_guild.id: ["Premier", "Master"]})
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild_id = mock_guild.id

        choices = await mixin.tier_autocomplete(interaction, "")

        assert len(choices) == 2

    async def test_returns_empty_when_no_guild(self):
        mixin = _create_mixin(_tier_cache={})
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild_id = None

        choices = await mixin.tier_autocomplete(interaction, "pr")
        assert choices == []

    async def test_returns_empty_when_cache_missing(self, mock_guild):
        mixin = _create_mixin(_tier_cache={})
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild_id = mock_guild.id

        choices = await mixin.tier_autocomplete(interaction, "pr")
        assert choices == []

    async def test_limits_to_25_choices(self, mock_guild):
        tiers = [f"Tier{i}" for i in range(30)]
        mixin = _create_mixin(_tier_cache={mock_guild.id: tiers})
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild_id = mock_guild.id

        choices = await mixin.tier_autocomplete(interaction, "Tier")
        assert len(choices) == 25
