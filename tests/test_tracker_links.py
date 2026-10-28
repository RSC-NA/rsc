from rsc.members.tracker_links import TrackerProblem, parse_tracker_line, parse_tracker_links

STEAM = "https://rocketleague.tracker.network/rocket-league/profile/steam/76561197960409023/overview"
EPIC = "https://rocketleague.tracker.network/rocket-league/profile/epic/Xentrick/overview"


class TestParseTrackerLine:
    async def test_valid_profile(self):
        line = await parse_tracker_line(EPIC)
        assert line.valid
        assert (line.platform, line.player_id, line.platform_name) == ("epic", "Xentrick", "Epic")
        assert line.url == EPIC

    async def test_adds_scheme(self):
        line = await parse_tracker_line(EPIC.removeprefix("https://"))
        assert line.valid
        assert line.url == EPIC

    async def test_old_url_format_is_fixed(self):
        line = await parse_tracker_line("https://rocketleague.tracker.network/profile/ps/SomePlayer/overview")
        assert line.valid
        assert line.platform == "psn"

    async def test_home_page_is_not_a_profile(self):
        line = await parse_tracker_line("https://rocketleague.tracker.network/rocket-league/")
        assert line.problem is TrackerProblem.NOT_PROFILE

    async def test_unknown_platform(self):
        line = await parse_tracker_line("https://rocketleague.tracker.network/rocket-league/profile/stadia/Someone")
        assert line.problem is TrackerProblem.UNKNOWN_PLATFORM

    async def test_steam_needs_steam64(self):
        line = await parse_tracker_line("https://rocketleague.tracker.network/rocket-league/profile/steam/xentrick/overview")
        assert line.problem is TrackerProblem.NOT_STEAM64

    async def test_steam64_is_accepted(self):
        assert (await parse_tracker_line(STEAM)).valid


class TestParseTrackerLinks:
    async def test_skips_blank_lines_and_duplicates(self):
        lines = await parse_tracker_links(f"{STEAM}\n\n  \n{EPIC}\n{EPIC.upper().replace('HTTPS', 'https')}\n")
        assert [line.platform for line in lines] == ["steam", "epic"]

    async def test_keeps_bad_lines_in_order(self):
        lines = await parse_tracker_links(f"{STEAM}\nnot a link\n{EPIC}")
        assert [line.valid for line in lines] == [True, False, True]
        assert lines[1].raw == "not a link"
