from typing import Annotated, Any

from fastapi import APIRouter, Body
from pydantic import ValidationError

from folio.api.deps import DbDep, StoreDep, UserDep
from folio.api.errors import ApiError
from folio.settings_schema import SECTIONS
from folio.settings_store import save_section, view_section

router = APIRouter(prefix="/settings", tags=["settings"])


def _check(section: str) -> None:
    if section not in SECTIONS:
        raise ApiError(404, "Unknown settings section", f"Sections: {', '.join(SECTIONS)}.")


@router.get("/{section}")
def get_section(section: str, _user: UserDep, db: DbDep, store: StoreDep) -> dict[str, Any]:
    _check(section)
    return view_section(db, store, section)


@router.put("/{section}")
def put_section(
    section: str,
    body: Annotated[dict[str, Any], Body()],
    _user: UserDep,
    db: DbDep,
    store: StoreDep,
) -> dict[str, Any]:
    _check(section)
    try:
        incoming = SECTIONS[section].model_validate(body)
    except ValidationError as exc:
        errors = [
            {"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]}
            for e in exc.errors(include_url=False, include_context=False, include_input=False)
        ]
        raise ApiError(
            422, "Invalid settings", "Some values are missing or invalid.", errors=errors
        ) from exc
    save_section(db, store, section, incoming)
    return view_section(db, store, section)
