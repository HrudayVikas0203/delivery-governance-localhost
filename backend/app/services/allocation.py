from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.delivery import Account, Project, ResourceAllocation
from app.models.people import Availability, Employee, Role
from app.schemas.common import AllocationCreate
from app.services.audit import audit
from app.services.access import require_project_manager


def ensure_allocation_authority(db: Session, actor: Employee, project: Project) -> None:
    require_project_manager(actor, project, db.get(Account, project.account_id))


def create_allocation(db: Session, payload: AllocationCreate, actor: Employee) -> ResourceAllocation:
    project = db.get(Project, payload.project_id)
    employee = db.get(Employee, payload.employee_id)
    if project is None or employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project or employee not found")
    ensure_allocation_authority(db, actor, project)
    if not employee.is_active:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Inactive employees cannot be allocated")
    if payload.end_date and payload.end_date < payload.start_date:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Allocation end date cannot precede start date")
    if payload.reporting_manager_id:
        manager = db.get(Employee, payload.reporting_manager_id)
        if manager is None or manager.role not in {Role.PROJECT_MANAGER, Role.PROGRAM_MANAGER, Role.PROGRAM_DIRECTOR, Role.DELIVERY_HEAD, Role.STUDIO_HEAD}:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Reporting manager is invalid")

    existing = db.scalar(
        select(ResourceAllocation).where(
            ResourceAllocation.project_id == payload.project_id,
            ResourceAllocation.employee_id == payload.employee_id,
        )
    )
    if existing:
        data = payload.model_dump()
        for key, value in data.items():
            setattr(existing, key, value)
        existing.is_active = True
        employee.availability = Availability.ALLOCATED
        audit(db, actor.id, "Resource Allocation Updated", "Allocation", f"{employee.name} allocation updated for {project.name}")
        db.commit()
        db.refresh(existing)
        return existing

    allocation = ResourceAllocation(**payload.model_dump(), created_by_id=actor.id)
    employee.availability = Availability.ALLOCATED
    db.add(allocation)
    audit(db, actor.id, "Resource Allocated", "Allocation", f"{employee.name} allocated to {project.name}")
    try:
        db.commit()
        db.refresh(allocation)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Employee is already allocated to this project")
    return allocation
