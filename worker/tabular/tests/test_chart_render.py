import io

import pytest
from PIL import Image

from app.chart import ChartError, render_chart
from app.limits import ChartLimits

COLUMNS = [
    {"name": "région", "type": "VARCHAR"},
    {"name": "total", "type": "DOUBLE"},
    {"name": "n", "type": "BIGINT"},
    {"name": "jour", "type": "DATE"},
    {"name": "produit", "type": "VARCHAR"},
]
ROWS = [
    ["Nord", 344148.66, 6780, "2024-01-01", "A"],
    ["Sud", 339082.77, 6652, "2024-02-01", "B"],
    ["Est", 328142.09, 6568, "2024-03-01", "A"],
    ["Ouest", 120000.5, 3000, "2024-04-01", "B"],
]


def spec(**overrides) -> dict:
    return {"type": "bar", "x": "région", "y": ["total"], "title": "Total par région", **overrides}


def drawn(chart_spec: dict, columns=COLUMNS, rows=ROWS, **kwargs):
    png, width, height = render_chart(chart_spec, columns, rows, **kwargs)
    image = Image.open(io.BytesIO(png))
    assert image.format == "PNG" and image.size == (width, height)
    return image


def not_blank(image: Image.Image) -> bool:
    small = image.convert("RGB").resize((90, 54)).tobytes()
    return len({small[i : i + 3] for i in range(0, len(small), 3)}) > 5


@pytest.mark.parametrize(
    "chart_spec",
    [
        spec(),
        spec(type="barh", sort="y_desc"),
        spec(y=["total", "n"], stacked=True),
        spec(type="line", x="jour"),
        spec(type="area", x="jour", y=["total", "n"], stacked=True),
        spec(type="line", x="jour", y=["total"], color="produit"),
        spec(type="pie"),
        spec(type="scatter", x="n", y=["total"]),
        spec(type="histogram", x="total", y=[]),
    ],
    ids=["bar", "barh", "stacked bar", "line by date", "stacked area", "line by color", "pie", "scatter", "histogram"],
)
def test_every_kind_of_chart_is_drawn_at_the_same_fixed_size(chart_spec) -> None:
    image = drawn(chart_spec)

    assert image.size == (900, 540) and not_blank(image)


def test_the_size_does_not_depend_on_the_data() -> None:
    many = [[f"c{i}", float(i), i, "2024-01-01", "A"] for i in range(30)]

    assert drawn(spec(), rows=many).size == drawn(spec(), rows=ROWS[:1]).size == (900, 540)


def test_dates_are_plotted_on_a_time_axis_whatever_their_order() -> None:
    shuffled = [ROWS[2], ROWS[0], ROWS[3], ROWS[1]]

    assert not_blank(drawn(spec(type="line", x="jour"), rows=shuffled))


def test_a_column_that_does_not_exist_lists_the_ones_that_do() -> None:
    with pytest.raises(ChartError) as error:
        drawn(spec(y=["chiffre"]))

    message = str(error.value)
    assert "chiffre" in message and "total (DOUBLE)" in message and "région (VARCHAR)" in message


def test_a_y_column_that_is_not_numeric_says_how_to_convert_it() -> None:
    with pytest.raises(ChartError, match="TRY_CAST"):
        drawn(spec(y=["produit"]))


def test_numbers_stored_as_text_are_accepted() -> None:
    columns = [{"name": "k", "type": "VARCHAR"}, {"name": "v", "type": "VARCHAR"}]

    assert not_blank(drawn({"type": "bar", "x": "k", "y": ["v"], "title": "t"}, columns, [["a", "1,5"], ["b", "2.5"]]))


def test_too_many_categories_ask_to_aggregate() -> None:
    rows = [[f"c{i}", 1.0, 1, "2024-01-01", "A"] for i in range(41)]

    with pytest.raises(ChartError, match="Trop de catégories"):
        drawn(spec(), rows=rows)
    assert drawn(spec(), rows=rows, limits=ChartLimits(max_categories=50)).size == (900, 540)


def test_too_many_series_ask_to_filter() -> None:
    rows = [["Nord", 1.0, 1, "2024-01-01", f"p{i}"] for i in range(13)]

    with pytest.raises(ChartError, match="Trop de séries"):
        drawn(spec(color="produit"), rows=rows)


def test_a_pie_groups_the_smallest_slices_and_refuses_negative_values() -> None:
    rows = [[f"c{i}", float(100 - i), 1, "2024-01-01", "A"] for i in range(30)]
    assert not_blank(drawn(spec(type="pie"), rows=rows))

    with pytest.raises(ChartError, match="positives"):
        drawn(spec(type="pie"), rows=[["a", -1.0, 1, "2024-01-01", "A"], ["b", 2.0, 1, "2024-01-01", "A"]])
    with pytest.raises(ChartError, match="nulles"):
        drawn(spec(type="pie"), rows=[["a", 0.0, 1, "2024-01-01", "A"]])


def test_scatter_and_histogram_need_a_numeric_axis() -> None:
    with pytest.raises(ChartError, match="axe x numérique"):
        drawn(spec(type="scatter", x="région"))
    with pytest.raises(ChartError, match="colonne numérique"):
        drawn(spec(type="histogram", x="région", y=[]))


def test_an_empty_result_has_nothing_to_draw() -> None:
    with pytest.raises(ChartError, match="vide"):
        drawn(spec(), rows=[])


def test_null_values_are_tolerated() -> None:
    rows = [["Nord", None, 1, "2024-01-01", "A"], [None, 5.0, 2, "2024-02-01", "A"], ["Est", 7.0, 3, None, "A"]]

    assert not_blank(drawn(spec(), rows=rows))
    assert not_blank(drawn(spec(type="histogram", x="total", y=[]), rows=rows))


def test_a_truncated_result_is_flagged_on_the_image() -> None:
    plain, flagged = drawn(spec()), drawn(spec(), truncated=True)

    assert plain.tobytes() != flagged.tobytes()


def test_unusual_titles_do_not_break_the_drawing() -> None:
    title = "Ventes 2024 — « chiffres » $\\alpha$ $5 et $\\foo <script>alert(1)</script> éè€"

    assert not_blank(drawn(spec(title=title)))


def test_a_dollar_in_a_label_or_a_category_is_a_dollar() -> None:
    rows = [["$10 et $20", 1.0, 1, "2024-01-01", "A"], ["$\\bad", 2.0, 2, "2024-02-01", "A"]]

    assert not_blank(drawn(spec(title="Prix en $", x_label="$x", y_label="y$"), rows=rows))
