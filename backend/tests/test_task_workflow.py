from __future__ import annotations

from datetime import date, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.main import app
from app.models.people import Employee
from app.models.status import AuditLog


def _employees_by_email(*emails: str) -> dict[str, Employee]:
    with SessionLocal() as db:
        employees = db.scalars(select(Employee).where(Employee.email.in_(emails))).all()
        return {employee.email: employee for employee in employees}


def _headers(employee: Employee) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(employee.id)}"}


def test_account_project_allocation_task_kanban_workflow_and_rbac() -> None:
    people = _employees_by_email(
        "praveen.baburaya@delta.com",
        "gowtham.rallabandi@delta.com",
        "shanmukha.rewal@delta.com",
        "amrita.kumari@delta.com",
        "maria.chen@trimble.com",
        "deepak.sharma@delta.com",
        "sneha.patil@delta.com",
        "karthik.venkat@delta.com",
        "manoj.kumar@delta.com",
    )
    studio_head = people["praveen.baburaya@delta.com"]
    account_manager = people["gowtham.rallabandi@delta.com"]
    project_manager = people["shanmukha.rewal@delta.com"]
    replacement_pm = people["amrita.kumari@delta.com"]
    unrelated_pm = people["maria.chen@trimble.com"]
    primary_developer = people["deepak.sharma@delta.com"]
    second_developer = people["sneha.patil@delta.com"]
    unassigned_developer = people["karthik.venkat@delta.com"]
    unallocated_developer = people["manoj.kumar@delta.com"]

    suffix = uuid4().hex[:8]
    today = date.today()

    with TestClient(app) as client:
        account_response = client.post(
            "/api/v1/governance/accounts",
            headers=_headers(studio_head),
            json={
                "name": f"Task Workflow Account {suffix}",
                "industry": "Technology",
                "country": "India",
                "business_unit": "Engineering",
                "program_manager_id": account_manager.id,
                "start_date": today.isoformat(),
            },
        )
        assert account_response.status_code == 201, account_response.text
        account_id = account_response.json()["id"]
        assert account_response.json()["delivery_head_id"] == studio_head.id

        forbidden_account = client.post(
            "/api/v1/governance/accounts",
            headers=_headers(account_manager),
            json={
                "name": f"Forbidden Account {suffix}",
                "industry": "Technology",
                "country": "India",
                "business_unit": "Engineering",
                "program_manager_id": account_manager.id,
            },
        )
        assert forbidden_account.status_code == 403

        project_response = client.post(
            "/api/v1/governance/projects",
            headers=_headers(account_manager),
            json={
                "account_id": account_id,
                "name": f"Task Workflow Project {suffix}",
                "project_manager_id": project_manager.id,
                "phase": "development",
                "start_date": today.isoformat(),
                "end_date": (today + timedelta(days=90)).isoformat(),
                "description": "Integration test project for the persistent task workflow.",
            },
        )
        assert project_response.status_code == 201, project_response.text
        project_id = project_response.json()["id"]
        assert project_response.json()["account_id"] == account_id
        assert project_response.json()["program_manager_id"] == account_manager.id
        assert project_response.json()["project_manager_id"] == project_manager.id

        forbidden_project = client.post(
            "/api/v1/governance/projects",
            headers=_headers(project_manager),
            json={
                "account_id": account_id,
                "name": f"Forbidden Project {suffix}",
                "project_manager_id": project_manager.id,
            },
        )
        assert forbidden_project.status_code == 403

        for developer in (primary_developer, second_developer, unassigned_developer):
            allocation_response = client.post(
                "/api/v1/governance/allocations",
                headers=_headers(account_manager),
                json={
                    "project_id": project_id,
                    "employee_id": developer.id,
                    "allocation_role": "developer",
                    "allocation_percent": 100,
                    "start_date": today.isoformat(),
                    "reporting_manager_id": project_manager.id,
                },
            )
            assert allocation_response.status_code == 201, allocation_response.text

        eligible_response = client.get(
            f"/api/v1/tasks/projects/{project_id}/eligible-assignees",
            headers=_headers(project_manager),
        )
        assert eligible_response.status_code == 200
        eligible_ids = {employee["id"] for employee in eligible_response.json()}
        assert {primary_developer.id, second_developer.id, unassigned_developer.id}.issubset(eligible_ids)
        assert unallocated_developer.id not in eligible_ids

        invalid_assignment = client.post(
            "/api/v1/tasks",
            headers=_headers(project_manager),
            json={
                "project_id": project_id,
                "title": f"Invalid Assignment {suffix}",
                "assignee_id": unallocated_developer.id,
            },
        )
        assert invalid_assignment.status_code == 422
        assert invalid_assignment.json()["detail"] == "The selected developer is not allocated to this project."

        task_response = client.post(
            "/api/v1/tasks",
            headers=_headers(project_manager),
            json={
                "project_id": project_id,
                "title": f"Persistent Kanban Task {suffix}",
                "description": "Moves through the stored Kanban workflow.",
                "task_type": "development",
                "priority": "high",
                "status": "todo",
                "assignee_id": primary_developer.id,
                "assignee_ids": [primary_developer.id, second_developer.id],
                "start_date": today.isoformat(),
                "due_date": (today + timedelta(days=14)).isoformat(),
                "estimate_hours": 16,
                "labels": ["integration", "kanban"],
            },
        )
        assert task_response.status_code == 201, task_response.text
        task = task_response.json()
        task_id = task["id"]
        assert task["account_id"] == account_id
        assert task["account_name"] == account_response.json()["name"]
        assert task["project_id"] == project_id
        assert task["task_type"] == "development"
        assert set(task["assignee_ids"]) == {primary_developer.id, second_developer.id}
        assert task["reporter_id"] == project_manager.id

        filtered = client.get(
            "/api/v1/tasks",
            headers=_headers(project_manager),
            params={
                "account_id": account_id,
                "project_id": project_id,
                "assignee_id": second_developer.id,
                "reporter_id": project_manager.id,
                "task_status": "todo",
                "priority": "high",
                "task_type": "development",
            },
        )
        assert filtered.status_code == 200
        assert [item["id"] for item in filtered.json()] == [task_id]

        primary_tasks = client.get("/api/v1/tasks", headers=_headers(primary_developer))
        second_tasks = client.get("/api/v1/tasks", headers=_headers(second_developer))
        unassigned_tasks = client.get("/api/v1/tasks", headers=_headers(unassigned_developer))
        assert task_id in {item["id"] for item in primary_tasks.json()}
        assert task_id in {item["id"] for item in second_tasks.json()}
        assert task_id not in {item["id"] for item in unassigned_tasks.json()}
        assert client.get(f"/api/v1/tasks/{task_id}", headers=_headers(unassigned_developer)).status_code == 404
        assert client.get(f"/api/v1/tasks/{task_id}", headers=_headers(unrelated_pm)).status_code == 404

        for next_status in ("in_progress", "review", "done"):
            moved = client.put(
                f"/api/v1/tasks/{task_id}/status",
                headers=_headers(primary_developer),
                json={"status": next_status},
            )
            assert moved.status_code == 200, moved.text
            assert moved.json()["status"] == next_status

            persisted = client.get(f"/api/v1/tasks/{task_id}", headers=_headers(project_manager))
            assert persisted.status_code == 200
            assert persisted.json()["status"] == next_status

        updated_task = client.put(
            f"/api/v1/tasks/{task_id}",
            headers=_headers(project_manager),
            json={
                "priority": "critical",
                "due_date": (today + timedelta(days=21)).isoformat(),
                "assignee_id": second_developer.id,
                "assignee_ids": [second_developer.id],
            },
        )
        assert updated_task.status_code == 200, updated_task.text
        assert updated_task.json()["priority"] == "critical"
        assert updated_task.json()["due_date"] == (today + timedelta(days=21)).isoformat()
        assert updated_task.json()["assignee_id"] == second_developer.id
        assert updated_task.json()["assignee_ids"] == [second_developer.id]

        cannot_reassign_manager = client.put(
            f"/api/v1/governance/projects/{project_id}",
            headers=_headers(project_manager),
            json={"project_manager_id": replacement_pm.id},
        )
        assert cannot_reassign_manager.status_code == 403

    with SessionLocal() as db:
        actions = set(
            db.scalars(
                select(AuditLog.action).where(
                    AuditLog.module == "Task Tracker",
                    AuditLog.details.contains(f"Persistent Kanban Task {suffix}"),
                )
            ).all()
        )
    assert {
        "Task Created",
        "Task Assigned",
        "Task Reassigned",
        "Task Status Updated",
        "Task Priority Changed",
        "Task Due Date Changed",
        "Task Completed",
    }.issubset(actions)
