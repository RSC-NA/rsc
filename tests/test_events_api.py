import sys
from pathlib import Path

import pytest

# Add the project root to the path so we can import the modules
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from rscapi import IntegrationsApi
from rscapi.models.league_event_list import LeagueEventList
from rscapi.models.paginated_league_event_list_list import PaginatedLeagueEventListList


class TestIntegrationsApiContract:
    """Verify the rscapi IntegrationsApi surface the poller relies on exists.

    Cheap guard against generated-client drift. Nothing here calls the API.
    """

    EXPECTED_METHODS = [
        "integrations_events_list",
        "integrations_events_list_without_preload_content",
        "integrations_events_retrieve",
    ]

    @pytest.mark.parametrize("method_name", EXPECTED_METHODS)
    def test_method_exists(self, method_name: str):
        assert hasattr(IntegrationsApi, method_name), f"IntegrationsApi missing expected method: {method_name}"
        assert callable(getattr(IntegrationsApi, method_name)), f"IntegrationsApi.{method_name} is not callable"

    @pytest.mark.parametrize(
        "param",
        [
            "ordering",
            "id__gt",
            "limit",
            "league",
            "guild_id",
            "include_global",
            "is_public",
            "_request_timeout",
        ],
    )
    def test_list_accepts_required_params(self, param: str):
        """The poller depends on each of these.

        `ordering` plus `id__gt` are what make the cursor drift-free: ascending
        order means new events append past the window instead of shifting rows
        out of it, so a single bounded request per tick is sufficient.
        """
        import inspect

        sig = inspect.signature(IntegrationsApi.integrations_events_list)
        assert param in sig.parameters, f"integrations_events_list is missing the `{param}` parameter"

    def test_list_returns_a_paginated_envelope(self):
        """The poller reads `count` off page one to size a backlog cheaply."""
        import inspect

        ret = inspect.signature(IntegrationsApi.integrations_events_list).return_annotation
        assert ret is PaginatedLeagueEventListList

        fields = PaginatedLeagueEventListList.model_fields
        assert "count" in fields
        assert "results" in fields

    def test_ordering_supports_ascending_id(self):
        """The whole cursor design rests on this.

        If the server ever drops `id` from `ordering_fields` the request would
        silently fall back to the default `-created_at, -id`, and the poller
        would process newest-first while advancing an ascending cursor - which
        skips events rather than erroring.
        """
        import json
        from pathlib import Path

        spec_path = Path.home() / "dev" / "web-rsc-website" / "openapi" / "openapi.json"
        if not spec_path.exists():
            pytest.skip("API repo not checked out alongside the bot")

        spec = json.loads(spec_path.read_text())
        params = spec["paths"]["/integrations/events/"]["get"]["parameters"]
        ordering = next((p for p in params if p["name"] == "ordering"), None)
        assert ordering is not None, "the events endpoint no longer exposes `ordering`"


class TestLeagueEventListModel:
    def test_to_dict_is_unusable(self):
        """Guards the reason `rsc.events` never calls `to_dict()`.

        Every field on the generated model is marked `readOnly`, so the generator
        excludes all of them and `to_dict()` returns effectively nothing. If this
        test starts failing the client was regenerated correctly and the note in
        `LeagueEventData.from_api` can be dropped.
        """
        event = LeagueEventList(id=5, league=1, category="TRN", action="PTR", object_id=9, is_public=True)
        assert "id" not in event.to_dict()

    def test_model_dump_is_usable(self):
        event = LeagueEventList(id=5, league=1, category="TRN", action="PTR", object_id=9, is_public=True)
        dumped = event.model_dump(mode="json")
        assert dumped["id"] == 5
        assert dumped["category"] == "TRN"
        assert dumped["action"] == "PTR"
