import pytest

from rsc.utils.website import (
    franchise_page_url,
    match_page_url,
    player_page_url,
    rsc_id_number,
    standings_page_url,
    team_page_url,
    website_url,
)


class TestWebsiteUrl:
    @pytest.mark.parametrize(
        ("api_url", "expected"),
        [
            ("https://www.rscna.com/api/v1", "https://www.rscna.com"),
            ("https://www.rscna.com/api/v1/", "https://www.rscna.com"),
            ("https://staging-api.rscna.com/api/v1", "https://staging-api.rscna.com"),
            ("http://localhost:8000/api/v2", "http://localhost:8000"),
            ("https://example.com/rsc/api/v1", "https://example.com/rsc"),
            ("  https://www.rscna.com/api/v1  ", "https://www.rscna.com"),
            ("https://www.rscna.com", "https://www.rscna.com"),
        ],
    )
    def test_strips_the_api_mount(self, api_url, expected):
        assert website_url(api_url) == expected

    @pytest.mark.parametrize("api_url", ["", "www.rscna.com/api/v1", "ftp://rscna.com/api/v1", "https:///api/v1"])
    def test_rejects_non_http_urls(self, api_url):
        assert website_url(api_url) is None

    def test_keeps_paths_that_only_start_with_api(self):
        # "/apis" is not the API mount, so it must survive
        assert website_url("https://example.com/apis/api/v1") == "https://example.com/apis"


class TestMatchPageUrl:
    def test_full_link(self):
        url = match_page_url("https://www.rscna.com", 36901, league_id=1, season_id=11)
        assert url == "https://www.rscna.com/matches/36901/?league=1&season=11&source=matches"

    def test_omits_unknown_season(self):
        url = match_page_url("https://www.rscna.com/", 36901, league_id=1)
        assert url == "https://www.rscna.com/matches/36901/?league=1&source=matches"


class TestStandingsPageUrl:
    def test_opens_the_tiers_playoff_view(self):
        url = standings_page_url("https://www.rscna.com", league_id=1, season_id=11, tier="Elite")
        assert url == "https://www.rscna.com/standings/?league=1&season=11&tier=Elite&mode=playoffs"

    def test_omits_unknown_season(self):
        url = standings_page_url("https://www.rscna.com/", league_id=1, tier="Elite")
        assert url == "https://www.rscna.com/standings/?league=1&tier=Elite&mode=playoffs"

    def test_encodes_the_tier_name(self):
        url = standings_page_url("https://www.rscna.com", league_id=1, season_id=11, tier="Pro Am")
        assert url == "https://www.rscna.com/standings/?league=1&season=11&tier=Pro+Am&mode=playoffs"


class TestRscIdNumber:
    @pytest.mark.parametrize(("rsc_id", "expected"), [("RSC001187", 1187), ("RSC000001", 1), ("rsc42", 42), (" RSC7 ", 7)])
    def test_reads_the_number(self, rsc_id, expected):
        assert rsc_id_number(rsc_id) == expected

    @pytest.mark.parametrize("rsc_id", ["", "RSC", "1187", "RSC12a", "XYZ001187"])
    def test_rejects_other_strings(self, rsc_id):
        assert rsc_id_number(rsc_id) is None


class TestEntityPageUrls:
    def test_player_page(self):
        assert player_page_url("https://www.rscna.com/", 1187, league_id=1) == "https://www.rscna.com/player/1187/?league=1"

    def test_team_page(self):
        assert team_page_url("https://www.rscna.com", 42, league_id=1) == "https://www.rscna.com/team/42/?league=1"

    def test_franchise_page(self):
        assert franchise_page_url("https://www.rscna.com", 7, league_id=1) == "https://www.rscna.com/franchise/7/?league=1"
