from sqlalchemy.orm import Session

from app.models.models import AuditLog


def log_action(
    db: Session,
    *,
    username: str | None,
    role: str | None,
    action: str,
    entity: str | None = None,
    result: str = "OK",
    before: dict | None = None,
    after: dict | None = None,
    origin: str = "Manual",
    details: dict | None = None,
    ip_address: str | None = None,
) -> None:
    db.add(
        AuditLog(
            username=username,
            role=role,
            action=action,
            entity=entity,
            result=result,
            before=before,
            after=after,
            origin=origin,
            details=details or {},
            ip_address=ip_address,
        )
    )
    db.commit()
