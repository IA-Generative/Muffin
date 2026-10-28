"""Draws a chart from the rows of a query, as a PNG.

Adapted from spreadsheet-analyser (Apache-2.0, analysis-worker/app/chart/render.py).

The spec is data (kind, columns, title), never code: this module is the only thing that draws. Everything about a
chart that cannot be drawn is a ChartError whose message tells the author what to change."""

import datetime as dt
import io
import math
from collections import defaultdict

import matplotlib
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

from app.limits import ChartLimits

# Colour-blind friendly (Okabe-Ito), then greys for the rest.
PALETTE = ["#0072B2", "#E69F00", "#009E73", "#D55E00", "#CC79A7", "#56B4E9", "#F0E442", "#7A7A7A"]
OTHER_COLOR = "#B5B5B5"
_NUMERIC_TYPES = ("TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "UTINYINT", "USMALLINT", "UINTEGER", "UBIGINT")
_NUMERIC_PREFIXES = ("DECIMAL", "DOUBLE", "FLOAT", "REAL", "NUMERIC")


class ChartError(Exception):
    """The chart cannot be drawn as asked: the message is for the author of the spec to act on."""


def _color(index: int) -> str:
    return PALETTE[index % len(PALETTE)]


def _kind(sql_type: str) -> str:
    """temporal | numeric | text, from the type DuckDB gave the column."""
    upper = sql_type.upper()
    if upper.startswith(("DATE", "TIMESTAMP")):
        return "temporal"
    if upper in _NUMERIC_TYPES or upper.startswith(_NUMERIC_PREFIXES):
        return "numeric"
    return "text"


def _to_number(value, column: str, sql_type: str) -> float:
    if value is None:
        return math.nan
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(str(value).strip().replace(",", "."))
    except ValueError as error:
        raise ChartError(
            f"La colonne « {column} » n'est pas numérique ({sql_type}) : « {str(value)[:30]} ». "
            "Convertis-la dans la requête avec TRY_CAST(... AS DOUBLE)."
        ) from error


def _to_datetime(value) -> dt.datetime:
    text = str(value)
    try:
        return dt.datetime.fromisoformat(text)
    except ValueError as error:
        raise ChartError(f"Date illisible : « {text[:30]} ».") from error


def _label(value, kind: str) -> str:
    if value is None:
        return "(vide)"
    text = str(value)
    if kind == "temporal":
        text = text.replace("T", " ").removesuffix(" 00:00:00")
    return text if len(text) <= 28 else text[:27] + "…"


def _thousands(value: float, _position=None) -> str:
    """1234567 -> '1 234 567' (the French way), decimals kept only when they matter."""
    if value == int(value) or abs(value) >= 1000:
        return f"{value:,.0f}".replace(",", " ")
    return f"{value:g}"


class _Data:
    def __init__(self, columns: list[dict], rows: list[list]) -> None:
        self.names = [column["name"] for column in columns]
        self.types = {column["name"]: column["type"] for column in columns}
        self.rows = rows

    def index(self, name: str) -> int:
        if name not in self.names:
            known = ", ".join(f"{n} ({self.types[n]})" for n in self.names)
            raise ChartError(f"Colonne « {name} » introuvable dans le résultat de la requête. Colonnes : {known}.")
        return self.names.index(name)

    def values(self, name: str) -> list:
        position = self.index(name)
        return [row[position] for row in self.rows]

    def numbers(self, name: str) -> list[float]:
        return [_to_number(value, name, self.types[name]) for value in self.values(name)]

    def kind(self, name: str) -> str:
        self.index(name)
        return _kind(self.types[name])


def _sort_key(value, kind: str):
    if value is None:
        return (1, 0)
    if kind == "temporal":
        return (0, _to_datetime(value))
    if kind == "numeric":
        return (0, float(value))
    return (0, str(value).casefold())


def _series(data: _Data, spec: dict, limits: ChartLimits) -> tuple[list, list[tuple[str, list[float]]]]:
    """(x values in the order to draw, [(series label, one value per x)]) for a spec with y columns."""
    x_name = spec["x"]
    x_kind = data.kind(x_name)
    xs = data.values(x_name)
    if spec.get("color"):
        colors = data.values(spec["color"])
        y = data.numbers(spec["y"][0])
        order: dict = {}
        for x in xs:
            order.setdefault(x, len(order))
        labels = list(dict.fromkeys(_label(c, "text") for c in colors))
        if len(labels) > limits.max_series:
            raise ChartError(
                f"Trop de séries ({len(labels)}) : {limits.max_series} au maximum. "
                f"Filtre ou regroupe la colonne « {spec['color']} »."
            )
        sums: dict = defaultdict(float)
        for x, c, value in zip(xs, colors, y, strict=True):
            if not math.isnan(value):
                sums[(x, _label(c, "text"))] += value
        x_values = list(order)
        series = [(label, [sums.get((x, label), 0.0) for x in x_values]) for label in labels]
    else:
        x_values = xs
        series = [(name, data.numbers(name)) for name in spec["y"]]

    sort = spec.get("sort", "none")
    if sort == "x" or (x_kind != "text" and spec["type"] in ("line", "area", "scatter") and sort == "none"):
        sort = "x"
    position = list(range(len(x_values)))
    if sort == "x":
        position.sort(key=lambda i: _sort_key(x_values[i], x_kind))
    elif sort in ("y_desc", "y_asc"):
        first = series[0][1]
        sign = -1 if sort == "y_desc" else 1
        position.sort(key=lambda i: (math.isnan(first[i]), 0 if math.isnan(first[i]) else sign * first[i]))
    ordered_x = [x_values[i] for i in position]
    return ordered_x, [(label, [values[i] for i in position]) for label, values in series]


def _check_categories(count: int, limits: ChartLimits) -> None:
    if count > limits.max_categories:
        raise ChartError(
            f"Trop de catégories ({count}) : {limits.max_categories} au maximum pour ce graphique. "
            "Agrège (GROUP BY) ou garde les plus grandes valeurs (ORDER BY ... DESC LIMIT 20)."
        )


def _style(ax, spec: dict, single_series_label: str | None) -> None:
    ax.set_title(spec["title"], fontsize=14, fontweight="bold", loc="left", pad=14)
    x_label = spec.get("x_label") or spec["x"]
    ax.set_xlabel(x_label, fontsize=10)
    y_label = spec.get("y_label") or single_series_label
    if y_label:
        ax.set_ylabel(y_label, fontsize=10)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.grid(axis="y", alpha=0.3)
    ax.set_axisbelow(True)


def _draw_bars(ax, spec: dict, data: _Data, limits: ChartLimits, horizontal: bool) -> list:
    x_kind = data.kind(spec["x"])
    xs, series = _series(data, spec, limits)
    _check_categories(len(xs), limits)
    labels = [_label(x, x_kind) for x in xs]
    positions = list(range(len(xs)))
    count = len(series)
    stacked = spec.get("stacked") and count > 1
    width = 0.8 if (stacked or count == 1) else 0.8 / count
    bottoms = [0.0] * len(xs)
    handles = []
    for index, (label, values) in enumerate(series):
        clean = [0.0 if math.isnan(v) else v for v in values]
        offset = 0.0 if (stacked or count == 1) else (index - (count - 1) / 2) * width
        place = [p + offset for p in positions]
        if horizontal:
            handles.append(
                ax.barh(place, clean, height=width, left=bottoms if stacked else None, color=_color(index), label=label)
            )
        else:
            handles.append(
                ax.bar(place, clean, width=width, bottom=bottoms if stacked else None, color=_color(index), label=label)
            )
        if stacked:
            bottoms = [b + v for b, v in zip(bottoms, clean, strict=True)]
    if horizontal:
        ax.set_yticks(positions, labels)
        ax.invert_yaxis()
        ax.xaxis.set_major_formatter(FuncFormatter(_thousands))
        ax.grid(axis="x", alpha=0.3)
        ax.grid(axis="y", visible=False)
    else:
        ax.set_xticks(
            positions,
            labels,
            rotation=45 if max(map(len, labels), default=0) > 6 or len(labels) > 12 else 0,
            ha="right" if len(labels) > 12 or max(map(len, labels), default=0) > 6 else "center",
        )
        ax.yaxis.set_major_formatter(FuncFormatter(_thousands))
    if count == 1 and len(xs) <= 20:
        ax.bar_label(
            handles[0], labels=[_thousands(v) if not math.isnan(v) else "" for v in series[0][1]], fontsize=8, padding=2
        )
    return series


def _draw_lines(ax, spec: dict, data: _Data, limits: ChartLimits, filled: bool) -> list:
    x_kind = data.kind(spec["x"])
    xs, series = _series(data, spec, limits)
    if x_kind == "temporal":
        positions: list = [_to_datetime(x) for x in xs]
    elif x_kind == "numeric":
        positions = [float(x) for x in xs]
    else:
        _check_categories(len(xs), limits)
        positions = list(range(len(xs)))
        ax.set_xticks(positions, [_label(x, x_kind) for x in xs], rotation=45, ha="right")
    marker = "o" if len(xs) <= 30 else None
    if filled and spec.get("stacked") and len(series) > 1:
        ax.stackplot(
            positions,
            *[[0.0 if math.isnan(v) else v for v in values] for _, values in series],
            labels=[label for label, _ in series],
            colors=[_color(i) for i in range(len(series))],
            alpha=0.85,
        )
    else:
        for index, (label, values) in enumerate(series):
            ax.plot(positions, values, color=_color(index), marker=marker, markersize=4, linewidth=2, label=label)
            if filled:
                ax.fill_between(
                    positions, [0.0 if math.isnan(v) else v for v in values], color=_color(index), alpha=0.15
                )
    ax.yaxis.set_major_formatter(FuncFormatter(_thousands))
    if x_kind == "temporal":
        ax.figure.autofmt_xdate()
    return series


def _draw_pie(ax, spec: dict, data: _Data, limits: ChartLimits) -> list:
    x_kind = data.kind(spec["x"])
    xs, series = _series(data, spec, limits)
    values = [0.0 if math.isnan(v) else v for v in series[0][1]]
    if any(v < 0 for v in values):
        raise ChartError("Un camembert ne représente que des valeurs positives : filtre ou prends la valeur absolue.")
    if sum(values) <= 0:
        raise ChartError("Le camembert n'a rien à représenter : toutes les valeurs sont nulles.")
    pairs = sorted(zip((_label(x, x_kind) for x in xs), values, strict=True), key=lambda pair: -pair[1])
    if len(pairs) > limits.max_slices:
        rest = sum(value for _, value in pairs[limits.max_slices :])
        pairs = [*pairs[: limits.max_slices], ("Autres", rest)]
    labels, sizes = [p[0] for p in pairs], [p[1] for p in pairs]
    colors = [
        OTHER_COLOR if label == "Autres" and len(pairs) > limits.max_slices else _color(i)
        for i, label in enumerate(labels)
    ]
    wedges, _texts, autotexts = ax.pie(
        sizes,
        colors=colors,
        startangle=90,
        counterclock=False,
        autopct=lambda p: f"{p:.0f} %" if p >= 4 else "",
        pctdistance=0.78,
        wedgeprops={"linewidth": 1, "edgecolor": "white"},
    )
    for text in autotexts:
        text.set_color("white")
        text.set_fontsize(9)
    ax.legend(
        wedges,
        [f"{label} ({_thousands(size)})" for label, size in pairs],
        loc="center left",
        bbox_to_anchor=(1.0, 0.5),
        frameon=False,
        fontsize=9,
    )
    ax.set_title(spec["title"], fontsize=14, fontweight="bold", pad=14)
    return series


def _draw_scatter(ax, spec: dict, data: _Data, limits: ChartLimits) -> list:
    if data.kind(spec["x"]) != "numeric":
        raise ChartError(
            f"Un nuage de points a besoin d'un axe x numérique : « {spec['x']} » est de type {data.types[spec['x']]}."
        )
    xs, series = _series(data, spec, limits)
    positions = [float(x) for x in xs]
    for index, (label, values) in enumerate(series):
        ax.scatter(positions, values, s=18, alpha=0.7, color=_color(index), label=label)
    ax.xaxis.set_major_formatter(FuncFormatter(_thousands))
    ax.yaxis.set_major_formatter(FuncFormatter(_thousands))
    return series


def _draw_histogram(ax, spec: dict, data: _Data) -> None:
    if data.kind(spec["x"]) != "numeric":
        raise ChartError(
            f"Un histogramme a besoin d'une colonne numérique : « {spec['x']} » est de type {data.types[spec['x']]}."
        )
    values = [v for v in data.numbers(spec["x"]) if not math.isnan(v)]
    if not values:
        raise ChartError(f"La colonne « {spec['x']} » est vide : rien à représenter.")
    ax.hist(values, bins=min(30, max(5, int(math.sqrt(len(values))))), color=_color(0), edgecolor="white")
    ax.xaxis.set_major_formatter(FuncFormatter(_thousands))
    ax.yaxis.set_major_formatter(FuncFormatter(_thousands))


def _render(
    spec: dict, columns: list[dict], rows: list[list], truncated: bool = False, limits: ChartLimits | None = None
) -> tuple[bytes, int, int]:
    """The chart as (PNG bytes, width, height). `columns` is [{"name", "type"}] of the query result, `rows` its
    rows; `truncated` says the query had more rows than were drawn (the image says so)."""
    limits = limits or ChartLimits()
    if not rows:
        raise ChartError("Le résultat de la requête est vide : il n'y a rien à représenter.")
    data = _Data(columns, rows)
    figure = Figure(figsize=(limits.width_inches, limits.height_inches), dpi=limits.dpi)
    FigureCanvasAgg(figure)
    axes = figure.add_subplot()
    kind = spec["type"]
    series: list = []
    if kind in ("bar", "barh"):
        series = _draw_bars(axes, spec, data, limits, horizontal=kind == "barh")
    elif kind in ("line", "area"):
        series = _draw_lines(axes, spec, data, limits, filled=kind == "area")
    elif kind == "pie":
        series = _draw_pie(axes, spec, data, limits)
    elif kind == "scatter":
        series = _draw_scatter(axes, spec, data, limits)
    elif kind == "histogram":
        _draw_histogram(axes, spec, data)
    else:
        raise ChartError(f"Type de graphique inconnu : {kind}.")

    if kind != "pie":
        _style(axes, spec, series[0][0] if len(series) == 1 else None)
        if kind == "histogram":
            axes.set_ylabel(spec.get("y_label") or "Effectif", fontsize=10)
        if len(series) > 1:
            axes.legend(frameon=False, fontsize=9)
    if truncated:
        figure.text(
            0.99,
            0.01,
            f"Données limitées aux {len(rows)} premières lignes",
            ha="right",
            va="bottom",
            fontsize=7,
            color="#7A7A7A",
        )
    figure.tight_layout()
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png")
    return buffer.getvalue(), round(limits.width_inches * limits.dpi), round(limits.height_inches * limits.dpi)


def render_chart(
    spec: dict, columns: list[dict], rows: list[list], truncated: bool = False, limits: ChartLimits | None = None
) -> tuple[bytes, int, int]:
    """The chart as (PNG bytes, width, height). `columns` is [{"name", "type"}] of the query result, `rows` its
    rows; `truncated` says the query had more rows than were drawn (the image says so).

    Text is drawn as it is: a `$` in a title or a category is a dollar, not the start of a formula (which would fail to
    parse, or draw something else than what was written)."""
    with matplotlib.rc_context({"text.parse_math": False}):
        return _render(spec, columns, rows, truncated, limits)
