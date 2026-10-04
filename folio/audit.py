from typing import Any

from sqlalchemy.orm import Session

from folio.db.models import AuditLog


def write_audit(
    db: Session,
    actor: str,
    entity: str,
    action: str,
    entity_id: str | int | None = None,
    diff: dict[str, Any] | None = None,
) -> None:
    """Append-only audit trail (FR-SY-08). There is deliberately no update or delete helper."""
    db.add(
        AuditLog(
            actor=actor,
            entity=entity,
            entity_id=None if entity_id is None else str(entity_id),
            action=action,
            diff=diff,
        )
    )
