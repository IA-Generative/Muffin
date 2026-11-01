"""What a 👍 or a 👎 says of the style of an answer (#285), by rules: no model reads the comment, and the answer is only
measured. A signal is one thing a person did, said or let show - never a conclusion: one alone changes nothing, several
that agree, recent enough, are what makes a preference."""

import math
import re
from dataclasses import dataclass
from datetime import datetime

from app.core.memory_rules import fold

# One signal weighs 1 when the person said it ("trop long") and less when it is only read from the answer they rated.
SAID = 1.0
MEASURED = 0.4
# What a preference must add up to before it is used: two comments that agree, or one and two measures - never one vote.
THRESHOLD = 1.5

SHORT_ANSWER_CHARS = 700
LONG_ANSWER_CHARS = 2000


@dataclass(frozen=True)
class Signal:
    dimension: str
    # +1 or -1: which side of the dimension this signal is on (see `LEARNED`).
    direction: int
    weight: float


# What is kept for each side of each dimension: the key of the item, and the sentence the assistant is given.
LEARNED: dict[tuple[str, int], tuple[str, str]] = {
    ("verbosity", -1): ("appris-verbosite", "Préfère des réponses concises"),
    ("verbosity", 1): ("appris-verbosite", "Préfère des réponses détaillées"),
    ("table", 1): ("appris-tableau", "Préfère les réponses sous forme de tableau quand cela s'y prête"),
    ("table", -1): ("appris-tableau", "Préfère éviter les tableaux"),
}
KEYS = sorted({key for key, _ in LEARNED.values()})

# What the person says is read after folding (no case, no accents). "pas trop long" says the opposite of "trop long":
# such a phrase is taken out before anything is looked for.
_NEGATED = re.compile(r"\b(pas|plus|jamais) (trop|si|aussi|vraiment) \w+|\b(not|isn't|never) (too|that|so) \w+")
_CONCISE = re.compile(
    r"\b(trop (long|longue|longs|verbeu\w*|detaill\w*|dense|de texte)|verbeu\w*|plus (court|courte|concis\w*|bref\w*|"
    r"synthetique)|moins (long|longue|de texte)|raccourci\w*|(too|a bit|bit too) (long|verbose)|shorter|more concise|"
    r"less verbose)\b"
)
_DETAILED = re.compile(
    r"\b(trop (court|courte|bref|breve|succinct\w*|rapide|superficiel\w*)|pas assez (detaill\w*|develop\w*|complet\w*|"
    r"precis\w*)|plus (detaill\w*|develop\w*|complet\w*)|plus de detail\w*|too (short|brief)|more detail\w*)\b"
)
_NO_TABLE = re.compile(
    r"\b(pas de tableau\w*|sans tableau\w*|(pas|plus) en tableau\w*|moins de tableau\w*|trop de tableau\w*|"
    r"eviter les tableaux|no tables?|without tables?|avoid tables?)\b"
)
_TABLE = re.compile(
    r"\b(en tableau\w*|sous forme de tableau\w*|un tableau|des tableaux|plus de tableau\w*|(as|in) a table|"
    r"table format)\b"
)
_HAS_TABLE = re.compile(r"^\s*\|.*\|\s*\n\s*\|?\s*:?-{3,}", re.MULTILINE)


def signals_of(value: str, reasons: list[str], comment: str | None, answer: str) -> list[Signal]:
    """What one feedback says. A 👎 about the facts, the sources or the tone, with no comment, says nothing of the style
    that can be read without a model: it is no signal."""
    signals: list[Signal] = []
    text = _NEGATED.sub(" ", fold(comment or ""))
    if _CONCISE.search(text):
        signals.append(Signal("verbosity", -1, SAID))
    if _DETAILED.search(text):
        signals.append(Signal("verbosity", 1, SAID))
    if _NO_TABLE.search(text):
        signals.append(Signal("table", -1, SAID))
    elif _TABLE.search(text):
        signals.append(Signal("table", 1, SAID))

    size = len(answer)
    if value == "up":
        if size < SHORT_ANSWER_CHARS:
            signals.append(Signal("verbosity", -1, MEASURED))
        elif size > LONG_ANSWER_CHARS:
            signals.append(Signal("verbosity", 1, MEASURED))
        if _HAS_TABLE.search(answer):
            signals.append(Signal("table", 1, MEASURED))
    elif "not_useful" in reasons and size > LONG_ANSWER_CHARS:
        signals.append(Signal("verbosity", -1, MEASURED))
    return signals


def decayed(weight: float, age_days: float, half_life_days: int) -> float:
    """A signal fades: it weighs half as much after `half_life_days`."""
    return weight * math.pow(0.5, max(age_days, 0.0) / max(half_life_days, 1))


def age_in_days(then: datetime, now: datetime) -> float:
    return (now - then).total_seconds() / 86400
