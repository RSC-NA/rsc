"""Tests for long value handling in LLM query embeds."""

from unittest.mock import MagicMock

from rsc.embeds import BetterEmbed, BlueEmbed, EmbedLimits, chunk_field_value
from rsc.llm.llm import LLMMixIn


def build_embeds(response: str, icon_url: str | None = None):
    """Call the embed builder without instantiating the full cog."""
    return LLMMixIn._build_llm_query_embeds(
        MagicMock(),
        response=response,
        icon_url=icon_url,
    )


class TestChunkFieldValue:
    def test_paragraphs_fit_field_limit(self):
        paragraph = "This is a sentence about rocket league rules. " * 10
        text = "\n\n".join([paragraph] * 8)
        assert len(text) > 3500

        chunks = chunk_field_value(text)

        assert len(chunks) > 1
        assert all(len(c) <= EmbedLimits.Field.Value for c in chunks)
        # No content is dropped, only delimiter whitespace at page breaks
        assert "".join(chunks).split() == text.split()

    def test_no_delimiters_hard_splits(self):
        text = "a" * 2000

        chunks = chunk_field_value(text)

        assert len(chunks) > 1
        assert all(len(c) <= EmbedLimits.Field.Value for c in chunks)
        assert "".join(chunks) == text

    def test_short_text_single_chunk(self):
        assert chunk_field_value("short answer") == ["short answer"]

    def test_empty_text_returns_single_chunk(self):
        assert chunk_field_value("") == [""]


class TestPaginate:
    def test_short_description_returns_self(self):
        embed = BlueEmbed(title="RSC AI", description="short answer")

        assert embed.paginate() == [embed]
        assert embed.description == "short answer"

    def test_empty_description_returns_self(self):
        embed = BlueEmbed(title="RSC AI")

        assert embed.paginate() == [embed]

    def test_splits_on_paragraph_before_newline(self):
        first = "\n".join(f"`1300` FA | player{i}" for i in range(120))
        second = "\n".join(f"`1300` PFA | player{i}" for i in range(120))
        assert len(first) < EmbedLimits.Description < len(first) + len(second)
        embed = BetterEmbed(title="Rival Free Agents", description=f"{first}\n\n{second}")

        pages = embed.paginate()

        assert [(p.description or "").strip() for p in pages] == [first, second]
        assert all(p.title == "Rival Free Agents" for p in pages)

    def test_oversized_paragraph_splits_on_newlines(self):
        text = "\n".join(f"line {i} " + "z" * 60 for i in range(200))
        assert len(text) > EmbedLimits.Description * 2

        pages = BlueEmbed(title="RSC AI", description=text).paginate(continued_title="RSC AI (continued)")

        assert len(pages) > 2
        assert all(not p.exceeds_limits() for p in pages)
        assert "".join(p.description or "" for p in pages).split() == text.split()
        assert [p.title for p in pages[1:]] == ["RSC AI (continued)"] * (len(pages) - 1)

    def test_continuations_keep_color_only(self):
        embed = BlueEmbed(title="RSC AI", description="\n".join("z" * 70 for _ in range(100)))
        embed.set_thumbnail(url="https://example.com/icon.png")
        embed.set_footer(text="footer")

        first, *rest = embed.paginate()

        assert first is embed
        assert rest
        assert all(p.color == embed.color for p in rest)
        assert all(p.thumbnail.url is None and p.footer.text is None for p in rest)


class TestAddLongField:
    def test_long_value_split_across_fields(self):
        embed = BlueEmbed(title="RSC AI")
        embed.set_thumbnail(url="https://example.com/icon.png")
        value = "\n".join(f"line {i} with some filler content" for i in range(120))
        assert len(value) > 3500

        leftover = embed.add_long_field(name="Response", value=value)

        assert leftover == ""
        assert len(embed.fields) > 1
        assert embed.fields[0].name == "Response"
        assert embed.fields[1].name == "Response (cont.)"
        assert not embed.exceeds_limits()

    def test_leftover_returned_when_embed_full(self):
        embed = BlueEmbed(title="RSC AI")
        # Consume most of the 6000 character budget up front
        embed.add_long_field(name="Filler", value="x" * 5000)
        value = "y" * 2000

        leftover = embed.add_long_field(name="Response", value=value)

        assert leftover
        assert not embed.exceeds_limits()

    def test_leftover_fits_in_continuation_embed(self):
        first = BlueEmbed(title="RSC AI")
        first.add_long_field(name="Filler", value="x" * 5000)
        filler_fields = len(first.fields)
        value = "\n".join(f"line {i} of the response" for i in range(100))

        leftover = first.add_long_field(name="Response", value=value)
        second = BlueEmbed(title="RSC AI (continued)")
        remaining = second.add_long_field(name="Response (cont.)", value=leftover)

        assert remaining == ""
        assert not second.exceeds_limits()
        # Splitting across embeds preserves the response content
        written = [f.value or "" for f in first.fields[filler_fields:]] + [f.value or "" for f in second.fields]
        assert "".join(written) == value


class TestBuildQueryEmbeds:
    def test_max_length_response(self):
        response = "\n".join(f"paragraph {i} of the answer with filler text" for i in range(90))
        assert len(response) > 3500

        embeds = build_embeds(response)

        assert all(not e.exceeds_limits() for e in embeds)
        assert all(len(e.description or "") <= EmbedLimits.Description for e in embeds)

    def test_short_response_is_single_embed(self):
        embeds = build_embeds("RSC is a Rocket League league.")

        assert len(embeds) == 1
        assert embeds[0].description == "RSC is a Rocket League league."
        assert not embeds[0].fields

    def test_oversized_response_spills_into_continuation_embed(self):
        response = "\n".join(f"line {i} " + "z" * 60 for i in range(200))
        assert len(response) > 12000

        embeds = build_embeds(response)

        assert len(embeds) > 1
        assert embeds[1].title == "RSC AI (continued)"
        assert all(not e.exceeds_limits() for e in embeds)
        # Splitting across embeds preserves the response content
        assert "".join(e.description or "" for e in embeds).split() == response.split()

    def test_thumbnail_only_on_first_embed(self):
        response = "\n".join(f"line {i} " + "z" * 60 for i in range(200))

        embeds = build_embeds(response, icon_url="https://example.com/icon.png")

        assert embeds[0].thumbnail.url == "https://example.com/icon.png"
        assert all(e.thumbnail.url is None for e in embeds[1:])
