from rsc.utils.cache import merge_name_cache


class TestMergeNameCache:
    def test_full_refresh_replaces_the_cache(self):
        assert merge_name_cache(["Old"], ["New"], full_refresh=True) == ["New"]

    def test_filtered_query_only_adds(self):
        assert merge_name_cache(["Alpha"], ["Bravo"], full_refresh=False) == ["Alpha", "Bravo"]

    def test_filtered_query_does_not_repeat_a_cached_name(self):
        assert merge_name_cache(["Alpha"], ["Alpha"], full_refresh=False) == ["Alpha"]

    def test_drops_duplicates_within_the_api_list(self):
        assert merge_name_cache([], ["Alpha", "Alpha"], full_refresh=True) == ["Alpha"]

    def test_drops_duplicates_already_in_the_cache(self):
        assert merge_name_cache(["Alpha", "Alpha"], ["Bravo"], full_refresh=False) == ["Alpha", "Bravo"]

    def test_keeps_api_order(self):
        """The tier cache is ordered by tier position, not alphabetically."""
        tiers = ["Premier", "Master", "Elite", "Amateur"]
        assert merge_name_cache([], tiers, full_refresh=True) == tiers

    def test_accepts_a_generator(self):
        assert merge_name_cache([], (n for n in ["Alpha", "Alpha"]), full_refresh=True) == ["Alpha"]

    def test_names_differing_in_case_are_distinct(self):
        assert merge_name_cache([], ["Dik-Diks", "Dik-diks"], full_refresh=True) == ["Dik-Diks", "Dik-diks"]
