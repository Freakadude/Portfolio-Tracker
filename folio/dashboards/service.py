"""Dashboards and their widgets: create, rename, duplicate, delete, reorder, default, layouts,
export and import (FR-DB-01, FR-DB-02, FR-DB-07)."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from folio.audit import write_audit
from folio.dashboards import layout as grid
from folio.dashboards.templates import TEMPLATES
from folio.dashboards.widgets import WIDGET_TYPES, WidgetError, normalize_config
from folio.db.base import utcnow
from folio.db.models_analytics import Dashboard, Widget

DOCUMENT_FORMAT = "folio-dashboard"
DOCUMENT_VERSION = 1
MAX_WIDGETS = 40
MAX_DASHBOARDS = 50


class DashboardError(ValueError):
    """Something the owner can fix; the message is written for them."""


@dataclass
class DashboardView:
    dashboard: Dashboard
    widgets: list[Widget]


def _live(db: Session) -> list[Dashboard]:
    return list(
        db.scalars(
            select(Dashboard)
            .where(Dashboard.deleted_at.is_(None))
            .order_by(Dashboard.sort_order, Dashboard.id)
        )
    )


def list_dashboards(db: Session) -> list[Dashboard]:
    return _live(db)


def get_dashboard(db: Session, dashboard_id: int) -> Dashboard:
    found = db.get(Dashboard, dashboard_id)
    if found is None or found.deleted_at is not None:
        raise DashboardError("That dashboard does not exist.")
    return found


def widgets_of(db: Session, dashboard_id: int) -> list[Widget]:
    return list(
        db.scalars(select(Widget).where(Widget.dashboard_id == dashboard_id).order_by(Widget.id))
    )


def view(db: Session, dashboard_id: int) -> DashboardView:
    dashboard = get_dashboard(db, dashboard_id)
    return DashboardView(dashboard, widgets_of(db, dashboard.id))


def _unique_name(db: Session, wanted: str, ignore: int | None = None) -> str:
    taken = {d.name.lower() for d in _live(db) if d.id != ignore}
    name, n = wanted, 1
    while name.lower() in taken:
        n += 1
        name = f"{wanted} {n}"
    return name


def _check_name(name: str) -> str:
    name = name.strip()
    if not name:
        raise DashboardError("Give the dashboard a name.")
    if len(name) > 100:
        raise DashboardError("A dashboard name can have at most 100 characters.")
    return name


def _store_layouts(db: Session, dashboard: Dashboard, widgets: list[Widget]) -> None:
    ids = [str(w.id) for w in widgets]
    dashboard.layouts = grid.complete(dashboard.layouts or {}, ids)
    by_id = {b["i"]: b for b in dashboard.layouts["lg"]}
    for widget in widgets:
        box = by_id.get(str(widget.id))
        if box is not None:
            widget.grid = {k: box[k] for k in ("x", "y", "w", "h")}
    db.flush()


def _add_widget(
    db: Session, dashboard: Dashboard, kind: str, config: dict[str, Any], box: dict[str, int]
) -> Widget:
    widget = Widget(dashboard_id=dashboard.id, type=kind, config=config, grid=dict(box))
    db.add(widget)
    db.flush()
    return widget


def create_dashboard(
    db: Session, name: str, template: str | None = None, actor: str = "user"
) -> Dashboard:
    if len(_live(db)) >= MAX_DASHBOARDS:
        raise DashboardError(f"You can have at most {MAX_DASHBOARDS} dashboards.")
    tpl = None
    if template is not None:
        tpl = TEMPLATES.get(template)
        if tpl is None:
            raise DashboardError(
                f"There is no template {template!r}. Use one of: {', '.join(TEMPLATES)}."
            )
    live = _live(db)
    dashboard = Dashboard(
        name=_unique_name(db, _check_name(name)),
        layouts={},
        filters={"period": "YTD", "account": None},
        is_default=not live,
        sort_order=(max((d.sort_order for d in live), default=0) + 1),
    )
    db.add(dashboard)
    db.flush()
    widgets: list[Widget] = []
    if tpl is not None:
        lg = []
        for spec in tpl.widgets:
            widget = _add_widget(
                db,
                dashboard,
                spec.type,
                normalize_config(spec.type, spec.config),
                {"x": spec.x, "y": spec.y, "w": spec.w, "h": spec.h},
            )
            widgets.append(widget)
            lg.append({"i": str(widget.id), "x": spec.x, "y": spec.y, "w": spec.w, "h": spec.h})
        dashboard.layouts = grid.derive(lg)
    _store_layouts(db, dashboard, widgets)
    write_audit(
        db, actor, "dashboard", "create", entity_id=dashboard.id,
        diff={"name": dashboard.name, "template": template},
    )  # fmt: skip
    return dashboard


def update_dashboard(
    db: Session, dashboard: Dashboard, name: str | None, filters: dict[str, Any] | None
) -> Dashboard:
    if name is not None:
        new = _unique_name(db, _check_name(name), ignore=dashboard.id)
        if new != dashboard.name:
            write_audit(
                db, "user", "dashboard", "rename", entity_id=dashboard.id,
                diff={"name": {"old": dashboard.name, "new": new}},
            )  # fmt: skip
            dashboard.name = new
    if filters is not None:
        dashboard.filters = {**(dashboard.filters or {}), **filters}
    db.flush()
    return dashboard


def delete_dashboard(db: Session, dashboard: Dashboard) -> None:
    was_default = dashboard.is_default
    dashboard.deleted_at = utcnow()
    dashboard.is_default = False
    write_audit(
        db, "user", "dashboard", "delete", entity_id=dashboard.id, diff={"name": dashboard.name}
    )
    db.flush()
    remaining = _live(db)
    if was_default and remaining:
        remaining[0].is_default = True


def set_default(db: Session, dashboard: Dashboard) -> None:
    for other in _live(db):
        other.is_default = other.id == dashboard.id
    db.flush()


def reorder(db: Session, ids: list[int]) -> list[Dashboard]:
    live = {d.id: d for d in _live(db)}
    if sorted(ids) != sorted(live):
        raise DashboardError("List every dashboard exactly once.")
    for position, dashboard_id in enumerate(ids, start=1):
        live[dashboard_id].sort_order = position
    db.flush()
    return [live[i] for i in ids]


def duplicate(db: Session, source: Dashboard) -> Dashboard:
    widgets = widgets_of(db, source.id)
    copy_ = create_dashboard(db, f"{source.name} (copy)")
    mapping: dict[str, str] = {}
    for widget in widgets:
        clone = _add_widget(
            db, copy_, widget.type, copy.deepcopy(widget.config), dict(widget.grid or {})
        )
        mapping[str(widget.id)] = str(clone.id)
    layouts = {
        bp: [{**box, "i": mapping[box["i"]]} for box in boxes if box["i"] in mapping]
        for bp, boxes in (source.layouts or {}).items()
    }
    copy_.layouts = layouts
    copy_.filters = copy.deepcopy(source.filters or {})
    _store_layouts(db, copy_, widgets_of(db, copy_.id))
    return copy_


def save_layout(db: Session, dashboard: Dashboard, layouts: dict[str, list[grid.Box]]) -> Dashboard:
    widgets = widgets_of(db, dashboard.id)
    try:
        clean = grid.check(layouts, {str(w.id) for w in widgets})
    except grid.LayoutError as exc:
        raise DashboardError(str(exc)) from exc
    merged = {**(dashboard.layouts or {}), **clean}
    dashboard.layouts = merged
    _store_layouts(db, dashboard, widgets)
    return dashboard


def add_widget(
    db: Session,
    dashboard: Dashboard,
    kind: str,
    config: dict[str, Any] | None,
    box: dict[str, int] | None = None,
) -> Widget:
    widgets = widgets_of(db, dashboard.id)
    if len(widgets) >= MAX_WIDGETS:
        raise DashboardError(f"A dashboard can hold at most {MAX_WIDGETS} widgets.")
    try:
        clean = normalize_config(kind, config)
    except WidgetError as exc:
        raise DashboardError(str(exc)) from exc
    spec = WIDGET_TYPES[kind]
    lg = (dashboard.layouts or {}).get("lg", [])
    placed = box or {"x": 0, "y": grid.bottom(lg), "w": spec.width, "h": spec.height}
    widget = _add_widget(db, dashboard, kind, clean, placed)
    layouts = copy.deepcopy(dashboard.layouts or {})
    layouts["lg"] = [*layouts.get("lg", []), {"i": str(widget.id), **placed}]
    dashboard.layouts = layouts
    _store_layouts(db, dashboard, [*widgets, widget])
    return widget


def get_widget(db: Session, dashboard: Dashboard, widget_id: int) -> Widget:
    widget = db.get(Widget, widget_id)
    if widget is None or widget.dashboard_id != dashboard.id:
        raise DashboardError("That widget is not on this dashboard.")
    return widget


def update_widget(
    db: Session, dashboard: Dashboard, widget: Widget, config: dict[str, Any]
) -> Widget:
    try:
        widget.config = normalize_config(widget.type, config)
    except WidgetError as exc:
        raise DashboardError(str(exc)) from exc
    dashboard.updated_at = utcnow()
    db.flush()
    return widget


def remove_widget(db: Session, dashboard: Dashboard, widget: Widget) -> None:
    wid = str(widget.id)
    db.delete(widget)
    dashboard.layouts = {
        bp: [b for b in boxes if b["i"] != wid] for bp, boxes in (dashboard.layouts or {}).items()
    }
    db.flush()


# --- export and import --------------------------------------------------------------------------


def export_document(db: Session, dashboard: Dashboard) -> dict[str, Any]:
    """A dashboard as JSON. Widgets are listed in order and the layouts refer to them by their
    position in that list, so the file means the same thing in any installation."""
    widgets = widgets_of(db, dashboard.id)
    index = {str(w.id): n for n, w in enumerate(widgets)}
    return {
        "format": DOCUMENT_FORMAT,
        "version": DOCUMENT_VERSION,
        "name": dashboard.name,
        "filters": dict(dashboard.filters or {}),
        "widgets": [{"type": w.type, "config": w.config} for w in widgets],
        "layouts": {
            bp: [{**b, "i": index[b["i"]]} for b in boxes if b["i"] in index]
            for bp, boxes in (dashboard.layouts or {}).items()
        },
    }


def import_document(db: Session, document: dict[str, Any], actor: str = "user") -> Dashboard:
    if document.get("format") != DOCUMENT_FORMAT:
        raise DashboardError("This file is not a Folio dashboard export.")
    if document.get("version") != DOCUMENT_VERSION:
        raise DashboardError(
            f"This dashboard was exported with format version {document.get('version')}; this "
            f"Folio reads version {DOCUMENT_VERSION}."
        )
    items = document.get("widgets")
    if not isinstance(items, list) or len(items) > MAX_WIDGETS:
        raise DashboardError(f"A dashboard needs a list of at most {MAX_WIDGETS} widgets.")
    cleaned: list[tuple[str, dict[str, Any]]] = []
    for n, item in enumerate(items, start=1):
        if not isinstance(item, dict) or not isinstance(item.get("type"), str):
            raise DashboardError(f"Widget {n} has no type.")
        try:
            cleaned.append((item["type"], normalize_config(item["type"], item.get("config"))))
        except WidgetError as exc:
            raise DashboardError(f"Widget {n}: {exc}") from exc
    name = document.get("name")
    dashboard = create_dashboard(
        db, name if isinstance(name, str) and name.strip() else "Imported", actor=actor
    )
    created = [_add_widget(db, dashboard, kind, config, {}) for kind, config in cleaned]
    ids = [str(w.id) for w in created]
    layouts: dict[str, list[grid.Box]] = {}
    for bp, boxes in (document.get("layouts") or {}).items():
        mapped: list[grid.Box] = []
        for box in boxes if isinstance(boxes, list) else []:
            try:
                position = int(box["i"])
            except (KeyError, TypeError, ValueError):
                continue
            if 0 <= position < len(ids):
                mapped.append({**box, "i": ids[position]})
        layouts[bp] = mapped
    try:
        dashboard.layouts = grid.check(layouts, set(ids)) if layouts else {}
    except grid.LayoutError as exc:
        raise DashboardError(f"The layout in this file cannot be used: {exc}") from exc
    filters = document.get("filters")
    if isinstance(filters, dict):
        dashboard.filters = {
            k: v for k, v in filters.items() if k in ("period", "account", "start", "end")
        }
    _store_layouts(db, dashboard, created)
    return dashboard


def ensure_default(db: Session) -> Dashboard:
    """The default dashboard, creating the Overview template on the very first visit."""
    live = _live(db)
    if not live:
        return create_dashboard(db, "Overview", template="overview", actor="user")
    for dashboard in live:
        if dashboard.is_default:
            return dashboard
    live[0].is_default = True
    db.flush()
    return live[0]


def widget_counts(db: Session) -> dict[int, int]:
    rows = db.execute(select(Widget.dashboard_id, func.count()).group_by(Widget.dashboard_id))
    return {dashboard_id: count for dashboard_id, count in rows}
