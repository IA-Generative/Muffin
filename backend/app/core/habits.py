"""The collections a person uses most (#286), by counting: no model reads anything here. A use is a collection that an
answer cited, or that the person attached to a question; it weighs less as it gets old, and one use settles nothing."""

import math
import uuid
from datetime import datetime

# What one answer adds to a collection: that it cited it (the answer rests on it), or that the person attached it (they
# chose it, whether or not it was cited).
CITED = 1.0
PINNED = 0.5
# What a collection must add up to before it is a habit - shown, and weighed in the routing: two answers that cited it
# within a few days, or four that had it attached. Below FORGET_BELOW it is no longer counted at all.
THRESHOLD = 1.8
FORGET_BELOW = 0.25
# The score at which a habit weighs the most in the routing (1.0): the weight is the score over this, no more than 1.
FULL_WEIGHT_SCORE = 5.0
# How much more a collection counts in the pre-filter of the routing at the most: a few per cent, so that it only turns
# comparable relevance - a collection that fits clearly better still comes first.
MAX_ROUTING_BONUS = 0.1


def key_of(collection_id: uuid.UUID | str) -> str:
    return f"collection-{collection_id}"


def sentence(name: str) -> str:
    return f"Consulte souvent la collection « {' '.join(name.split())[:120]} »"


def faded(score: float, at: datetime, now: datetime, half_life_days: int) -> float:
    """What a score has become by `now`: half of it every `half_life_days`."""
    age = max((now - at).total_seconds() / 86400, 0.0)
    return score * math.pow(0.5, age / max(half_life_days, 1))


def weight_of(score: float) -> float:
    return min(1.0, max(score, 0.0) / FULL_WEIGHT_SCORE)
