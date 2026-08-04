from pathlib import Path

CHROMA_PATH = Path(__file__).parent / "db"
OPENAI_CHAT_MODEL = "gpt-5.4-mini"
OPENAI_CHAT_TEMPERATURE: float | None = None
OPENAI_EMBEDDING_MODEL = "text-embedding-3-large"


def openai_chat_completion_options(model: str = OPENAI_CHAT_MODEL) -> dict[str, str | float]:
    options: dict[str, str | float] = {"model": model}
    if OPENAI_CHAT_TEMPERATURE is not None:
        options["temperature"] = OPENAI_CHAT_TEMPERATURE
    return options
