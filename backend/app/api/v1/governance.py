from datetime import datetime, timezone
import logging
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import get_current_user, require_min_role, require_roles
from app.db.session import get_db
from app.models.delivery import Account, Project, ResourceAllocation
from app.models.people import Employee, Role
from app.models.status import ReportTemplate, WeeklyStatus
from app.rag.store import index_statuses
from app.schemas.common import AccountCreate, AccountUpdate, AccountOut, AllocationCreate, AllocationOut, ProjectCreate, ProjectUpdate, ProjectOut, WeeklyStatusCreate, WeeklyStatusOut, WeeklyStatusUpdate
from app.services.allocation import create_allocation
from app.services.audit import audit
from app.services.access import (
    MANAGER_ROLES,
    PROGRAM_ROLES,
    STUDIO_HEAD_ROLES,
    can_manage_project,
    is_studio_head,
    require_account_access,
    require_account_manager,
    require_project_access,
    require_project_manager,
    validate_account_program_manager,
    validate_project_manager,
    visible_account_ids,
    visible_project_ids,
)
from app.services.template_storage import (
    TemplateUploadError,
    find_account_template,
    remove_account_templates,
    store_account_template,
    validate_pptx_upload,
)

router = APIRouter(prefix="/governance", tags=["governance"])
logger = logging.getLogger(__name__)


def _index_status_safely(db: Session, weekly_status: WeeklyStatus) -> None:
    try:
        index_statuses(db, [weekly_status])
    except Exception as exc:
        logger.warning("RAG_STATUS_INDEX_FAILED status_id=%s exception_type=%s", weekly_status.id, type(exc).__name__)


def _account_template(db: Session, account_id: str) -> ReportTemplate | None:
    return find_account_template(db, account_id)


def _status_for_reporting_period(
    db: Session,
    employee_id: str,
    project_id: str | None,
    week_start,
    frequency: str,
) -> WeeklyStatus | None:
    statement = select(WeeklyStatus).where(
        WeeklyStatus.employee_id == employee_id,
        WeeklyStatus.week_start == week_start,
    )
    if project_id is None:
        statement = statement.where(WeeklyStatus.project_id.is_(None))
    else:
        statement = statement.where(WeeklyStatus.project_id == project_id)
    expected = frequency.lower()
    return next(
        (
            row for row in db.scalars(statement).all()
            if str(row.fields.get("reportingFrequency") or row.fields.get("frequency") or "Weekly").lower() == expected
        ),
        None,
    )


def _account_response(db: Session, account: Account) -> Account:
    template = _account_template(db, account.id)
    setattr(account, "ppt_template_id", template.id if template else None)
    setattr(account, "ppt_template_filename", template.filename or template.name if template else None)
    setattr(account, "ppt_template_status", "configured" if template else "not_configured")
    return account


def _validated_uploaded_template(file: UploadFile):
    max_bytes = get_settings().ppt_template_max_bytes
    content = file.file.read(max_bytes + 1)
    return validate_pptx_upload(file.filename, file.content_type, content)


@router.get("/employees", response_model=list[dict])
def list_employees(db: Session = Depends(get_db), actor: Employee = Depends(get_current_user)) -> list[dict]:
    if is_studio_head(actor):
        rows = db.scalars(select(Employee).order_by(Employee.name)).all()
    else:
        project_ids = visible_project_ids(db, actor)
        employee_ids = {actor.id}
        if project_ids:
            projects = db.scalars(select(Project).where(Project.id.in_(project_ids))).all()
            for project in projects:
                employee_ids.update(filter(None, [project.program_manager_id, project.project_manager_id, project.team_lead_id]))
            employee_ids.update(
                db.scalars(
                    select(ResourceAllocation.employee_id).where(
                        ResourceAllocation.project_id.in_(project_ids),
                        ResourceAllocation.is_active.is_(True),
                    )
                ).all()
            )
        rows = db.scalars(select(Employee).where(Employee.id.in_(employee_ids)).order_by(Employee.name)).all()
    return [
        {
            "id": row.id,
            "name": row.name,
            "email": row.email,
            "title": row.title,
            "role": row.role.value,
            "department": row.department,
            "location": row.location,
            "manager_id": row.manager_id,
            "availability": row.availability.value,
            "skills": row.skills.split(",") if row.skills else [],
            "is_active": row.is_active,
        }
        for row in rows
    ]


@router.post("/accounts", response_model=AccountOut, status_code=201)
def create_account(payload: AccountCreate, db: Session = Depends(get_db), actor: Employee = Depends(require_roles(*STUDIO_HEAD_ROLES))) -> Account:
    validate_account_program_manager(db, payload.program_manager_id)
    account = Account(**payload.model_dump(exclude={"delivery_head_id"}), delivery_head_id=actor.id)
    db.add(account)
    audit(db, actor.id, "Account Created", "Accounts", f"Account {account.name} created")
    db.commit()
    db.refresh(account)
    return _account_response(db, account)


@router.post("/accounts/with-template", response_model=AccountOut, status_code=201)
def create_account_with_template(
    account_data: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    actor: Employee = Depends(require_roles(*STUDIO_HEAD_ROLES)),
) -> Account:
    try:
        payload = AccountCreate.model_validate_json(account_data)
        validated = _validated_uploaded_template(file)
        validate_account_program_manager(db, payload.program_manager_id)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Account details are invalid") from exc
    except TemplateUploadError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    try:
        account = Account(**payload.model_dump(exclude={"delivery_head_id"}), delivery_head_id=actor.id)
        db.add(account)
        db.flush()
        store_account_template(db, account.id, validated, actor.id)
        audit(db, actor.id, "Account Created", "Accounts", f"Account {account.name} created with PPT template")
        db.commit()
        db.refresh(account)
        return _account_response(db, account)
    except Exception:
        db.rollback()
        raise


@router.get("/accounts", response_model=list[AccountOut])
def list_accounts(db: Session = Depends(get_db), actor: Employee = Depends(get_current_user)) -> list[Account]:
    ids = visible_account_ids(db, actor)
    if not ids:
        return []
    return [_account_response(db, account) for account in db.scalars(select(Account).where(Account.id.in_(ids)).order_by(Account.name)).all()]


@router.get("/accounts/{account_id}", response_model=AccountOut)
def get_account(account_id: str, db: Session = Depends(get_db), actor: Employee = Depends(get_current_user)) -> Account:
    account = require_account_access(db, actor, db.get(Account, account_id))
    return _account_response(db, account)


@router.put("/accounts/{account_id}", response_model=AccountOut)
def update_account(account_id: str, payload: AccountUpdate, db: Session = Depends(get_db), actor: Employee = Depends(get_current_user)) -> Account:
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    require_account_manager(actor, account)
    if "program_manager_id" in payload.model_fields_set:
        if not is_studio_head(actor):
            raise HTTPException(status_code=403, detail="Only Studio Head can assign an account manager")
        validate_account_program_manager(db, payload.program_manager_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(account, key, value)
    audit(db, actor.id, "Account Updated", "Accounts", f"Account {account.name} updated")
    db.commit()
    db.refresh(account)
    return _account_response(db, account)


@router.put("/accounts/{account_id}/with-template", response_model=AccountOut)
def update_account_with_template(
    account_id: str,
    account_data: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    actor: Employee = Depends(require_roles(*STUDIO_HEAD_ROLES)),
) -> Account:
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    try:
        payload = AccountUpdate.model_validate_json(account_data)
        validated = _validated_uploaded_template(file)
        validate_account_program_manager(db, payload.program_manager_id)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Account details are invalid") from exc
    except TemplateUploadError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    try:
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(account, key, value)
        store_account_template(db, account_id, validated, actor.id)
        audit(db, actor.id, "Account Updated", "Accounts", f"Account {account.name} and PPT template updated")
        db.commit()
        db.refresh(account)
        return _account_response(db, account)
    except Exception:
        db.rollback()
        raise


@router.post("/accounts/{account_id}/template", response_model=dict, status_code=201)
def upload_account_template(
    account_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    actor: Employee = Depends(require_roles(*STUDIO_HEAD_ROLES)),
) -> dict:
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    try:
        validated = _validated_uploaded_template(file)
        template = store_account_template(db, account_id, validated, actor.id)
    except TemplateUploadError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise
    audit(db, actor.id, "Account Template Updated", "Accounts", f"PPT template updated for account {account.name}")
    db.commit()
    db.refresh(template)
    return {"id": template.id, "filename": template.filename, "status": "configured"}


@router.delete("/accounts/{account_id}/template", status_code=204)
def delete_account_template(account_id: str, db: Session = Depends(get_db), actor: Employee = Depends(require_roles(*STUDIO_HEAD_ROLES))):
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    templates = remove_account_templates(db, account_id)
    if not templates:
        raise HTTPException(status_code=404, detail="No PPT template configured for this account")
    audit(db, actor.id, "Account Template Removed", "Accounts", f"PPT template removed for account {account.name}")
    db.commit()
    return None


@router.delete("/accounts/{account_id}", status_code=204)
def delete_account(account_id: str, db: Session = Depends(get_db), actor: Employee = Depends(require_roles(*STUDIO_HEAD_ROLES))):
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    audit(db, actor.id, "Account Deleted", "Accounts", f"Account {account.name} deleted")
    db.delete(account)
    db.commit()
    return None


@router.post("/projects", response_model=ProjectOut, status_code=201)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db), actor: Employee = Depends(get_current_user)) -> Project:
    account = db.get(Account, payload.account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    require_account_manager(actor, account)
    validate_project_manager(db, account, payload.project_manager_id)
    data = payload.model_dump(exclude={"tech_stack"})
    data["program_manager_id"] = account.program_manager_id
    data["tech_stack"] = ",".join(payload.tech_stack)
    project = Project(**data)
    db.add(project)
    audit(db, actor.id, "Project Created", "Projects", f"Project {project.name} created")
    db.commit()
    db.refresh(project)
    return project


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db), actor: Employee = Depends(get_current_user)) -> list[Project]:
    ids = visible_project_ids(db, actor)
    if not ids:
        return []
    return list(db.scalars(select(Project).where(Project.id.in_(ids)).order_by(Project.name)).all())


@router.put("/projects/{project_id}", response_model=ProjectOut)
def update_project(project_id: str, payload: ProjectUpdate, db: Session = Depends(get_db), actor: Employee = Depends(get_current_user)) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    account = db.get(Account, project.account_id)
    require_project_manager(actor, project, account)
    data = payload.model_dump(exclude_unset=True)
    if "program_manager_id" in data and data["program_manager_id"] != (account.program_manager_id if account else None):
        raise HTTPException(status_code=422, detail="Project program manager must match the account manager")
    if "project_manager_id" in data and account:
        validate_project_manager(db, account, data["project_manager_id"])
    if "tech_stack" in data and data["tech_stack"] is not None:
        data["tech_stack"] = ",".join(data["tech_stack"])
    for key, value in data.items():
        setattr(project, key, value)
    audit(db, actor.id, "Project Updated", "Projects", f"Project {project.name} updated")
    db.commit()
    db.refresh(project)
    return project


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: str, db: Session = Depends(get_db), actor: Employee = Depends(get_current_user)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    require_project_manager(actor, project, db.get(Account, project.account_id))
    audit(db, actor.id, "Project Deleted", "Projects", f"Project {project.name} deleted")
    db.delete(project)
    db.commit()
    return None


@router.post("/allocations", response_model=AllocationOut, status_code=201)
def allocate(payload: AllocationCreate, db: Session = Depends(get_db), actor: Employee = Depends(get_current_user)):
    allocation = create_allocation(db, payload, actor)
    # create_allocation doesn't pre-populate the joined properties, we could reload or just return it.
    # The response model will ignore missing fields, but we should try to populate names
    project = db.get(Project, allocation.project_id)
    employee = db.get(Employee, allocation.employee_id)
    setattr(allocation, "project_name", project.name if project else None)
    setattr(allocation, "employee_name", employee.name if employee else None)
    setattr(allocation, "employee_title", employee.title if employee else None)
    setattr(allocation, "employee_email", employee.email if employee else None)
    setattr(allocation, "department", employee.department if employee else None)
    return allocation


@router.get("/allocations", response_model=list[AllocationOut])
def list_allocations(db: Session = Depends(get_db), actor: Employee = Depends(get_current_user)):
    project_ids = visible_project_ids(db, actor)
    if not project_ids:
        return []
    allocations = db.scalars(select(ResourceAllocation).where(ResourceAllocation.project_id.in_(project_ids), ResourceAllocation.is_active.is_(True))).all()
    # Populate names for frontend
    result = []
    for alloc in allocations:
        project = db.get(Project, alloc.project_id)
        employee = db.get(Employee, alloc.employee_id)
        setattr(alloc, "project_name", project.name if project else None)
        setattr(alloc, "employee_name", employee.name if employee else None)
        setattr(alloc, "employee_title", employee.title if employee else None)
        setattr(alloc, "employee_email", employee.email if employee else None)
        setattr(alloc, "department", employee.department if employee else None)
        result.append(alloc)
    return result


@router.delete("/allocations/{allocation_id}", status_code=204)
def delete_allocation(allocation_id: str, db: Session = Depends(get_db), actor: Employee = Depends(get_current_user)):
    allocation = db.get(ResourceAllocation, allocation_id)
    if not allocation:
        raise HTTPException(status_code=404, detail="Allocation not found")
    
    project = db.get(Project, allocation.project_id)
    require_project_manager(actor, project, db.get(Account, project.account_id) if project else None)
         
    audit(db, actor.id, "Resource Deallocated", "Projects", f"Deallocated employee {allocation.employee_id} from project {allocation.project_id}")
    allocation.is_active = False
    employee = db.get(Employee, allocation.employee_id)
    other_active = db.scalar(select(ResourceAllocation.id).where(ResourceAllocation.employee_id == allocation.employee_id, ResourceAllocation.id != allocation.id, ResourceAllocation.is_active.is_(True)).limit(1))
    if employee and not other_active:
        from app.models.people import Availability
        employee.availability = Availability.AVAILABLE
    db.commit()
    return None


@router.post("/status", response_model=WeeklyStatusOut, status_code=201)
def submit_status(payload: WeeklyStatusCreate, db: Session = Depends(get_db), actor: Employee = Depends(get_current_user)) -> WeeklyStatus:
    if actor.role not in MANAGER_ROLES:
        raise HTTPException(status_code=403, detail="Only authorized managers can submit status updates")
    if payload.employee_id != actor.id:
        raise HTTPException(status_code=403, detail="Managers can submit only their own status updates")
    if not db.get(Employee, payload.employee_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found")
    if payload.project_id:
        project = db.get(Project, payload.project_id)
        require_project_access(db, actor, project)
        if actor.role == Role.PROJECT_MANAGER and project.project_manager_id != actor.id:
            raise HTTPException(status_code=403, detail="Project managers can submit status only for assigned projects")
    elif actor.role == Role.PROJECT_MANAGER:
        raise HTTPException(status_code=422, detail="Project status requires a project")
    frequency = str(payload.fields.get("reportingFrequency") or payload.fields.get("frequency") or "Weekly")
    if frequency.lower() not in {"daily", "weekly", "monthly"}:
        raise HTTPException(status_code=422, detail="Status frequency must be Daily, Weekly, or Monthly")
    if _status_for_reporting_period(db, payload.employee_id, payload.project_id, payload.week_start, frequency):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A status report already exists for this employee, project, and reporting date.",
        )
    weekly_status = WeeklyStatus(**payload.model_dump())
    if weekly_status.status.value == "submitted":
        weekly_status.submitted_at = datetime.now(timezone.utc)
    db.add(weekly_status)
    audit(db, actor.id, "Status Saved", "Weekly Status", f"Status saved for employee {payload.employee_id}")
    db.commit()
    db.refresh(weekly_status)
    _index_status_safely(db, weekly_status)
    return weekly_status


@router.put("/status/{status_id}", response_model=WeeklyStatusOut)
def update_status(
    status_id: str,
    payload: WeeklyStatusUpdate,
    db: Session = Depends(get_db),
    actor: Employee = Depends(get_current_user),
) -> WeeklyStatus:
    weekly_status = db.get(WeeklyStatus, status_id)
    if not weekly_status:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Status report not found")
    if actor.role not in MANAGER_ROLES:
        raise HTTPException(status_code=403, detail="Only authorized managers can update status")
    if weekly_status.employee_id != actor.id and not is_studio_head(actor):
        raise HTTPException(status_code=403, detail="Not authorized to update this status")
    if weekly_status.project_id:
        require_project_access(db, actor, db.get(Project, weekly_status.project_id))
    if payload.fields is not None:
        weekly_status.fields = payload.fields
    if payload.status is not None:
        weekly_status.status = payload.status
        weekly_status.submitted_at = datetime.now(timezone.utc) if payload.status.value == "submitted" else weekly_status.submitted_at
    audit(db, actor.id, "Status Updated", "Weekly Status", f"Status updated for employee {weekly_status.employee_id}")
    db.commit()
    db.refresh(weekly_status)
    _index_status_safely(db, weekly_status)
    return weekly_status


@router.get("/status", response_model=list[WeeklyStatusOut])
def list_statuses(db: Session = Depends(get_db), actor: Employee = Depends(get_current_user)) -> list[WeeklyStatus]:
    project_ids = visible_project_ids(db, actor)
    conditions = [WeeklyStatus.employee_id == actor.id]
    if project_ids:
        conditions.append(WeeklyStatus.project_id.in_(project_ids))
    from sqlalchemy import or_
    return list(db.scalars(select(WeeklyStatus).where(or_(*conditions)).order_by(WeeklyStatus.week_start.desc())).all())


@router.delete("/status/{status_id}", status_code=204)
def delete_status(status_id: str, db: Session = Depends(get_db), actor: Employee = Depends(get_current_user)):
    weekly_status = db.get(WeeklyStatus, status_id)
    if not weekly_status:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Status report not found")
    if actor.role not in MANAGER_ROLES or (weekly_status.employee_id != actor.id and not is_studio_head(actor)):
        raise HTTPException(status_code=403, detail="Not authorized to delete this status")
    if weekly_status.status.value not in {"draft", "not_started"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only draft status reports can be deleted")
    audit(db, actor.id, "Status Deleted", "Weekly Status", f"Draft status deleted for employee {weekly_status.employee_id}")
    db.delete(weekly_status)
    db.commit()
    return None


@router.post("/rag/reindex", response_model=dict)
def reindex(db: Session = Depends(get_db), _: Employee = Depends(require_min_role(Role.PROJECT_MANAGER))) -> dict:
    return {"indexed": index_statuses(db)}
