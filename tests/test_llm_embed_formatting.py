"""Tests for long value handling in LLM query embeds."""

from rsc.embeds import BlueEmbed, EmbedLimits, chunk_field_value
from rsc.llm.llm import LLMMixIn


def build_embeds(question: str, response: str, sources: str | None = None, icon_url: str | None = None):
    """Call the embed builder without instantiating the full cog."""
    return LLMMixIn._build_llm_query_embeds(
        None,  # type: ignore[arg-type]
        question=question,
        response=response,
        sources=sources,
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
        value = "y" * 2000

        leftover = first.add_long_field(name="Response", value=value)
        second = BlueEmbed(title="RSC AI (continued)")
        remaining = second.add_long_field(name="Response (cont.)", value=leftover)

        assert remaining == ""
        assert not second.exceeds_limits()


class TestBuildQueryEmbeds:
    def test_max_length_question_and_response(self):
        question = "q" * 6000
        response = "\n".join(f"paragraph {i} of the answer with filler text" for i in range(90))
        assert len(response) > 3500

        embeds = build_embeds(question, response, sources="- RSC Rules (ID: 1)")

        assert all(not e.exceeds_limits() for e in embeds)
        assert len(embeds[0].fields[0].value or "") <= EmbedLimits.Field.Value
        assert embeds[-1].fields[-1].name == "Sources"

    def test_short_response_is_single_embed(self):
        embeds = build_embeds("What is RSC?", "RSC is a Rocket League league.", sources="- Help")

        assert len(embeds) == 1
        field_names = [f.name for f in embeds[0].fields]
        assert field_names == ["Question", "Response", "Sources"]

    def test_oversized_response_spills_into_continuation_embed(self):
        response = "\n".join(f"line {i} " + "z" * 60 for i in range(200))
        assert len(response) > 12000

        embeds = build_embeds("Explain everything", response)

        assert len(embeds) > 1
        assert embeds[1].title == "RSC AI (continued)"
        assert all(not e.exceeds_limits() for e in embeds)

    def test_thumbnail_only_on_first_embed(self):
        response = "\n".join(f"line {i} " + "z" * 60 for i in range(200))

        embeds = build_embeds("Explain everything", response, icon_url="https://example.com/icon.png")

        assert embeds[0].thumbnail.url == "https://example.com/icon.png"
        assert all(e.thumbnail.url is None for e in embeds[1:])
