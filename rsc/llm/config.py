from pathlib import Path
from typing import Any

CHROMA_PATH = Path(__file__).parent / "db"
OPENAI_CHAT_MODEL = "gpt-5.4-mini"
OPENAI_CHAT_TEMPERATURE: float | None = None
OPENAI_EMBEDDING_MODEL = "text-embedding-3-large"


# Returns `Any` values because the result is splatted into the OpenAI SDK's
# TypedDict kwargs, which a concrete `str | float` union cannot satisfy.
def openai_chat_completion_options(model: str = OPENAI_CHAT_MODEL) -> dict[str, Any]:
    options: dict[str, Any] = {"model": model}
    if OPENAI_CHAT_TEMPERATURE is not None:
        options["temperature"] = OPENAI_CHAT_TEMPERATURE
    return options
