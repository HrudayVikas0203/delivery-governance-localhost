from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.people import Employee
from app.models.tasks import TaskNotification
from app.schemas.common import TaskNotificationOut


router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[TaskNotificationOut])
def list_notifications(
    db: Session = Depends(get_db),
    actor: Employee = Depends(get_current_user),
) -> list[TaskNotification]:
    return list(db.scalars(
        select(TaskNotification)
        .where(TaskNotification.recipient_id == actor.id)
        .order_by(TaskNotification.created_at.desc())
    ).all())


@router.patch("/{notification_id}/read", response_model=TaskNotificationOut)
def set_notification_read(
    notification_id: str,
    is_read: bool = True,
    db: Session = Depends(get_db),
    actor: Employee = Depends(get_current_user),
) -> TaskNotification:
    notification = db.get(TaskNotification, notification_id)
    if notification is None or notification.recipient_id != actor.id:
        raise HTTPException(status_code=404, detail="Notification not found")
    notification.is_read = is_read
    db.commit()
    db.refresh(notification)
    return notification


@router.post("/read-all", status_code=204)
def mark_all_notifications_read(
    db: Session = Depends(get_db),
    actor: Employee = Depends(get_current_user),
) -> Response:
    db.execute(update(TaskNotification).where(TaskNotification.recipient_id == actor.id).values(is_read=True))
    db.commit()
    return Response(status_code=204)


@router.delete("", status_code=204)
def clear_notifications(
    db: Session = Depends(get_db),
    actor: Employee = Depends(get_current_user),
) -> Response:
    db.execute(delete(TaskNotification).where(TaskNotification.recipient_id == actor.id))
    db.commit()
    return Response(status_code=204)
