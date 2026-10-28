"""Streaming column statistics. Memory per column is bounded (Counter capped at `max_distinct` entries, a
fixed-size reservoir, a few scalars), so it does not depend on the number of rows."""

import datetime as dt
import math
import random
from collections import Counter
from dataclasses import dataclass, field

from app.tabular.sheets.limits import Limits

ERROR_VALUES = frozenset({"#DIV/0!", "#N/A", "#NAME?", "#NULL!", "#NUM!", "#REF!", "#VALUE!", "#ERROR"})


def value_kind(value) -> str:
    """integer | number | boolean | datetime | date | time | error | text"""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, dt.datetime):
        return "datetime"
    if isinstance(value, dt.date):
        return "date"
    if isinstance(value, dt.time | dt.timedelta):
        return "time"
    if isinstance(value, str) and value in ERROR_VALUES:
        return "error"
    return "text"


def _finite(number: float | None) -> float | None:
    return number if number is not None and math.isfinite(number) else None


def _iso(value) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


@dataclass
class ColumnProfile:
    limits: Limits
    index: int
    seed: int = 0
    kinds: Counter = field(default_factory=Counter)
    non_null: int = 0
    # numeric (Welford's online mean/variance: numerically stable, O(1) memory)
    n_num: int = 0
    mean: float = 0.0
    m2: float = 0.0
    minimum: float | None = None
    maximum: float | None = None
    total: float = 0.0
    reservoir: list[float] = field(default_factory=list)
    # text
    min_length: int | None = None
    max_length: int | None = None
    # The real length of the text (before a long one is cut for the rest), for the average: it is what tells a free
    # text column from a short label, and a text cut at 200 characters would never look long.
    text_chars: int = 0
    text_count: int = 0
    # dates
    first_date: dt.date | dt.datetime | None = None
    last_date: dt.date | dt.datetime | None = None
    # categorical-ish
    distinct: Counter = field(default_factory=Counter)
    distinct_overflow: bool = False
    samples: list = field(default_factory=list)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)

    def add(self, value) -> None:
        if value is None or value == "":
            return
        kind = value_kind(value)
        self.kinds[kind] += 1
        self.non_null += 1
        if kind in ("integer", "number"):
            self._add_number(float(value))
        elif kind == "text":
            self.text_chars += len(value)
            self.text_count += 1
            value = value[: self.limits.max_cell_chars]
            length = len(value)
            self.min_length = length if self.min_length is None else min(self.min_length, length)
            self.max_length = length if self.max_length is None else max(self.max_length, length)
        elif kind in ("date", "datetime"):
            if self.first_date is None or _comparable(value) < _comparable(self.first_date):
                self.first_date = value
            if self.last_date is None or _comparable(value) > _comparable(self.last_date):
                self.last_date = value
        if kind != "error":
            self._count_distinct(value if kind == "text" else _iso(value))
        if len(self.samples) < self.limits.sample_values:
            self.samples.append(_jsonable(value))

    def _add_number(self, number: float) -> None:
        if not math.isfinite(number):
            return
        self.n_num += 1
        delta = number - self.mean
        self.mean += delta / self.n_num
        self.m2 += delta * (number - self.mean)
        self.total += number
        self.minimum = number if self.minimum is None else min(self.minimum, number)
        self.maximum = number if self.maximum is None else max(self.maximum, number)
        # Reservoir sampling (algorithm R): a uniform fixed-size sample of the column, for the quantiles.
        if len(self.reservoir) < self.limits.reservoir_size:
            self.reservoir.append(number)
        else:
            slot = self._rng.randrange(self.n_num)
            if slot < self.limits.reservoir_size:
                self.reservoir[slot] = number

    def _count_distinct(self, key) -> None:
        key = key if isinstance(key, str) else str(key)
        if key in self.distinct or len(self.distinct) < self.limits.max_distinct:
            self.distinct[key] += 1
        else:
            self.distinct_overflow = True  # still counted only for keys already tracked

    def column_type(self) -> str:
        if self.non_null == 0:
            return "empty"
        kinds = {kind: count for kind, count in self.kinds.items() if kind != "error"}
        valid = sum(kinds.values())  # error cells (#DIV/0!...) do not make a column "mixed"
        if valid == 0:
            return "error"
        numeric = kinds.get("integer", 0) + kinds.get("number", 0)
        shares = {"number": numeric, **{k: v for k, v in kinds.items() if k not in ("integer", "number")}}
        dominant, count = max(shares.items(), key=lambda item: item[1])
        if count / valid < 0.95:
            return "mixed"
        if dominant == "number":
            return "integer" if kinds.get("number", 0) == 0 else "number"
        return dominant

    def summary(self, name: str, rows: int) -> dict:
        kind = self.column_type()
        out: dict = {
            "index": self.index,
            "name": name,
            "type": kind,
            "non_null": self.non_null,
            "null": rows - self.non_null,
            "type_counts": dict(self.kinds),
            "distinct": len(self.distinct),
            # False once more than `max_distinct` different values were seen: "distinct" is then a lower bound.
            "distinct_exact": not self.distinct_overflow,
            "sample_values": self.samples,
        }
        if self.kinds.get("error"):
            out["error_cells"] = self.kinds["error"]
        if self.n_num:
            ordered = sorted(self.reservoir)
            out["numeric"] = {
                "count": self.n_num,
                "min": _finite(self.minimum),
                "max": _finite(self.maximum),
                "sum": _finite(self.total),
                "mean": _finite(self.mean),
                "std": _finite(math.sqrt(self.m2 / (self.n_num - 1))) if self.n_num > 1 else 0.0,
                # exact while the column has <= reservoir_size numbers, a uniform-sample estimate beyond
                "median": _quantile(ordered, 0.5),
                "p25": _quantile(ordered, 0.25),
                "p75": _quantile(ordered, 0.75),
                "quantiles_exact": self.n_num <= self.limits.reservoir_size,
            }
        if self.min_length is not None:
            out["text"] = {
                "min_length": self.min_length,
                "max_length": self.max_length,
                "avg_length": round(self.text_chars / self.text_count, 1) if self.text_count else None,
            }
        if self.first_date is not None:
            out["dates"] = {"min": _iso(self.first_date), "max": _iso(self.last_date)}
        if kind in ("text", "boolean", "mixed", "integer") and self.distinct:
            out["top_values"] = [
                {"value": value, "count": count} for value, count in self.distinct.most_common(self.limits.top_values)
            ]
        return out


def _comparable(value) -> dt.datetime:
    return value if isinstance(value, dt.datetime) else dt.datetime.combine(value, dt.time())


def _quantile(ordered: list[float], q: float) -> float | None:
    if not ordered:
        return None
    position = (len(ordered) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    return _finite(ordered[low] + (ordered[high] - ordered[low]) * (position - low))


def _jsonable(value):
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str | int | bool):
        return value[:100] if isinstance(value, str) else value
    return _iso(value)
