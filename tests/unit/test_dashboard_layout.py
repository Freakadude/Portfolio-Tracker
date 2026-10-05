import pytest

from folio.dashboards import layout as grid
from folio.dashboards.templates import TEMPLATES
from folio.dashboards.widgets import WIDGET_TYPES, WidgetError, normalize_config


def box(i: str, x: int, y: int, w: int, h: int) -> dict[str, object]:
    return {"i": i, "x": x, "y": y, "w": w, "h": h}


# --- checking a saved layout --------------------------------------------------------------------


def test_a_valid_layout_is_returned_cleaned() -> None:
    clean = grid.check({"lg": [{**box("1", 0, 0, 6, 4), "extra": "dropped"}]}, {"1"})
    assert clean == {"lg": [box("1", 0, 0, 6, 4)]}


@pytest.mark.parametrize(
    ("layouts", "message"),
    [
        ({"lg": [box("1", 8, 0, 6, 2)]}, "12-column grid"),  # 8 + 6 > 12
        ({"md": [box("1", 4, 0, 5, 2)]}, "8-column grid"),
        ({"sm": [box("1", 0, 0, 2, 2)]}, "1-column grid"),
        ({"lg": [box("9", 0, 0, 2, 2)]}, "not on this dashboard"),
        ({"lg": [box("1", 0, 0, 2, 2), box("1", 2, 0, 2, 2)]}, "placed twice"),
        ({"lg": [box("1", 0, 0, 0, 2)]}, "at least 1"),
        ({"lg": [box("1", -1, 0, 2, 2)]}, "at least 1"),
        ({"xl": [box("1", 0, 0, 2, 2)]}, "Unknown breakpoint"),
        ({"lg": [{"i": "1", "x": 0}]}, "whole numbers"),
        ({"lg": [box("1", 0, 500, 2, 2)]}, "too far down"),
    ],
)
def test_a_layout_that_cannot_be_drawn_is_refused_in_plain_words(
    layouts: dict[str, list[dict[str, object]]], message: str
) -> None:
    with pytest.raises(grid.LayoutError, match=message):
        grid.check(layouts, {"1"})


# --- tablet and phone ---------------------------------------------------------------------------


OVERVIEW = [
    box("1", 0, 0, 3, 2), box("2", 3, 0, 3, 2), box("3", 6, 0, 3, 2), box("4", 9, 0, 3, 2),
    box("5", 0, 2, 8, 5), box("6", 8, 2, 4, 5), box("7", 0, 7, 12, 6),
]  # fmt: skip


def test_the_phone_is_one_column_in_reading_order() -> None:
    sm = grid.derive(OVERVIEW)["sm"]
    assert [b["i"] for b in sm] == ["1", "2", "3", "4", "5", "6", "7"]
    assert all(b["x"] == 0 and b["w"] == 1 for b in sm)
    assert [b["y"] for b in sm] == [0, 2, 4, 6, 8, 13, 18]  # stacked, no gaps


def test_the_tablet_fits_eight_columns_and_keeps_reading_order() -> None:
    md = grid.derive(OVERVIEW)["md"]
    assert all(int(b["x"]) + int(b["w"]) <= 8 for b in md)
    first_row = [b for b in md if b["y"] == 0]
    assert [b["i"] for b in first_row] == ["1", "2", "3", "4"]  # 4 x 2 columns
    assert [(b["i"], b["w"]) for b in md if b["i"] in ("5", "6")] == [("5", 5), ("6", 3)]
    assert next(b for b in md if b["i"] == "7")["w"] == 8


def test_derived_layouts_leave_no_widget_out() -> None:
    derived = grid.derive(OVERVIEW)
    for bp in ("lg", "md", "sm"):
        assert sorted(b["i"] for b in derived[bp]) == ["1", "2", "3", "4", "5", "6", "7"]


def test_complete_adds_a_missing_widget_to_every_breakpoint() -> None:
    saved = {
        "lg": [box("1", 0, 0, 6, 4)],
        "md": [box("1", 0, 0, 8, 3)],
        "sm": [box("1", 0, 0, 1, 5)],
    }
    done = grid.complete(saved, ["1", "2"])
    for bp in ("lg", "md", "sm"):
        assert sorted(b["i"] for b in done[bp]) == ["1", "2"]
    assert done["md"][0] == box("1", 0, 0, 8, 3)  # what was arranged by hand is kept
    assert done["sm"][0] == box("1", 0, 0, 1, 5)
    new_on_phone = next(b for b in done["sm"] if b["i"] == "2")
    assert new_on_phone["y"] >= 5  # below the existing widget, not on top of it


def test_complete_drops_widgets_that_no_longer_exist() -> None:
    done = grid.complete({"lg": [box("1", 0, 0, 4, 3), box("2", 4, 0, 4, 3)]}, ["1"])
    for bp in ("lg", "md", "sm"):
        assert [b["i"] for b in done[bp]] == ["1"]


# --- widget options and templates ---------------------------------------------------------------


def test_options_are_completed_with_defaults() -> None:
    kpi = normalize_config("kpi", {})
    assert kpi["metric"] == "value" and kpi["scope"] == {"kind": "portfolio", "id": None}
    assert kpi["period"] is None and kpi["follow_filters"] is True and kpi["sparkline"] is True
    assert normalize_config("price_chart", {})["overlays"] == ["trades"]


def test_options_that_do_not_exist_are_refused() -> None:
    with pytest.raises(WidgetError, match="kpi widget has an option"):
        normalize_config("kpi", {"metric": "fun"})
    with pytest.raises(WidgetError, match="kpi widget has an option"):
        normalize_config("kpi", {"colour": "red"})
    with pytest.raises(WidgetError, match="Unknown widget type"):
        normalize_config("clock", {})


def test_every_widget_type_has_valid_defaults_and_a_sane_size() -> None:
    assert len(WIDGET_TYPES) == 18  # the v1 library of the spec
    for widget in WIDGET_TYPES.values():
        assert normalize_config(widget.key, {})
        assert 1 <= widget.width <= 12 and 1 <= widget.height <= 12


def test_the_four_templates_use_known_widgets_inside_the_grid() -> None:
    assert list(TEMPLATES) == ["overview", "risk", "income", "signals"]
    for template in TEMPLATES.values():
        for spec in template.widgets:
            normalize_config(spec.type, spec.config)
            assert spec.x + spec.w <= 12 and spec.type in WIDGET_TYPES
