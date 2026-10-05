"""Grid layouts per breakpoint (FR-DB-02, FR-DB-08).

A layout is a list of boxes `{i, x, y, w, h}` on a grid of `COLUMNS[breakpoint]` columns. The
desktop layout (`lg`) is the one the owner edits; the tablet (`md`, 8 columns) and the phone
(`sm`, one column) are derived from it until the owner arranges them by hand, and then kept as
saved, so each breakpoint can differ and survives a reload.
"""

from __future__ import annotations

from typing import Any

BREAKPOINTS = ("lg", "md", "sm")
COLUMNS = {"lg": 12, "md": 8, "sm": 1}
MAX_ROWS = 200
Box = dict[str, Any]


class LayoutError(ValueError):
    """The layout cannot be used; the message says what to fix."""


def check(layouts: dict[str, list[Box]], widget_ids: set[str]) -> dict[str, list[Box]]:
    """Validate a saved layout against the widgets of the dashboard and return it cleaned."""
    clean: dict[str, list[Box]] = {}
    for breakpoint_, boxes in layouts.items():
        if breakpoint_ not in COLUMNS:
            raise LayoutError(f"Unknown breakpoint {breakpoint_!r}. Use lg, md or sm.")
        columns = COLUMNS[breakpoint_]
        seen: set[str] = set()
        out: list[Box] = []
        for box in boxes:
            try:
                i, x, y, w, h = (
                    str(box["i"]),
                    int(box["x"]),
                    int(box["y"]),
                    int(box["w"]),
                    int(box["h"]),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise LayoutError("Every box needs i, x, y, w and h as whole numbers.") from exc
            if i not in widget_ids:
                raise LayoutError(f"The layout places widget {i}, which is not on this dashboard.")
            if i in seen:
                raise LayoutError(f"Widget {i} is placed twice in the {breakpoint_} layout.")
            if w < 1 or h < 1 or x < 0 or y < 0:
                raise LayoutError(
                    "A box needs a width and height of at least 1 and a position of 0 or more."
                )
            if x + w > columns:
                raise LayoutError(
                    f"A box leaves the {columns}-column grid of the {breakpoint_} layout."
                )
            if y + h > MAX_ROWS:
                raise LayoutError("A box is placed too far down.")
            seen.add(i)
            out.append({"i": i, "x": x, "y": y, "w": w, "h": h})
        clean[breakpoint_] = out
    return clean


def bottom(boxes: list[Box]) -> int:
    return max((int(b["y"]) + int(b["h"]) for b in boxes), default=0)


def derive(lg: list[Box]) -> dict[str, list[Box]]:
    """Tablet and phone layouts from a desktop layout: reading order is kept (top to bottom,
    left to right), widths scale to 8 columns, and the phone is one column in that order."""
    ordered = sorted(lg, key=lambda b: (int(b["y"]), int(b["x"])))
    md: list[Box] = []
    row, column, row_height = 0, 0, 0
    for box in ordered:
        w = max(1, min(8, round(int(box["w"]) * 8 / 12)))
        h = int(box["h"])
        if column + w > 8:
            row, column, row_height = row + row_height, 0, 0
        md.append({"i": box["i"], "x": column, "y": row, "w": w, "h": h})
        column += w
        row_height = max(row_height, h)
    sm: list[Box] = []
    y = 0
    for box in ordered:
        h = int(box["h"])
        sm.append({"i": box["i"], "x": 0, "y": y, "w": 1, "h": h})
        y += h
    return {"lg": [dict(b) for b in ordered], "md": md, "sm": sm}


def complete(layouts: dict[str, list[Box]], widget_ids: list[str]) -> dict[str, list[Box]]:
    """Every breakpoint holds every widget: missing ones are derived from the desktop layout,
    so a widget added on one breakpoint never disappears on another."""
    lg = [b for b in layouts.get("lg", []) if b["i"] in widget_ids]
    placed = {b["i"] for b in lg}
    for widget_id in widget_ids:
        if widget_id not in placed:
            lg = [*lg, {"i": widget_id, "x": 0, "y": bottom(lg), "w": 4, "h": 3}]
    derived = derive(lg)
    out = {"lg": lg}
    for breakpoint_ in ("md", "sm"):
        boxes = [b for b in layouts.get(breakpoint_, []) if b["i"] in widget_ids]
        have = {b["i"] for b in boxes}
        for box in derived[breakpoint_]:
            if box["i"] not in have:
                boxes.append({**box, "y": max(bottom(boxes), int(box["y"]))})
        out[breakpoint_] = boxes
    return out
