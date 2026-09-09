from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.security import get_current_user, require_min_role
from app.db.session import get_db
from app.models.delivery import Account, AllocationRole, Project, ResourceAllocation
from app.models.people import Employee, Role
from app.models.tasks import Task, TaskComment, TaskNotification, TaskPriority, TaskStatus, TaskStatusHistory, TaskType
from app.schemas.common import EligibleTaskAssigneeOut, TaskApprovalAction, TaskCommentCreate, TaskCommentOut, TaskCreate, TaskOut, TaskReviewSubmit, TaskStatusHistoryOut, TaskStatusUpdate, TaskUpdate
from app.services.audit import audit
from app.services.access import can_manage_project, require_project_access, require_project_manager, visible_project_ids

router = APIRouter(prefix="/tasks", tags=["tasks"])

MANAGER_ALLOCATION_ROLES = {
    AllocationRole.STUDIO_HEAD,
    AllocationRole.PROGRAM_MANAGER,
    AllocationRole.PROJECT_MANAGER,
}

EXECUTION_ROLES = set(AllocationRole) - MANAGER_ALLOCATION_ROLES

ASSIGNEE_TRANSITIONS = {
    TaskStatus.TODO: {TaskStatus.IN_PROGRESS},
    TaskStatus.IN_PROGRESS: {TaskStatus.REVIEW},
}

MANAGER_TRANSITIONS = {
    TaskStatus.TODO: {TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED},
    TaskStatus.IN_PROGRESS: {TaskStatus.REVIEW, TaskStatus.BLOCKED},
    TaskStatus.REVIEW: {TaskStatus.BLOCKED, TaskStatus.DONE},
    TaskStatus.BLOCKED: {TaskStatus.DONE},
}


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
    elif task.labels is None:
        setattr(task, "labels", [])
    if task.tags is None:
        task.tags = []
    if task.checklist is None:
        task.checklist = []
    setattr(task, "project_name", project.name if project else None)
    setattr(task, "account_id", project.account_id if project else "")
    setattr(task, "account_name", account.name if account else None)
    setattr(task, "assignee_name", assignee.name if assignee else None)
    setattr(task, "reporter_name", reporter.name if reporter else None)
    return task


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


def _ensure_assignee_is_eligible(project_id: str, assignee_id: str, db: Session) -> Employee:
    employee = db.get(Employee, assignee_id)
    allocation = _project_allocation(project_id, assignee_id, db)
    if not employee or not employee.is_active or not allocation:
        raise HTTPException(status_code=422, detail="The selected person is not an active resource on this project.")
    if employee.role in {Role.PROJECT_MANAGER, Role.PROGRAM_MANAGER, Role.PROGRAM_DIRECTOR, Role.DELIVERY_HEAD, Role.STUDIO_HEAD} or allocation.allocation_role not in EXECUTION_ROLES:
        raise HTTPException(status_code=422, detail="Project and program managers cannot be assigned tasks.")
    return employee


def _task_is_assigned_to(task: Task, employee_id: str) -> bool:
    return task.assignee_id == employee_id


def _require_task_access(task: Task | None, actor: Employee, db: Session) -> Task:
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    require_project_access(db, actor, db.get(Project, task.project_id))
    if actor.role in {Role.DEVELOPER, Role.INTERN} and not _task_is_assigned_to(task, actor.id):
        raise HTTPException(status_code=404, detail="Task not found")
    return task


def _manager_recipient_ids(project: Project, db: Session) -> set[str]:
    account = db.get(Account, project.account_id)
    return {
        employee_id
        for employee_id in {
            project.project_manager_id,
            project.program_manager_id,
            account.program_manager_id if account else None,
        }
        if employee_id
    }


def _notify(db: Session, recipient_ids: set[str], task: Task, notification_type: str, title: str, message: str) -> None:
    for recipient_id in recipient_ids:
        db.add(TaskNotification(
            recipient_id=recipient_id,
            task_id=task.id,
            notification_type=notification_type,
            title=title,
            message=message,
        ))


def _change_status(task: Task, next_status: TaskStatus, actor: Employee, project: Project, db: Session, blocker_reason: str | None = None) -> None:
    previous_status = task.status
    if next_status == previous_status:
        return
    if not task.assignee_id:
        raise HTTPException(status_code=409, detail="Assign an eligible project member before moving this task.")
    manager = can_manage_project(actor, project, db.get(Account, project.account_id))
    allowed = MANAGER_TRANSITIONS.get(previous_status, set()) if manager else ASSIGNEE_TRANSITIONS.get(previous_status, set())
    if not manager and task.assignee_id != actor.id:
        raise HTTPException(status_code=403, detail="Only the assigned person can move this task.")
    if next_status not in allowed:
        raise HTTPException(status_code=409, detail="Invalid task status transition")
    if next_status == TaskStatus.BLOCKED and not manager:
        raise HTTPException(status_code=403, detail="Only a project or program manager can block a task.")
    if next_status == TaskStatus.DONE and not manager:
        raise HTTPException(status_code=403, detail="Only a project or program manager can complete a task.")

    task.status = next_status
    task.blocker_reason = blocker_reason if next_status == TaskStatus.BLOCKED else task.blocker_reason
    now = datetime.now(timezone.utc)
    if next_status == TaskStatus.REVIEW:
        task.submitted_for_review_at = now
    if next_status == TaskStatus.DONE:
        task.approved_at = now
    db.add(TaskStatusHistory(
        task_id=task.id,
        previous_status=previous_status,
        new_status=next_status,
        changed_by_id=actor.id,
    ))
    audit(db, actor.id, "Task Completed" if next_status == TaskStatus.DONE else "Task Status Updated", "Task Tracker", f"Task {task.title} moved from {previous_status.value} to {next_status.value}")

    task_ref = f"TASK-{task.id[:8].upper()}"
    if next_status == TaskStatus.REVIEW:
        _notify(db, _manager_recipient_ids(project, db), task, "alert", "Task ready for review", f"{task_ref} has been moved to In Review by {actor.name}.")
    elif next_status == TaskStatus.BLOCKED:
        recipients = _manager_recipient_ids(project, db) | ({task.assignee_id} if task.assignee_id else set())
        _notify(db, recipients - {actor.id}, task, "alert", "Task blocked", f"{task_ref} has been marked Blocked.")
    elif next_status == TaskStatus.DONE:
        recipients = _manager_recipient_ids(project, db) | ({task.assignee_id} if task.assignee_id else set())
        _notify(db, recipients - {actor.id}, task, "success", "Task completed", f"{task_ref} has been moved to Done.")
    elif next_status == TaskStatus.IN_PROGRESS:
        _notify(db, _manager_recipient_ids(project, db) - {actor.id}, task, "info", "Task in progress", f"{task_ref} has been moved to In Progress by {actor.name}.")


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
            ResourceAllocation.allocation_role.in_(EXECUTION_ROLES),
            Employee.role.notin_({Role.PROJECT_MANAGER, Role.PROGRAM_MANAGER, Role.PROGRAM_DIRECTOR, Role.DELIVERY_HEAD, Role.STUDIO_HEAD}),
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
        stmt = stmt.where(Task.assignee_id == actor.id)
    if account_id:
        stmt = stmt.where(Project.account_id == account_id)
    if project_id:
        stmt = stmt.where(Task.project_id == project_id)
    if assignee_id:
        stmt = stmt.where(Task.assignee_id == assignee_id)
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
    assignee = _ensure_assignee_is_eligible(payload.project_id, payload.assignee_id, db)

    task = Task(
        **payload.model_dump(exclude={"labels", "assignee_id"}),
        reporter_id=actor.id,
        assignee_id=payload.assignee_id,
        labels=_labels_to_text(payload.labels),
    )
    try:
        db.add(task)
        db.flush()
        audit(db, actor.id, "Task Created", "Task Tracker", f"Task {task.title} created for project {project.name}")
        audit(db, actor.id, "Task Assigned", "Task Tracker", f"Task {task.title} assigned to {assignee.name}")
        _notify(db, {assignee.id}, task, "info", "Task assigned", f"You have been assigned task TASK-{task.id[:8].upper()} for {project.name}.")
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
    if "assignee_id" in data:
        _ensure_assignee_is_eligible(task.project_id, data["assignee_id"], db)
    previous_assignee_id = task.assignee_id
    previous_priority = task.priority
    previous_due_date = task.due_date
    changes: list[str] = []
    for key, value in data.items():
        if getattr(task, key) != value:
            changes.append(key)
        setattr(task, key, value)
    audit(db, actor.id, "Task Updated", "Task Tracker", f"Task {task.title} updated: {', '.join(changes) or 'no field changes'}")
    if task.assignee_id != previous_assignee_id:
        audit(db, actor.id, "Task Reassigned", "Task Tracker", f"Task {task.title} assignment changed")
        _notify(db, {task.assignee_id}, task, "info", "Task reassigned", f"You have been assigned task TASK-{task.id[:8].upper()} for {project.name}.")
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
    payload: TaskStatusUpdate,
    db: Session = Depends(get_db),
    actor: Employee = Depends(get_current_user),
) -> Task:
    if payload.status is None:
        raise HTTPException(status_code=400, detail="Status is required")
    task = _require_task_access(db.get(Task, task_id), actor, db)
    project = require_project_access(db, actor, db.get(Project, task.project_id))
    _change_status(task, payload.status, actor, project, db, payload.blocker_reason)
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
    if actor.id != task.assignee_id:
        raise HTTPException(status_code=403, detail="Only assigned employees can submit this task for review")
    project = require_project_access(db, actor, db.get(Project, task.project_id))
    _change_status(task, TaskStatus.REVIEW, actor, project, db)
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
        _change_status(task, TaskStatus.DONE, actor, project, db)
        task.rejection_reason = None
    elif payload.action == "block":
        _change_status(task, TaskStatus.BLOCKED, actor, project, db, payload.comment)
    else:
        raise HTTPException(status_code=409, detail="Invalid task status transition")
    db.commit()
    db.refresh(task)
    return _hydrate_task(task, db)


@router.get("/{task_id}/history", response_model=list[TaskStatusHistoryOut])
def task_status_history(
    task_id: str,
    db: Session = Depends(get_db),
    actor: Employee = Depends(get_current_user),
) -> list[TaskStatusHistory]:
    task = _require_task_access(db.get(Task, task_id), actor, db)
    history = db.scalars(select(TaskStatusHistory).where(TaskStatusHistory.task_id == task.id).order_by(TaskStatusHistory.changed_at)).all()
    for entry in history:
        setattr(entry, "changed_by_name", entry.changed_by.name if entry.changed_by else None)
    return list(history)


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
