"""Voice names: which ones are English, and how a requested name is matched."""

# Kitten-TTS 2 names its voices either after a person (English) or '<Language><Thing>' (e.g. SpanishAbuela); nine of
# them are a bare language name ("French").
NON_ENGLISH_LANGUAGES = (
    "Arabic",
    "Chinese",
    "Dutch",
    "French",
    "German",
    "Hindi",
    "Indonesian",
    "Italian",
    "Japanese",
    "Korean",
    "Polish",
    "Portuguese",
    "Russian",
    "Spanish",
    "Turkish",
)


def is_english_voice(name: str) -> bool:
    """The text normaliser of the model is tuned for English: it is only applied to English voices."""
    return not name.startswith(NON_ENGLISH_LANGUAGES)


def resolve_voice(requested: str | None, available: list[str], default: str) -> str | None:
    """The exact name of `requested` (case-insensitive) among `available`, `default` when omitted, else None."""
    wanted = (requested or "").strip() or default
    by_lowercase = {name.lower(): name for name in available}
    return by_lowercase.get(wanted.lower())
