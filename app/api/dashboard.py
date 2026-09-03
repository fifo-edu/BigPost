from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import ROLE_RANK, get_current_user
from app.models.models import AuditLog, Licensee, User

router = APIRouter(prefix="/api/v1", tags=["dashboard"])


@router.get("/state")
def state(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Endpoint agregado usado pelo painel administrativo (equivalente ao
    /api/state do protótipo original) para reduzir round-trips."""
    licensees = db.query(Licensee).order_by(Licensee.id.desc()).all()
    audit_rows = (
        db.query(AuditLog).order_by(AuditLog.id.desc()).limit(500).all()
        if ROLE_RANK.get(user.role, 0) >= ROLE_RANK["Supervisor"]
        else []
    )
    active = sum(1 for licensee in licensees if licensee.status == "Ativo")
    late = sum(1 for licensee in licensees if licensee.status == "Inadimplente")
    blocked = sum(1 for licensee in licensees if licensee.status == "Bloqueado")
    total_users = sum(licensee.reported_active_users or 0 for licensee in licensees)
    return {
        "user": {"username": user.username, "role": user.role},
        "metrics": {
            "licensees": len(licensees),
            "active": active,
            "late_or_blocked": late + blocked,
            "reported_active_users": total_users,
        },
        "audit": [
            {
                "created_at": row.created_at,
                "username": row.username,
                "action": row.action,
                "entity": row.entity,
                "details": row.details,
            }
            for row in audit_rows
        ],
    }
