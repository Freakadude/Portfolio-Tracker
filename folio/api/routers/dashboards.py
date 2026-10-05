"""Dashboards, widgets, templates and the batched widget data (FR-DB-01 to FR-DB-08)."""

from datetime import date
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from folio.api.deps import DbDep, UserDep
from folio.api.errors import ApiError
from folio.dashboards import service
from folio.dashboards.data import Env, Filters, WidgetDataError, compute
from folio.dashboards.service import DashboardError
from folio.dashboards.templates import TEMPLATES
from folio.dashboards.widgets import WIDGET_TYPES, WidgetError, normalize_config
from folio.db.models_analytics import Dashboard, Widget

router = APIRouter(tags=["dashboards"])


class WidgetOut(BaseModel):
    id: int
    type: str
    config: dict[str, Any]
    grid: dict[str, int]


class DashboardOut(BaseModel):
    id: int
    name: str
    is_default: bool
    sort_order: int
    filters: dict[str, Any]
    layouts: dict[str, list[dict[str, Any]]]
    widgets: list[WidgetOut]


class DashboardSummary(BaseModel):
    id: int
    name: str
    is_default: bool
    sort_order: int
    widget_count: int


class DashboardIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    template: str | None = None


class DashboardChanges(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    filters: dict[str, Any] | None = None


class OrderIn(BaseModel):
    ids: list[int]


class LayoutIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    layouts: dict[str, list[dict[str, Any]]]


class WidgetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    config: dict[str, Any] = Field(default_factory=dict)
    grid: dict[str, int] | None = None


class WidgetChanges(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config: dict[str, Any]


class ImportIn(BaseModel):
    document: dict[str, Any]


def _fail(exc: DashboardError) -> ApiError:
    text = str(exc)
    status = 404 if "does not exist" in text or text.startswith("That widget is not") else 422
    return ApiError(status, "Not found" if status == 404 else "Invalid dashboard", str(exc))


def _widget_out(widget: Widget) -> WidgetOut:
    return WidgetOut(
        id=widget.id,
        type=widget.type,
        config=dict(widget.config or {}),
        grid={k: int(v) for k, v in (widget.grid or {}).items()},
    )


def _full(db: Session, dashboard: Dashboard) -> DashboardOut:
    widgets = service.widgets_of(db, dashboard.id)
    return DashboardOut(
        id=dashboard.id,
        name=dashboard.name,
        is_default=dashboard.is_default,
        sort_order=dashboard.sort_order,
        filters=dict(dashboard.filters or {}),
        layouts=dict(dashboard.layouts or {}),
        widgets=[_widget_out(w) for w in widgets],
    )


def _load(db: Session, dashboard_id: int) -> Dashboard:
    try:
        return service.get_dashboard(db, dashboard_id)
    except DashboardError as exc:
        raise _fail(exc) from exc


# --- the dashboards -----------------------------------------------------------------------------


@router.get("/dashboards", response_model=list[DashboardSummary])
def list_dashboards(_user: UserDep, db: DbDep) -> list[DashboardSummary]:
    counts = service.widget_counts(db)
    return [
        DashboardSummary(
            id=d.id,
            name=d.name,
            is_default=d.is_default,
            sort_order=d.sort_order,
            widget_count=counts.get(d.id, 0),
        )
        for d in service.list_dashboards(db)
    ]


@router.get("/dashboards/default", response_model=DashboardOut)
def default_dashboard(_user: UserDep, db: DbDep) -> DashboardOut:
    """The dashboard Home opens. The very first visit creates the Overview template."""
    return _full(db, service.ensure_default(db))


@router.post("/dashboards", response_model=DashboardOut, status_code=201)
def create_dashboard(body: DashboardIn, _user: UserDep, db: DbDep) -> DashboardOut:
    try:
        return _full(db, service.create_dashboard(db, body.name, body.template))
    except DashboardError as exc:
        raise _fail(exc) from exc


@router.put("/dashboards/order", response_model=list[DashboardSummary])
def reorder(body: OrderIn, _user: UserDep, db: DbDep) -> list[DashboardSummary]:
    try:
        ordered = service.reorder(db, body.ids)
    except DashboardError as exc:
        raise _fail(exc) from exc
    counts = service.widget_counts(db)
    return [
        DashboardSummary(
            id=d.id,
            name=d.name,
            is_default=d.is_default,
            sort_order=d.sort_order,
            widget_count=counts.get(d.id, 0),
        )
        for d in ordered
    ]


@router.post("/dashboards/import", response_model=DashboardOut, status_code=201)
def import_dashboard(body: ImportIn, _user: UserDep, db: DbDep) -> DashboardOut:
    try:
        return _full(db, service.import_document(db, body.document))
    except DashboardError as exc:
        raise _fail(exc) from exc


@router.get("/dashboards/{dashboard_id}", response_model=DashboardOut)
def read_dashboard(dashboard_id: int, _user: UserDep, db: DbDep) -> DashboardOut:
    return _full(db, _load(db, dashboard_id))


@router.patch("/dashboards/{dashboard_id}", response_model=DashboardOut)
def update_dashboard(
    dashboard_id: int, body: DashboardChanges, _user: UserDep, db: DbDep
) -> DashboardOut:
    dashboard = _load(db, dashboard_id)
    try:
        service.update_dashboard(db, dashboard, body.name, body.filters)
    except DashboardError as exc:
        raise _fail(exc) from exc
    return _full(db, dashboard)


@router.delete("/dashboards/{dashboard_id}", status_code=204)
def delete_dashboard(dashboard_id: int, _user: UserDep, db: DbDep) -> None:
    service.delete_dashboard(db, _load(db, dashboard_id))


@router.post("/dashboards/{dashboard_id}/duplicate", response_model=DashboardOut, status_code=201)
def duplicate_dashboard(dashboard_id: int, _user: UserDep, db: DbDep) -> DashboardOut:
    return _full(db, service.duplicate(db, _load(db, dashboard_id)))


@router.post("/dashboards/{dashboard_id}/default", response_model=DashboardOut)
def make_default(dashboard_id: int, _user: UserDep, db: DbDep) -> DashboardOut:
    dashboard = _load(db, dashboard_id)
    service.set_default(db, dashboard)
    return _full(db, dashboard)


@router.put("/dashboards/{dashboard_id}/layout", response_model=DashboardOut)
def save_layout(dashboard_id: int, body: LayoutIn, _user: UserDep, db: DbDep) -> DashboardOut:
    """Save the arrangement of widgets; each breakpoint (lg, md, sm) is kept as sent."""
    dashboard = _load(db, dashboard_id)
    try:
        service.save_layout(db, dashboard, body.layouts)
    except DashboardError as exc:
        raise _fail(exc) from exc
    return _full(db, dashboard)


@router.get("/dashboards/{dashboard_id}/export")
def export_dashboard(dashboard_id: int, _user: UserDep, db: DbDep) -> dict[str, Any]:
    return service.export_document(db, _load(db, dashboard_id))


# --- widgets ------------------------------------------------------------------------------------


@router.post("/dashboards/{dashboard_id}/widgets", response_model=DashboardOut, status_code=201)
def add_widget(dashboard_id: int, body: WidgetIn, _user: UserDep, db: DbDep) -> DashboardOut:
    dashboard = _load(db, dashboard_id)
    try:
        service.add_widget(db, dashboard, body.type, body.config, body.grid)
    except DashboardError as exc:
        raise _fail(exc) from exc
    return _full(db, dashboard)


@router.patch("/dashboards/{dashboard_id}/widgets/{widget_id}", response_model=DashboardOut)
def update_widget(
    dashboard_id: int, widget_id: int, body: WidgetChanges, _user: UserDep, db: DbDep
) -> DashboardOut:
    dashboard = _load(db, dashboard_id)
    try:
        widget = service.get_widget(db, dashboard, widget_id)
        service.update_widget(db, dashboard, widget, body.config)
    except DashboardError as exc:
        raise _fail(exc) from exc
    return _full(db, dashboard)


@router.delete("/dashboards/{dashboard_id}/widgets/{widget_id}", response_model=DashboardOut)
def remove_widget(dashboard_id: int, widget_id: int, _user: UserDep, db: DbDep) -> DashboardOut:
    dashboard = _load(db, dashboard_id)
    try:
        service.remove_widget(db, dashboard, service.get_widget(db, dashboard, widget_id))
    except DashboardError as exc:
        raise _fail(exc) from exc
    return _full(db, dashboard)


# --- the library and the templates --------------------------------------------------------------


class LibraryEntry(BaseModel):
    type: str
    title_key: str
    width: int
    height: int
    defaults: dict[str, Any]


class TemplateOut(BaseModel):
    key: str
    name: str
    description: str
    widget_count: int


@router.get("/dashboard-widgets", response_model=list[LibraryEntry])
def widget_library(_user: UserDep) -> list[LibraryEntry]:
    return [
        LibraryEntry(
            type=w.key,
            title_key=w.title_key,
            width=w.width,
            height=w.height,
            defaults=normalize_config(w.key, {}),
        )
        for w in WIDGET_TYPES.values()
    ]


@router.get("/dashboard-templates", response_model=list[TemplateOut])
def templates(_user: UserDep) -> list[TemplateOut]:
    return [
        TemplateOut(key=t.key, name=t.name, description=t.description, widget_count=len(t.widgets))
        for t in TEMPLATES.values()
    ]


# --- batched widget data ------------------------------------------------------------------------


class FiltersIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    period: str | None = None  # 1D ... MAX, or CUSTOM with start and end
    account: int | None = None
    start: date | None = None
    end: date | None = None


class WidgetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(max_length=60)
    type: str
    config: dict[str, Any] = Field(default_factory=dict)


class WidgetsDataIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requests: list[WidgetRequest] = Field(min_length=1, max_length=60)
    filters: FiltersIn = Field(default_factory=FiltersIn)
    as_of: date | None = None


class WidgetResult(BaseModel):
    data: dict[str, Any] | None = None
    error: str | None = None


class WidgetsDataOut(BaseModel):
    results: dict[str, WidgetResult]


@router.post("/widgets/data", response_model=WidgetsDataOut)
def widgets_data(body: WidgetsDataIn, _user: UserDep, db: DbDep) -> WidgetsDataOut:
    """The data of many widgets in one request, so a dashboard shares one analytics context.
    A widget that cannot be drawn reports its own error without failing the others."""
    f = body.filters
    env = Env(db, body.as_of or date.today(), Filters(f.period, f.account, f.start, f.end))
    results: dict[str, WidgetResult] = {}
    for request in body.requests:
        try:
            config = normalize_config(request.type, request.config)
            results[request.key] = WidgetResult(data=compute(env, request.type, config))
        except (WidgetError, WidgetDataError, ValueError) as exc:
            results[request.key] = WidgetResult(error=str(exc))
    return WidgetsDataOut(results=results)
