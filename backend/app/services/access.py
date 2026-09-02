from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.delivery import Account, Project, ResourceAllocation
from app.models.people import Employee, Role


STUDIO_HEAD_ROLES = {Role.STUDIO_HEAD, Role.DELIVERY_HEAD}
PROGRAM_ROLES = {Role.PROGRAM_MANAGER, Role.PROGRAM_DIRECTOR}
MANAGER_ROLES = STUDIO_HEAD_ROLES | PROGRAM_ROLES | {Role.PROJECT_MANAGER}


def is_studio_head(user: Employee) -> bool:
    return user.role in STUDIO_HEAD_ROLES


def visible_project_ids(db: Session, user: Employee) -> set[str]:
    if is_studio_head(user):
        return set(db.scalars(select(Project.id)).all())
    if user.role in PROGRAM_ROLES:
        account_ids = set(
            db.scalars(select(Account.id).where(Account.program_manager_id == user.id)).all()
        )
        return set(
            db.scalars(
                select(Project.id).where(
                    (Project.account_id.in_(account_ids)) | (Project.program_manager_id == user.id)
                )
            ).all()
        )
    if user.role == Role.PROJECT_MANAGER:
        return set(
            db.scalars(select(Project.id).where(Project.project_manager_id == user.id)).all()
        )
    return set(
        db.scalars(
            select(ResourceAllocation.project_id).where(
                ResourceAllocation.employee_id == user.id,
                ResourceAllocation.is_active.is_(True),
            )
        ).all()
    )


def visible_account_ids(db: Session, user: Employee) -> set[str]:
    if is_studio_head(user):
        return set(db.scalars(select(Account.id)).all())
    account_ids = set()
    if user.role in PROGRAM_ROLES:
        account_ids.update(
            db.scalars(select(Account.id).where(Account.program_manager_id == user.id)).all()
        )
    project_ids = visible_project_ids(db, user)
    if project_ids:
        account_ids.update(
            db.scalars(select(Project.account_id).where(Project.id.in_(project_ids))).all()
        )
    return account_ids


def can_view_project(db: Session, user: Employee, project: Project) -> bool:
    return project.id in visible_project_ids(db, user)


def require_project_access(db: Session, user: Employee, project: Project | None) -> Project:
    if project is None or not can_view_project(db, user, project):
        # Deliberately do not reveal whether an inaccessible identifier exists.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


def require_account_access(db: Session, user: Employee, account: Account | None) -> Account:
    if account is None or account.id not in visible_account_ids(db, user):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    return account


def can_manage_account(user: Employee, account: Account) -> bool:
    return is_studio_head(user) or (
        user.role in PROGRAM_ROLES and account.program_manager_id == user.id
    )


def require_account_manager(user: Employee, account: Account) -> None:
    if not can_manage_account(user, account):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to manage this account")


def can_manage_project(user: Employee, project: Project, account: Account | None = None) -> bool:
    if is_studio_head(user):
        return True
    if user.role in PROGRAM_ROLES:
        return project.program_manager_id == user.id or bool(
            account and account.program_manager_id == user.id
        )
    return user.role == Role.PROJECT_MANAGER and project.project_manager_id == user.id


def require_project_manager(user: Employee, project: Project, account: Account | None = None) -> None:
    if not can_manage_project(user, project, account):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to manage this project")


def validate_account_program_manager(db: Session, employee_id: str | None) -> Employee | None:
    if not employee_id:
        return None
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Program manager or director not found")
    if not employee.is_active or employee.role not in PROGRAM_ROLES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Account manager must be an active Program Manager or Program Director",
        )
    return employee


def validate_project_manager(db: Session, account: Account, employee_id: str | None) -> Employee | None:
    if not employee_id:
        return None
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project manager not found")
    if not employee.is_active or employee.role != Role.PROJECT_MANAGER:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Project manager must be an active Project Manager",
        )
    # A PM is eligible when they report to the account's program manager/director,
    # or already manage another project under the same account.
    already_in_account = db.scalar(
        select(Project.id).where(
            Project.account_id == account.id,
            Project.project_manager_id == employee.id,
        ).limit(1)
    )
    if account.program_manager_id and employee.manager_id != account.program_manager_id and not already_in_account:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Project manager is not associated with the selected account",
        )
    return employee


def report_project_ids(scope: str) -> set[str]:
    return {
        token.split(":", 1)[1]
        for token in scope.split()
        if token.startswith("project:") and len(token.split(":", 1)) == 2
    }


def report_account_ids(scope: str) -> set[str]:
    return {
        token.split(":", 1)[1]
        for token in scope.split()
        if token.startswith("account:") and len(token.split(":", 1)) == 2
    }


def can_view_report(db: Session, user: Employee, scope: str) -> bool:
    if is_studio_head(user):
        return True
    projects = report_project_ids(scope)
    accounts = report_account_ids(scope)
    if projects and not projects.issubset(visible_project_ids(db, user)):
        return False
    if accounts and not accounts.issubset(visible_account_ids(db, user)):
        return False
    return bool(projects or accounts)
