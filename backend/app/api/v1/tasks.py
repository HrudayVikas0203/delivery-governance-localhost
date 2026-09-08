from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.security import get_current_user, require_min_role
from app.db.session import get_db
from app.models.delivery import Account, AllocationRole, Project, ResourceAllocation
from app.models.people import Employee, Role
from app.models.tasks import Task, TaskAssignment, TaskComment, TaskPriority, TaskStatus, TaskType
from app.schemas.common import EligibleTaskAssigneeOut, TaskApprovalAction, TaskCommentCreate, TaskCommentOut, TaskCreate, TaskOut, TaskReviewSubmit, TaskUpdate
from app.services.audit import audit
from app.services.access import can_manage_project, require_project_access, require_project_manager, visible_project_ids

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _labels_to_text(labels: list[str] | None) -> str | None:
    if not labels:
        return None
    return ",".join(label.strip() for label in labels if label.strip())


def _hydrate_task(task: Task, db: Session) -> Task:
    project = db.get(Project, task.project_id)
    account = db.get(Account, project.account_id) if project else None
    assignee = db.get(Employee, task.assignee_id) if task.assignee_id else None
    reporter = db.get(Employee, task.reporter_id) if task.reporter_id else None
    if isinstance(task.labels, str):
        setattr(task, "labels", task.labels.split(",") if task.labels else [])
    setattr(task, "assignee_ids", [assignment.employee_id for assignment in task.assignments])
    setattr(task, "project_name", project.name if project else None)
    setattr(task, "account_id", project.account_id if project else "")
    setattr(task, "account_name", account.name if account else None)
    setattr(task, "assignee_name", assignee.name if assignee else None)
    setattr(task, "reporter_name", reporter.name if reporter else None)
    return task


def _sync_assignments(task: Task, assignee_ids: list[str], db: Session) -> None:
    existing = {assignment.employee_id: assignment for assignment in task.assignments}
    requested = set(assignee_ids)
    for employee_id in requested:
        if not db.get(Employee, employee_id):
            raise HTTPException(status_code=404, detail=f"Assignee {employee_id} not found")
        if employee_id not in existing:
            db.add(TaskAssignment(task_id=task.id, employee_id=employee_id))
    for employee_id, assignment in existing.items():
        if employee_id not in requested:
            db.delete(assignment)


def _project_allocation(project_id: str, employee_id: str, db: Session) -> ResourceAllocation | None:
    return db.scalar(
        select(ResourceAllocation).where(
            ResourceAllocation.project_id == project_id,
            ResourceAllocation.employee_id == employee_id,
            ResourceAllocation.is_active.is_(True),
        )
    )


def _ensure_task_authority(project: Project, actor: Employee, db: Session) -> None:
    account = db.get(Account, project.account_id)
    if can_manage_project(actor, project, account):
        return
    allocation = _project_allocation(project.id, actor.id, db)
    if allocation and allocation.allocation_role in {
        AllocationRole.ARCHITECT,
        AllocationRole.TECHNICAL_ARCHITECT,
        AllocationRole.SOLUTION_ARCHITECT,
        AllocationRole.TEAM_LEAD,
    }:
        return
    raise HTTPException(status_code=403, detail="You do not have permission to manage tasks for this project.")


def _ensure_assignees_are_project_team(project_id: str, assignee_ids: list[str], db: Session) -> None:
    for assignee_id in assignee_ids:
        employee = db.get(Employee, assignee_id)
        allocation = _project_allocation(project_id, assignee_id, db)
        if not employee or not employee.is_active or not allocation:
            raise HTTPException(status_code=422, detail="The selected developer is not allocated to this project.")


def _task_is_assigned_to(task: Task, employee_id: str) -> bool:
    return task.assignee_id == employee_id or any(
        assignment.employee_id == employee_id for assignment in task.assignments
    )


def _require_task_access(task: Task | None, actor: Employee, db: Session) -> Task:
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    require_project_access(db, actor, db.get(Project, task.project_id))
    if actor.role in {Role.DEVELOPER, Role.INTERN} and not _task_is_assigned_to(task, actor.id):
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.get("/projects/{project_id}/eligible-assignees", response_model=list[EligibleTaskAssigneeOut])
def eligible_task_assignees(
    project_id: str,
    db: Session = Depends(get_db),
    actor: Employee = Depends(get_current_user),
) -> list[dict]:
    project = require_project_access(db, actor, db.get(Project, project_id))
    if actor.role not in {Role.DEVELOPER, Role.INTERN}:
        _ensure_task_authority(project, actor, db)
    rows = db.execute(
        select(Employee, ResourceAllocation.allocation_role)
        .join(ResourceAllocation, ResourceAllocation.employee_id == Employee.id)
        .where(
            ResourceAllocation.project_id == project_id,
            ResourceAllocation.is_active.is_(True),
            ResourceAllocation.allocation_role.notin_(
                {
                    AllocationRole.STUDIO_HEAD,
                    AllocationRole.PROGRAM_MANAGER,
                    AllocationRole.PROJECT_MANAGER,
                }
            ),
            Employee.is_active.is_(True),
        )
        .order_by(Employee.name)
    ).all()
    return [
        {
            "id": employee.id,
            "name": employee.name,
            "email": employee.email,
            "title": employee.title,
            "role": employee.role,
            "allocation_role": allocation_role,
        }
        for employee, allocation_role in rows
    ]


@router.get("", response_model=list[TaskOut])
def list_tasks(
    account_id: str | None = None,
    project_id: str | None = None,
    assignee_id: str | None = None,
    reporter_id: str | None = None,
    task_status: TaskStatus | None = None,
    priority: TaskPriority | None = None,
    task_type: TaskType | None = None,
    db: Session = Depends(get_db),
    actor: Employee = Depends(get_current_user),
) -> list[Task]:
    allowed_ids = visible_project_ids(db, actor)
    if project_id and project_id not in allowed_ids:
        raise HTTPException(status_code=404, detail="Project not found")
    if not allowed_ids:
        return []
    stmt = select(Task).join(Project, Project.id == Task.project_id).where(Task.project_id.in_(allowed_ids))
    if actor.role in {Role.DEVELOPER, Role.INTERN}:
        stmt = stmt.where(
            or_(
                Task.assignee_id == actor.id,
                Task.assignments.any(TaskAssignment.employee_id == actor.id),
            )
        )
    if account_id:
        stmt = stmt.where(Project.account_id == account_id)
    if project_id:
        stmt = stmt.where(Task.project_id == project_id)
    if assignee_id:
        stmt = stmt.where(
            or_(
                Task.assignee_id == assignee_id,
                Task.assignments.any(TaskAssignment.employee_id == assignee_id),
            )
        )
    if reporter_id:
        stmt = stmt.where(Task.reporter_id == reporter_id)
    if task_status:
        stmt = stmt.where(Task.status == task_status)
    if priority:
        stmt = stmt.where(Task.priority == priority)
    if task_type:
        stmt = stmt.where(Task.task_type == task_type)
    stmt = stmt.order_by(Task.updated_at.desc())
    return [_hydrate_task(task, db) for task in db.scalars(stmt).unique().all()]


@router.get("/{task_id}", response_model=TaskOut)
def get_task(
    task_id: str,
    db: Session = Depends(get_db),
    actor: Employee = Depends(get_current_user),
) -> Task:
    task = _require_task_access(db.get(Task, task_id), actor, db)
    return _hydrate_task(task, db)


@router.post("", response_model=TaskOut, status_code=201)
def create_task(
    payload: TaskCreate,
    db: Session = Depends(get_db),
    actor: Employee = Depends(get_current_user),
) -> Task:
    project = db.get(Project, payload.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    _ensure_task_authority(project, actor, db)
    assignee_ids = list(dict.fromkeys(([payload.assignee_id] if payload.assignee_id else []) + payload.assignee_ids))
    _ensure_assignees_are_project_team(payload.project_id, assignee_ids, db)

    task = Task(
        **payload.model_dump(exclude={"labels", "assignee_id", "assignee_ids"}),
        reporter_id=actor.id,
        assignee_id=payload.assignee_id or (assignee_ids[0] if assignee_ids else None),
        labels=_labels_to_text(payload.labels),
    )
    try:
        db.add(task)
        db.flush()
        _sync_assignments(task, assignee_ids, db)
        audit(db, actor.id, "Task Created", "Task Tracker", f"Task {task.title} created for project {project.name}")
        if assignee_ids:
            audit(db, actor.id, "Task Assigned", "Task Tracker", f"Task {task.title} assigned to {len(assignee_ids)} project resource(s)")
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A task with this title already exists in the selected project.") from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="Unable to save the task. Please try again.") from exc
    db.refresh(task)
    return _hydrate_task(task, db)


@router.put("/{task_id}", response_model=TaskOut)
def update_task(
    task_id: str,
    payload: TaskUpdate,
    db: Session = Depends(get_db),
    actor: Employee = Depends(get_current_user),
) -> Task:
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    project = require_project_access(db, actor, db.get(Project, task.project_id))
    _ensure_task_authority(project, actor, db)
    data = payload.model_dump(exclude_unset=True)
    if "start_date" in data or "due_date" in data:
        start_date = data.get("start_date", task.start_date)
        due_date = data.get("due_date", task.due_date)
        if start_date and due_date and due_date < start_date:
            raise HTTPException(status_code=422, detail="Due date cannot be before start date.")
    if "labels" in data:
        data["labels"] = _labels_to_text(data["labels"])
    assignee_ids = data.pop("assignee_ids", None)
    requested_assignees = list(assignee_ids or [])
    if data.get("assignee_id"):
        requested_assignees.append(data["assignee_id"])
    _ensure_assignees_are_project_team(task.project_id, list(dict.fromkeys(requested_assignees)), db)
    previous_assignee_id = task.assignee_id
    previous_priority = task.priority
    previous_due_date = task.due_date
    changes: list[str] = []
    for key, value in data.items():
        if getattr(task, key) != value:
            changes.append(key)
        setattr(task, key, value)
    if assignee_ids is not None:
        _sync_assignments(task, assignee_ids, db)
        task.assignee_id = assignee_ids[0] if assignee_ids else task.assignee_id
        changes.append("assignee")
    audit(db, actor.id, "Task Updated", "Task Tracker", f"Task {task.title} updated: {', '.join(changes) or 'no field changes'}")
    if task.assignee_id != previous_assignee_id or assignee_ids is not None:
        audit(db, actor.id, "Task Reassigned", "Task Tracker", f"Task {task.title} assignment changed")
    if task.priority != previous_priority:
        audit(db, actor.id, "Task Priority Changed", "Task Tracker", f"Task {task.title} priority changed from {previous_priority.value} to {task.priority.value}")
    if task.due_date != previous_due_date:
        audit(db, actor.id, "Task Due Date Changed", "Task Tracker", f"Task {task.title} due date changed")
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A task with this title already exists in the selected project.") from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="Unable to save the task. Please try again.") from exc
    db.refresh(task)
    return _hydrate_task(task, db)


@router.put("/{task_id}/status", response_model=TaskOut)
def update_task_status(
    task_id: str,
    payload: TaskUpdate,
    db: Session = Depends(get_db),
    actor: Employee = Depends(get_current_user),
) -> Task:
    if payload.status is None:
        raise HTTPException(status_code=400, detail="Status is required")
    task = _require_task_access(db.get(Task, task_id), actor, db)
    project = require_project_access(db, actor, db.get(Project, task.project_id))
    assigned_ids = {task.assignee_id, *[assignment.employee_id for assignment in task.assignments]}
    if actor.id not in assigned_ids:
        _ensure_task_authority(project, actor, db)
    previous_status = task.status
    task.status = payload.status
    task.blocker_reason = payload.blocker_reason
    action = "Task Completed" if payload.status == TaskStatus.DONE else "Task Status Updated"
    audit(db, actor.id, action, "Task Tracker", f"Task {task.title} moved from {previous_status.value} to {payload.status.value}")
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="Unable to update the task status. Please try again.") from exc
    db.refresh(task)
    return _hydrate_task(task, db)


@router.post("/{task_id}/submit-for-review", response_model=TaskOut)
def submit_for_review(
    task_id: str,
    _: TaskReviewSubmit,
    db: Session = Depends(get_db),
    actor: Employee = Depends(get_current_user),
) -> Task:
    task = _require_task_access(db.get(Task, task_id), actor, db)
    if actor.id not in {task.assignee_id, *[assignment.employee_id for assignment in task.assignments]}:
        raise HTTPException(status_code=403, detail="Only assigned employees can submit this task for review")
    task.status = TaskStatus.REVIEW
    task.submitted_for_review_at = datetime.now(timezone.utc)
    audit(db, actor.id, "Task Submitted for Review", "Task Tracker", f"Task {task.title} submitted for review")
    db.commit()
    db.refresh(task)
    return _hydrate_task(task, db)


@router.post("/{task_id}/approval", response_model=TaskOut)
def task_approval(
    task_id: str,
    payload: TaskApprovalAction,
    db: Session = Depends(get_db),
    actor: Employee = Depends(require_min_role(Role.TEAM_LEAD)),
) -> Task:
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    project = require_project_access(db, actor, db.get(Project, task.project_id))
    require_project_manager(actor, project, db.get(Account, project.account_id))
    if payload.action == "approve":
        task.status = TaskStatus.DONE
        task.approved_at = datetime.now(timezone.utc)
        task.rejection_reason = None
    elif payload.action in {"reject", "changes_requested"}:
        task.status = TaskStatus.IN_PROGRESS
        task.rejection_reason = payload.comment or "Changes requested"
    elif payload.action == "block":
        task.status = TaskStatus.BLOCKED
        task.blocker_reason = payload.comment or task.blocker_reason
    elif payload.action == "unblock":
        task.status = TaskStatus.IN_PROGRESS
        task.blocker_reason = None
    audit(db, actor.id, f"Task {payload.action.title()}", "Task Tracker", f"Task {task.title}: {payload.comment or payload.action}")
    db.commit()
    db.refresh(task)
    return _hydrate_task(task, db)


@router.delete("/{task_id}", status_code=204)
def delete_task(task_id: str, db: Session = Depends(get_db), actor: Employee = Depends(require_min_role(Role.TEAM_LEAD))):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    project = require_project_access(db, actor, db.get(Project, task.project_id))
    require_project_manager(actor, project, db.get(Account, project.account_id))
    audit(db, actor.id, "Task Deleted", "Task Tracker", f"Task {task.title} deleted")
    db.delete(task)
    db.commit()
    return None


@router.get("/{task_id}/comments", response_model=list[TaskCommentOut])
def list_comments(task_id: str, db: Session = Depends(get_db), actor: Employee = Depends(get_current_user)) -> list[TaskComment]:
    task = _require_task_access(db.get(Task, task_id), actor, db)
    comments = db.scalars(select(TaskComment).where(TaskComment.task_id == task_id).order_by(TaskComment.created_at)).all()
    for comment in comments:
        setattr(comment, "author_name", comment.author.name if comment.author else None)
    return list(comments)


@router.post("/{task_id}/comments", response_model=TaskCommentOut, status_code=201)
def add_comment(
    task_id: str,
    payload: TaskCommentCreate,
    db: Session = Depends(get_db),
    actor: Employee = Depends(get_current_user),
) -> TaskComment:
    task = _require_task_access(db.get(Task, task_id), actor, db)
    comment = TaskComment(task_id=task_id, author_id=actor.id, body=payload.body)
    db.add(comment)
    audit(db, actor.id, "Task Commented", "Task Tracker", f"Comment added to task {task_id}")
    db.commit()
    db.refresh(comment)
    setattr(comment, "author_name", actor.name)
    return comment
