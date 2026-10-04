from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from folio.audit import write_audit
from folio.db.models import Setting
from folio.security.secrets import MASK_PREFIX, SecretStore
from folio.settings_schema import SECTIONS, Section


def _key(section: str) -> str:
    return f"section.{section}"


def get_value(db: Session, key: str, default: Any = None) -> Any:
    row = db.scalar(select(Setting).where(Setting.key == key))
    return default if row is None else row.value


def set_value(db: Session, key: str, value: Any) -> None:
    row = db.scalar(select(Setting).where(Setting.key == key))
    if row is None:
        db.add(Setting(key=key, value=value))
    else:
        row.value = value


def load_section(db: Session, name: str) -> Section:
    """Stored non-secret values on top of defaults. Secret fields are always None here."""
    return SECTIONS[name].model_validate(get_value(db, _key(name), {}))


def view_section(db: Session, store: SecretStore, name: str) -> dict[str, Any]:
    """What the API returns: secrets replaced by their masked form (or null when unset)."""
    data = load_section(db, name).model_dump(mode="json")
    for field in SECTIONS[name].SECRETS:
        data[field] = store.masked(f"{name}.{field}")
    return data


def save_section(
    db: Session, store: SecretStore, name: str, incoming: Section, actor: str = "user"
) -> dict[str, Any]:
    """Persist a section. Secret fields: None keeps the saved value, "" clears it, anything
    else replaces it. Returns the audit diff, with secrets compared in masked form."""
    old_view = view_section(db, store, name)
    values = incoming.model_dump(mode="json")

    for field in SECTIONS[name].SECRETS:
        supplied = values.pop(field, None)
        secret_name = f"{name}.{field}"
        if supplied is None or supplied.startswith(MASK_PREFIX):
            continue  # unchanged; a client echoing back a masked value must not overwrite it
        if supplied == "":
            store.delete(secret_name)
        else:
            store.set(secret_name, supplied)
    set_value(db, _key(name), values)
    db.flush()

    new_view = view_section(db, store, name)
    diff = {
        k: {"old": old_view[k], "new": new_view[k]} for k in new_view if old_view[k] != new_view[k]
    }
    if diff:
        write_audit(db, actor, "setting", "update", entity_id=name, diff=diff)
    return diff
