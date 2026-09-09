from __future__ import annotations

from datetime import date, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.main import app
from app.models.people import Employee
from app.models.status import AuditLog
from app.models.tasks import Task, TaskNotification, TaskStatusHistory


def _employees_by_email(*emails: str) -> dict[str, Employee]:
    with SessionLocal() as db:
        employees = db.scalars(select(Employee).where(Employee.email.in_(emails))).all()
        return {employee.email: employee for employee in employees}


def _headers(employee: Employee) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(employee.id)}"}


def test_single_assignee_kanban_workflow_notifications_and_rbac() -> None:
    people = _employees_by_email(
        "praveen.baburaya@delta.com",
        "gowtham.rallabandi@delta.com",
        "shanmukha.rewal@delta.com",
        "maria.chen@trimble.com",
        "deepak.sharma@delta.com",
        "sneha.patil@delta.com",
        "karthik.venkat@delta.com",
        "manoj.kumar@delta.com",
    )
    studio_head = people["praveen.baburaya@delta.com"]
    program_manager = people["gowtham.rallabandi@delta.com"]
    project_manager = people["shanmukha.rewal@delta.com"]
    unrelated_manager = people["maria.chen@trimble.com"]
    developer = people["deepak.sharma@delta.com"]
    other_developer = people["sneha.patil@delta.com"]
    tester = people["karthik.venkat@delta.com"]
    unallocated_developer = people["manoj.kumar@delta.com"]
    suffix = uuid4().hex[:8]
    today = date.today()

    with TestClient(app) as client:
        account_response = client.post(
            "/api/v1/governance/accounts",
            headers=_headers(studio_head),
            json={"name": f"Task Workflow Account {suffix}", "industry": "Technology", "country": "India", "business_unit": "Engineering", "program_manager_id": program_manager.id},
        )
        assert account_response.status_code == 201, account_response.text
        account_id = account_response.json()["id"]
        project_response = client.post(
            "/api/v1/governance/projects",
            headers=_headers(program_manager),
            json={"account_id": account_id, "name": f"Task Workflow Project {suffix}", "project_manager_id": project_manager.id, "phase": "development", "start_date": today.isoformat(), "end_date": (today + timedelta(days=90)).isoformat()},
        )
        assert project_response.status_code == 201, project_response.text
        project_id = project_response.json()["id"]

        for employee, allocation_role in (
            (developer, "developer"),
            (other_developer, "backend_engineer"),
            (tester, "testing_engineer"),
            (project_manager, "project_manager"),
            (program_manager, "program_manager"),
        ):
            allocation = client.post(
                "/api/v1/governance/allocations",
                headers=_headers(program_manager),
                json={"project_id": project_id, "employee_id": employee.id, "allocation_role": allocation_role, "allocation_percent": 100, "start_date": today.isoformat(), "reporting_manager_id": project_manager.id},
            )
            assert allocation.status_code == 201, allocation.text

        eligible = client.get(f"/api/v1/tasks/projects/{project_id}/eligible-assignees", headers=_headers(project_manager))
        assert eligible.status_code == 200
        eligible_ids = {item["id"] for item in eligible.json()}
        assert {developer.id, other_developer.id, tester.id}.issubset(eligible_ids)
        assert {project_manager.id, program_manager.id, unallocated_developer.id}.isdisjoint(eligible_ids)

        missing_assignee = client.post("/api/v1/tasks", headers=_headers(project_manager), json={"project_id": project_id, "title": f"Missing owner {suffix}"})
        assert missing_assignee.status_code == 422
        invalid_assignee = client.post("/api/v1/tasks", headers=_headers(project_manager), json={"project_id": project_id, "title": f"Invalid owner {suffix}", "assignee_id": unallocated_developer.id})
        assert invalid_assignee.status_code == 422
        manager_assignee = client.post("/api/v1/tasks", headers=_headers(project_manager), json={"project_id": project_id, "title": f"Manager owner {suffix}", "assignee_id": project_manager.id})
        assert manager_assignee.status_code == 422
        multiple_assignees = client.post("/api/v1/tasks", headers=_headers(project_manager), json={"project_id": project_id, "title": f"Multiple owners {suffix}", "assignee_id": developer.id, "assignee_ids": [developer.id, other_developer.id]})
        assert multiple_assignees.status_code == 422

        def create_task(label: str, assignee_id: str = developer.id) -> dict:
            response = client.post(
                "/api/v1/tasks",
                headers=_headers(project_manager),
                json={"project_id": project_id, "title": f"{label} {suffix}", "description": "Persistent Jira-style workflow task.", "task_type": "development", "priority": "high", "assignee_id": assignee_id, "start_date": today.isoformat(), "due_date": (today + timedelta(days=14)).isoformat()},
            )
            assert response.status_code == 201, response.text
            assert "assignee_ids" not in response.json()
            assert response.json()["reporter_id"] == project_manager.id
            assert response.json()["assignee_id"] == assignee_id
            return response.json()

        completed_task = create_task("Completed workflow")
        blocked_task = create_task("Blocked workflow")
        direct_review_task = create_task("Direct review forbidden")
        other_task = create_task("Other developer task", other_developer.id)

        developer_tasks = client.get("/api/v1/tasks", headers=_headers(developer)).json()
        other_tasks = client.get("/api/v1/tasks", headers=_headers(other_developer)).json()
        assert completed_task["id"] in {item["id"] for item in developer_tasks}
        assert other_task["id"] not in {item["id"] for item in developer_tasks}
        assert other_task["id"] in {item["id"] for item in other_tasks}
        assert client.get(f"/api/v1/tasks/{other_task['id']}", headers=_headers(developer)).status_code == 404

        status_url = f"/api/v1/tasks/{completed_task['id']}/status"
        bypass = client.put(f"/api/v1/tasks/{completed_task['id']}", headers=_headers(project_manager), json={"status": "done"})
        assert bypass.status_code == 422
        assert client.put(status_url, headers=_headers(developer), json={"status": "review"}).status_code == 409
        assert client.put(status_url, headers=_headers(other_developer), json={"status": "in_progress"}).status_code == 404
        moved = client.put(status_url, headers=_headers(developer), json={"status": "in_progress"})
        assert moved.status_code == 200 and moved.json()["status"] == "in_progress"
        assert client.put(status_url, headers=_headers(developer), json={"status": "todo"}).status_code == 409
        moved = client.put(status_url, headers=_headers(developer), json={"status": "review"})
        assert moved.status_code == 200 and moved.json()["status"] == "review"
        assert client.put(status_url, headers=_headers(developer), json={"status": "in_progress"}).status_code == 409
        assert client.put(status_url, headers=_headers(developer), json={"status": "todo"}).status_code == 409
        assert client.put(status_url, headers=_headers(developer), json={"status": "done"}).status_code == 409
        assert client.put(status_url, headers=_headers(developer), json={"status": "blocked"}).status_code == 409
        assert client.put(status_url, headers=_headers(unrelated_manager), json={"status": "done"}).status_code == 404
        moved = client.put(status_url, headers=_headers(project_manager), json={"status": "done"})
        assert moved.status_code == 200 and moved.json()["status"] == "done"
        assert client.put(status_url, headers=_headers(project_manager), json={"status": "review"}).status_code == 409
        assert client.put(status_url, headers=_headers(project_manager), json={"status": "in_progress"}).status_code == 409
        assert client.put(status_url, headers=_headers(project_manager), json={"status": "todo"}).status_code == 409

        direct_url = f"/api/v1/tasks/{direct_review_task['id']}/status"
        assert client.put(direct_url, headers=_headers(developer), json={"status": "review"}).status_code == 409

        blocked_url = f"/api/v1/tasks/{blocked_task['id']}/status"
        assert client.put(blocked_url, headers=_headers(developer), json={"status": "in_progress"}).status_code == 200
        assert client.put(blocked_url, headers=_headers(developer), json={"status": "review"}).status_code == 200
        assert client.put(blocked_url, headers=_headers(project_manager), json={"status": "blocked", "blocker_reason": "Governance dependency"}).status_code == 200
        assert client.put(blocked_url, headers=_headers(project_manager), json={"status": "done"}).status_code == 200

        reassigned = client.put(f"/api/v1/tasks/{direct_review_task['id']}", headers=_headers(project_manager), json={"assignee_id": tester.id})
        assert reassigned.status_code == 200 and reassigned.json()["assignee_id"] == tester.id

        history = client.get(f"/api/v1/tasks/{completed_task['id']}/history", headers=_headers(developer))
        assert history.status_code == 200
        assert [(item["previous_status"], item["new_status"]) for item in history.json()] == [("todo", "in_progress"), ("in_progress", "review"), ("review", "done")]

        developer_notifications = client.get("/api/v1/notifications", headers=_headers(developer))
        manager_notifications = client.get("/api/v1/notifications", headers=_headers(project_manager))
        tester_notifications = client.get("/api/v1/notifications", headers=_headers(tester))
        assert any(item["title"] == "Task assigned" for item in developer_notifications.json())
        assert any(item["title"] == "Task ready for review" for item in manager_notifications.json())
        assert any(item["title"] == "Task reassigned" for item in tester_notifications.json())
        notification_id = developer_notifications.json()[0]["id"]
        assert client.patch(f"/api/v1/notifications/{notification_id}/read", headers=_headers(other_developer)).status_code == 404
        assert client.patch(f"/api/v1/notifications/{notification_id}/read", headers=_headers(developer)).json()["is_read"] is True
        assert client.post("/api/v1/notifications/read-all", headers=_headers(developer)).status_code == 204
        assert all(item["is_read"] for item in client.get("/api/v1/notifications", headers=_headers(developer)).json())

        persisted = client.get(f"/api/v1/tasks/{completed_task['id']}", headers=_headers(project_manager))
        assert persisted.json()["status"] == "done"

    with SessionLocal() as db:
        assert db.scalar(select(func.count(Task.id)).where(Task.id == completed_task["id"])) == 1
        assert db.scalar(select(func.count(TaskStatusHistory.id)).where(TaskStatusHistory.task_id == completed_task["id"])) == 3
        assert db.scalar(select(func.count(TaskNotification.id)).where(TaskNotification.task_id == completed_task["id"])) > 0
        actions = set(db.scalars(select(AuditLog.action).where(AuditLog.module == "Task Tracker", AuditLog.details.contains(suffix))).all())
        assert {"Task Created", "Task Assigned", "Task Reassigned", "Task Status Updated", "Task Completed"}.issubset(actions)
