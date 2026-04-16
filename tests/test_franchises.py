from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from rscapi.exceptions import ApiException, NotFoundException
from rscapi.models.franchise import Franchise
from rscapi.models.franchise_gm import FranchiseGM
from rscapi.models.franchise_list import FranchiseList
from rscapi.models.rebrand_a_franchise import RebrandAFranchise

from rsc.exceptions import RscException
from rsc.franchises.franchises import FranchiseMixIn

GUILD_ID = 395806681994493964


def _create_mixin(**attrs):
    """Create a FranchiseMixIn instance bypassing ABC restrictions."""
    saved = FranchiseMixIn.__abstractmethods__
    FranchiseMixIn.__abstractmethods__ = frozenset()
    try:
        m = object.__new__(FranchiseMixIn)
    finally:
        FranchiseMixIn.__abstractmethods__ = saved
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


def _make_franchise_list(id=1, name="Test Franchise", prefix="TF", gm_discord_id=999, gm_name="TestGM"):
    f = MagicMock(spec=FranchiseList)
    f.id = id
    f.name = name
    f.prefix = prefix
    f.gm = MagicMock(spec=FranchiseGM)
    f.gm.discord_id = gm_discord_id
    f.gm.rsc_name = gm_name
    return f


# --- Autocomplete ---


class TestFranchiseAutocomplete:
    async def test_returns_matching_choices(self, mock_guild):
        mixin = _create_mixin(_franchise_cache={mock_guild.id: ["Eagles", "Elephants", "Tigers"]})
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild_id = mock_guild.id

        choices = await mixin.franchise_autocomplete(interaction, "eag")
        names = [c.name for c in choices]
        assert "Eagles" in names
        assert "Elephants" not in names
        assert "Tigers" not in names

    async def test_returns_first_25_on_empty_input(self, mock_guild):
        franchises = [f"Franchise{i}" for i in range(30)]
        mixin = _create_mixin(_franchise_cache={mock_guild.id: franchises})
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild_id = mock_guild.id

        choices = await mixin.franchise_autocomplete(interaction, "")
        assert len(choices) == 25

    async def test_returns_empty_when_no_guild(self):
        mixin = _create_mixin(_franchise_cache={})
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild_id = None

        choices = await mixin.franchise_autocomplete(interaction, "test")
        assert choices == []

    async def test_returns_empty_when_cache_missing(self, mock_guild):
        mixin = _create_mixin(_franchise_cache={})
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild_id = mock_guild.id

        choices = await mixin.franchise_autocomplete(interaction, "test")
        assert choices == []

    async def test_limits_to_25_choices(self, mock_guild):
        franchises = [f"Team{i}" for i in range(30)]
        mixin = _create_mixin(_franchise_cache={mock_guild.id: franchises})
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild_id = mock_guild.id

        choices = await mixin.franchise_autocomplete(interaction, "Team")
        assert len(choices) == 25


# --- Helper functions ---


class TestFranchiseGmByName:
    async def test_returns_gm(self, mock_guild):
        f = _make_franchise_list(name="Eagles", gm_discord_id=123, gm_name="TestGM")
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _franchise_cache={},
        )
        with patch("rsc.franchises.franchises.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.franchises_list.return_value = [f]
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.franchises.franchises.FranchisesApi", return_value=mock_api):
                result = await mixin.franchise_gm_by_name(mock_guild, "Eagles")

        assert result is f.gm

    async def test_returns_none_when_not_found(self, mock_guild):
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _franchise_cache={},
        )
        with patch("rsc.franchises.franchises.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.franchises_list.return_value = []
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.franchises.franchises.FranchisesApi", return_value=mock_api):
                result = await mixin.franchise_gm_by_name(mock_guild, "NonExistent")

        assert result is None

    async def test_raises_when_multiple_matches(self, mock_guild):
        f1 = _make_franchise_list(id=1, name="Eagles")
        f2 = _make_franchise_list(id=2, name="Eagles2")
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _franchise_cache={},
        )
        with patch("rsc.franchises.franchises.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.franchises_list.return_value = [f1, f2]
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.franchises.franchises.FranchisesApi", return_value=mock_api):
                with pytest.raises(ValueError, match="more than one"):
                    await mixin.franchise_gm_by_name(mock_guild, "Eagles")

    async def test_returns_none_when_no_gm(self, mock_guild):
        f = _make_franchise_list(name="Eagles")
        f.gm = None
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _franchise_cache={},
        )
        with patch("rsc.franchises.franchises.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.franchises_list.return_value = [f]
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.franchises.franchises.FranchisesApi", return_value=mock_api):
                result = await mixin.franchise_gm_by_name(mock_guild, "Eagles")

        assert result is None


class TestFetchFranchise:
    async def test_returns_franchise(self, mock_guild):
        f = _make_franchise_list(name="Eagles")
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _franchise_cache={},
        )
        with patch("rsc.franchises.franchises.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.franchises_list.return_value = [f]
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.franchises.franchises.FranchisesApi", return_value=mock_api):
                result = await mixin.fetch_franchise(mock_guild, "Eagles")

        assert result is f

    async def test_returns_none_when_not_found(self, mock_guild):
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _franchise_cache={},
        )
        with patch("rsc.franchises.franchises.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.franchises_list.return_value = []
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.franchises.franchises.FranchisesApi", return_value=mock_api):
                result = await mixin.fetch_franchise(mock_guild, "None")

        assert result is None

    async def test_raises_when_multiple_matches(self, mock_guild):
        f1 = _make_franchise_list(id=1, name="Eagles")
        f2 = _make_franchise_list(id=2, name="Eagles2")
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _franchise_cache={},
        )
        with patch("rsc.franchises.franchises.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.franchises_list.return_value = [f1, f2]
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.franchises.franchises.FranchisesApi", return_value=mock_api):
                with pytest.raises(ValueError, match="more than one"):
                    await mixin.fetch_franchise(mock_guild, "Eagles")


class TestFranchiseNameToId:
    async def test_returns_id(self, mock_guild):
        f = _make_franchise_list(id=42, name="Eagles")
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _franchise_cache={},
        )
        with patch("rsc.franchises.franchises.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.franchises_list.return_value = [f]
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.franchises.franchises.FranchisesApi", return_value=mock_api):
                result = await mixin.franchise_name_to_id(mock_guild, "Eagles")

        assert result == 42

    async def test_returns_zero_when_not_found(self, mock_guild):
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _franchise_cache={},
        )
        with patch("rsc.franchises.franchises.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.franchises_list.return_value = []
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.franchises.franchises.FranchisesApi", return_value=mock_api):
                result = await mixin.franchise_name_to_id(mock_guild, "None")

        assert result == 0

    async def test_raises_when_no_id(self, mock_guild):
        f = _make_franchise_list(id=None, name="Eagles")
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _franchise_cache={},
        )
        with patch("rsc.franchises.franchises.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.franchises_list.return_value = [f]
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.franchises.franchises.FranchisesApi", return_value=mock_api):
                with pytest.raises(AttributeError, match="no ID"):
                    await mixin.franchise_name_to_id(mock_guild, "Eagles")


class TestDeleteFranchiseByName:
    async def test_deletes_franchise(self, mock_guild):
        f = _make_franchise_list(id=10, name="Eagles")
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _franchise_cache={},
        )
        with patch("rsc.franchises.franchises.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.franchises_list.return_value = [f]
            mock_api.franchises_delete.return_value = None
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.franchises.franchises.FranchisesApi", return_value=mock_api):
                await mixin.delete_franchise_by_name(mock_guild, "Eagles")

        mock_api.franchises_delete.assert_awaited_once_with(10)

    async def test_raises_when_not_found(self, mock_guild):
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _franchise_cache={},
        )
        with patch("rsc.franchises.franchises.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.franchises_list.return_value = []
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.franchises.franchises.FranchisesApi", return_value=mock_api):
                with pytest.raises(ValueError, match="does not exist"):
                    await mixin.delete_franchise_by_name(mock_guild, "NonExistent")

    async def test_raises_when_multiple_matches(self, mock_guild):
        f1 = _make_franchise_list(id=1, name="Eagles")
        f2 = _make_franchise_list(id=2, name="Eagles2")
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _franchise_cache={},
        )
        with patch("rsc.franchises.franchises.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.franchises_list.return_value = [f1, f2]
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.franchises.franchises.FranchisesApi", return_value=mock_api):
                with pytest.raises(ValueError, match="more than one"):
                    await mixin.delete_franchise_by_name(mock_guild, "Eagles")

    async def test_raises_when_no_id(self, mock_guild):
        f = _make_franchise_list(id=None, name="Eagles")
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _franchise_cache={},
        )
        with patch("rsc.franchises.franchises.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.franchises_list.return_value = [f]
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.franchises.franchises.FranchisesApi", return_value=mock_api):
                with pytest.raises(AttributeError, match="no ID"):
                    await mixin.delete_franchise_by_name(mock_guild, "Eagles")


class TestFullLogoUrl:
    async def test_returns_full_url(self, mock_guild):
        mixin = _create_mixin(
            _get_api_url=AsyncMock(return_value="https://api.example.com/api/v1/"),
        )
        result = await mixin.full_logo_url(mock_guild, "/media/logos/test.png")
        assert result == "https://api.example.com/media/logos/test.png"

    async def test_raises_when_no_host(self, mock_guild):
        mixin = _create_mixin(
            _get_api_url=AsyncMock(return_value=None),
        )
        with pytest.raises(RuntimeError, match="not configured"):
            await mixin.full_logo_url(mock_guild, "/media/logos/test.png")


# --- API methods ---


class TestFranchisesApi:
    async def test_returns_sorted_franchises(self, mock_guild):
        f1 = _make_franchise_list(id=1, name="Zebras")
        f2 = _make_franchise_list(id=2, name="Alphas")
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _franchise_cache={},
        )
        with patch("rsc.franchises.franchises.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.franchises_list.return_value = [f1, f2]
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.franchises.franchises.FranchisesApi", return_value=mock_api):
                result = await mixin.franchises(mock_guild)

        assert result[0].name == "Alphas"
        assert result[1].name == "Zebras"

    async def test_populates_cache(self, mock_guild):
        f1 = _make_franchise_list(id=1, name="Eagles")
        f2 = _make_franchise_list(id=2, name="Tigers")
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _franchise_cache={},
        )
        with patch("rsc.franchises.franchises.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.franchises_list.return_value = [f1, f2]
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.franchises.franchises.FranchisesApi", return_value=mock_api):
                await mixin.franchises(mock_guild)

        assert "Eagles" in mixin._franchise_cache[mock_guild.id]
        assert "Tigers" in mixin._franchise_cache[mock_guild.id]

    async def test_updates_cache_with_new_entries(self, mock_guild):
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _franchise_cache={mock_guild.id: ["Eagles"]},
        )
        f1 = _make_franchise_list(id=1, name="Eagles")
        f2 = _make_franchise_list(id=2, name="Tigers")

        with patch("rsc.franchises.franchises.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.franchises_list.return_value = [f1, f2]
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.franchises.franchises.FranchisesApi", return_value=mock_api):
                await mixin.franchises(mock_guild)

        assert "Tigers" in mixin._franchise_cache[mock_guild.id]

    async def test_raises_when_franchise_has_no_name(self, mock_guild):
        f = MagicMock(spec=FranchiseList)
        f.name = None
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _franchise_cache={},
        )
        with patch("rsc.franchises.franchises.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.franchises_list.return_value = [f]
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.franchises.franchises.FranchisesApi", return_value=mock_api):
                with pytest.raises(AttributeError, match="no name"):
                    await mixin.franchises(mock_guild)

    async def test_returns_empty_list(self, mock_guild):
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _franchise_cache={},
        )
        with patch("rsc.franchises.franchises.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.franchises_list.return_value = []
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.franchises.franchises.FranchisesApi", return_value=mock_api):
                result = await mixin.franchises(mock_guild)

        assert result == []

    async def test_passes_filters(self, mock_guild):
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
            _franchise_cache={},
        )
        with patch("rsc.franchises.franchises.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.franchises_list.return_value = []
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.franchises.franchises.FranchisesApi", return_value=mock_api):
                await mixin.franchises(mock_guild, prefix="TF", name="Test", gm_name="GM1")

        mock_api.franchises_list.assert_awaited_once_with(
            prefix="TF",
            league=1,
            gm_name="GM1",
            gm_discord_id=None,
            name="Test",
            tier=None,
            tier_name=None,
        )


class TestFranchiseByIdApi:
    async def test_returns_franchise(self, mock_guild):
        f = MagicMock(spec=Franchise)
        f.id = 5
        f.name = "Eagles"
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.franchises.franchises.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.franchises_read.return_value = f
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.franchises.franchises.FranchisesApi", return_value=mock_api):
                result = await mixin.franchise_by_id(mock_guild, 5)

        assert result.id == 5
        mock_api.franchises_read.assert_awaited_once_with(5)


class TestUploadFranchiseLogoApi:
    async def test_uploads_logo(self, mock_guild):
        f = MagicMock(spec=Franchise)
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.franchises.franchises.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.franchises_upload_logo.return_value = f
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.franchises.franchises.FranchisesApi", return_value=mock_api):
                result = await mixin.upload_franchise_logo(mock_guild, id=1, logo=b"fake data")

        assert result is f

    async def test_raises_rsc_exception_on_api_error(self, mock_guild):
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.franchises.franchises.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.franchises_upload_logo.side_effect = ApiException(status=400, reason="Bad Request")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.franchises.franchises.FranchisesApi", return_value=mock_api):
                with pytest.raises(RscException):
                    await mixin.upload_franchise_logo(mock_guild, id=1, logo=b"fake data")


class TestDeleteFranchiseApi:
    async def test_deletes_franchise(self, mock_guild):
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.franchises.franchises.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.franchises_delete.return_value = None
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.franchises.franchises.FranchisesApi", return_value=mock_api):
                await mixin.delete_franchise(mock_guild, id=5)

        mock_api.franchises_delete.assert_awaited_once_with(5)

    async def test_raises_rsc_exception_on_api_error(self, mock_guild):
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.franchises.franchises.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.franchises_delete.side_effect = ApiException(status=404, reason="Not Found")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.franchises.franchises.FranchisesApi", return_value=mock_api):
                with pytest.raises(RscException):
                    await mixin.delete_franchise(mock_guild, id=999)


class TestRebrandFranchiseApi:
    async def test_rebrands_franchise(self, mock_guild):
        f = MagicMock(spec=Franchise)
        rebrand = RebrandAFranchise(name="New Name", prefix="NN", teams=[])
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.franchises.franchises.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.franchises_rebrand.return_value = f
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.franchises.franchises.FranchisesApi", return_value=mock_api):
                result = await mixin.rebrand_franchise(mock_guild, id=1, rebrand=rebrand)

        assert result is f
        mock_api.franchises_rebrand.assert_awaited_once_with(1, rebrand)

    async def test_raises_rsc_exception_on_api_error(self, mock_guild):
        rebrand = RebrandAFranchise(name="New Name", prefix="NN", teams=[])
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.franchises.franchises.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.franchises_rebrand.side_effect = ApiException(status=400, reason="Bad Request")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.franchises.franchises.FranchisesApi", return_value=mock_api):
                with pytest.raises(RscException):
                    await mixin.rebrand_franchise(mock_guild, id=1, rebrand=rebrand)


class TestTransferFranchiseApi:
    async def test_transfers_franchise(self, mock_guild, mock_member):
        f = MagicMock(spec=Franchise)
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
        )

        with patch("rsc.franchises.franchises.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.franchises_transfer_franchise.return_value = f
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.franchises.franchises.FranchisesApi", return_value=mock_api):
                result = await mixin.transfer_franchise(mock_guild, id=1, gm=mock_member)

        assert result is f

    async def test_raises_rsc_exception_on_api_error(self, mock_guild, mock_member):
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
        )

        with patch("rsc.franchises.franchises.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.franchises_transfer_franchise.side_effect = ApiException(status=403, reason="Forbidden")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.franchises.franchises.FranchisesApi", return_value=mock_api):
                with pytest.raises(RscException):
                    await mixin.transfer_franchise(mock_guild, id=1, gm=mock_member)


class TestFranchiseLogoApi:
    async def test_returns_full_logo_url(self, mock_guild):
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _get_api_url=AsyncMock(return_value="https://api.example.com/api/v1/"),
        )
        logo_mock = MagicMock()
        logo_mock.logo = "/media/logos/eagles.png"

        with patch("rsc.franchises.franchises.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.franchises_logo.return_value = logo_mock
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.franchises.franchises.FranchisesApi", return_value=mock_api):
                result = await mixin.franchise_logo(mock_guild, 1)

        assert result == "https://api.example.com/media/logos/eagles.png"

    async def test_returns_none_when_no_host(self, mock_guild):
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _get_api_url=AsyncMock(return_value=None),
        )
        result = await mixin.franchise_logo(mock_guild, 1)
        assert result is None

    async def test_returns_none_when_no_logo(self, mock_guild):
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _get_api_url=AsyncMock(return_value="https://api.example.com/"),
        )
        logo_mock = MagicMock()
        logo_mock.logo = None

        with patch("rsc.franchises.franchises.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.franchises_logo.return_value = logo_mock
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.franchises.franchises.FranchisesApi", return_value=mock_api):
                result = await mixin.franchise_logo(mock_guild, 1)

        assert result is None

    async def test_returns_none_on_not_found(self, mock_guild):
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _get_api_url=AsyncMock(return_value="https://api.example.com/"),
        )

        with patch("rsc.franchises.franchises.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.franchises_logo.side_effect = NotFoundException(status=404, reason="Not Found")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.franchises.franchises.FranchisesApi", return_value=mock_api):
                result = await mixin.franchise_logo(mock_guild, 999)

        assert result is None

    async def test_raises_rsc_exception_on_api_error(self, mock_guild):
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _get_api_url=AsyncMock(return_value="https://api.example.com/"),
        )

        with patch("rsc.franchises.franchises.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.franchises_logo.side_effect = ApiException(status=500, reason="Server Error")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.franchises.franchises.FranchisesApi", return_value=mock_api):
                with pytest.raises(RscException):
                    await mixin.franchise_logo(mock_guild, 1)
