import pytest

from rsc.utils.website import match_page_url, website_url


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
