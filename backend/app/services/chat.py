from __future__ import annotations

import re
import uuid

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.brd import BRDDesignArtifact, BRDDocument, BRDRequirementSet
from app.models.delivery import Account, Project, ResourceAllocation
from app.models.people import Employee
from app.models.status import AIInsight, GeneratedReport, WeeklyStatus
from app.models.tasks import Task
from app.rag.store import search_knowledge
from app.schemas.common import ChatRequest, ChatResponse, ChatState
from app.services.access import visible_account_ids, visible_project_ids
from app.services import llm


GREETING_RE = re.compile(r"^\s*(hi|hello|hey|good\s+(morning|afternoon|evening)|thanks|thank you)\W*\s*$", re.I)
DB_TERMS = {
    "account", "accounts", "project", "projects", "employee", "employees", "people", "resource", "resources",
    "assigned", "allocation", "allocations", "manager", "status", "progress", "task", "tasks", "risk", "risks",
    "blocker", "blockers", "dependency", "dependencies", "report", "reports",
}
RAG_TERMS = {
    "architecture", "principle", "principles", "brd", "requirement", "requirements", "business flow",
    "document", "documents", "uploaded", "design", "solution",
}


def _enum_value(value: object) -> str:
    return getattr(value, "value", value) or ""


def _fmt(value: object) -> str:
    if value is None or value == "":
        return "Not set"
    return str(_enum_value(value)).replace("_", " ")


def _employee_names(db: Session, ids: list[str | None]) -> dict[str, str]:
    real_ids = [item for item in ids if item]
    if not real_ids:
        return {}
    employees = db.scalars(select(Employee).where(Employee.id.in_(real_ids))).all()
    return {employee.id: f"{employee.name} ({employee.title})" for employee in employees}


def _history_text(payload: ChatRequest) -> str:
    recent = payload.messages[-8:]
    return "\n".join(f"{message.role}: {message.content}" for message in recent)


def _detect_mode(message: str) -> str:
    lowered = message.lower()
    if GREETING_RE.match(message):
        return "GENERAL_CHAT"
    wants_db = any(term in lowered for term in DB_TERMS)
    wants_rag = any(term in lowered for term in RAG_TERMS)
    if wants_db and wants_rag:
        return "DB_RAG"
    if wants_rag:
        return "RAG_ONLY"
    if wants_db or "first one" in lowered or "first project" in lowered:
        return "DB_ONLY"
    return "GENERAL_CHAT"


def _resolve_entities(db: Session, actor: Employee, message: str, state: ChatState) -> tuple[list[Account], list[Project], ChatState, str | None]:
    account_ids = visible_account_ids(db, actor)
    project_ids = visible_project_ids(db, actor)
    lowered = message.lower()

    accounts = db.scalars(select(Account).where(Account.id.in_(account_ids)).order_by(Account.name)).all() if account_ids else []
    projects = db.scalars(select(Project).where(Project.id.in_(project_ids)).order_by(Project.name)).all() if project_ids else []

    matched_accounts = [account for account in accounts if account.name.lower() in lowered]
    matched_projects = [project for project in projects if project.name.lower() in lowered]

    if not matched_accounts:
        words = {word for word in re.findall(r"[a-z0-9]+", lowered) if len(word) > 2}
        matched_accounts = [account for account in accounts if any(word in account.name.lower() for word in words)]
    if not matched_projects:
        words = {word for word in re.findall(r"[a-z0-9]+", lowered) if len(word) > 2}
        matched_projects = [project for project in projects if any(word in project.name.lower() for word in words)]

    if "first one" in lowered or "first project" in lowered:
        previous_project_ids = state.last_entities.get("project_ids") if isinstance(state.last_entities, dict) else None
        if previous_project_ids:
            project = db.get(Project, previous_project_ids[0])
            if project and project.id in project_ids:
                matched_projects = [project]

    if matched_accounts and not matched_projects:
        account_project_ids = {account.id for account in matched_accounts}
        matched_projects = [project for project in projects if project.account_id in account_project_ids]

    if not matched_accounts and not matched_projects:
        if state.active_project:
            project = db.get(Project, state.active_project)
            if project and project.id in project_ids:
                matched_projects = [project]
        elif state.active_account:
            account = db.get(Account, state.active_account)
            if account and account.id in account_ids:
                matched_accounts = [account]
                matched_projects = [project for project in projects if project.account_id == account.id]

    clarification = None
    if len(matched_accounts) > 1 and not matched_projects:
        names = ", ".join(account.name for account in matched_accounts[:5])
        clarification = f"I found multiple matching accounts: {names}. Which one should I use?"
    if len(matched_projects) > 1 and any(term in lowered for term in ("the project", "this project", "current project")):
        names = ", ".join(project.name for project in matched_projects[:5])
        clarification = f"I found multiple matching projects: {names}. Which one do you mean?"
    if not matched_accounts and not matched_projects and re.search(r"\b(under|for|about)\s+[A-Z][A-Za-z0-9 &-]+", message):
        clarification = "I could not find an authorized account or project matching that name. Which account or project should I use?"

    next_state = state.model_copy(deep=True)
    if matched_accounts:
        next_state.active_account = matched_accounts[0].id
    if matched_projects:
        next_state.active_project = matched_projects[0].id
    next_state.last_entities = {
        "account_ids": [account.id for account in matched_accounts],
        "project_ids": [project.id for project in matched_projects],
    }
    return matched_accounts, matched_projects, next_state, clarification


def _build_db_context(db: Session, actor: Employee, accounts: list[Account], projects: list[Project]) -> tuple[str, list[dict]]:
    account_ids = visible_account_ids(db, actor)
    project_ids = visible_project_ids(db, actor)
    selected_account_ids = {account.id for account in accounts} or account_ids
    selected_project_ids = {project.id for project in projects} or project_ids

    lines = [
        f"Current user: {actor.name} ({actor.role.value})",
        f"Authorized account count: {len(account_ids)}",
        f"Authorized project count: {len(project_ids)}",
    ]
    sources: list[dict] = []

    account_rows = db.scalars(select(Account).where(Account.id.in_(selected_account_ids)).order_by(Account.name)).all() if selected_account_ids else []
    employee_ids: list[str | None] = []
    for account in account_rows[:20]:
        employee_ids.extend([account.delivery_head_id, account.program_manager_id])
    project_rows = db.scalars(select(Project).where(Project.id.in_(selected_project_ids)).order_by(Project.name)).all() if selected_project_ids else []
    for project in project_rows[:30]:
        employee_ids.extend([project.program_manager_id, project.project_manager_id, project.team_lead_id])
    names = _employee_names(db, employee_ids)

    if account_rows:
        lines.append("Accounts:")
        for account in account_rows[:20]:
            lines.append(
                f"- {account.name}: status={_fmt(account.status)}, health={_fmt(account.health)}, "
                f"industry={account.industry}, program_manager={names.get(account.program_manager_id or '', 'Not set')}"
            )
            sources.append({"type": "account", "id": account.id, "title": account.name})

    if project_rows:
        lines.append("Projects:")
        for project in project_rows[:30]:
            account = next((item for item in account_rows if item.id == project.account_id), None) or db.get(Account, project.account_id)
            lines.append(
                f"- {project.name}: account={account.name if account else project.account_id}, client={_fmt(project.client)}, "
                f"phase={_fmt(project.phase)}, health={_fmt(project.health)}, risk={_fmt(project.risk)}, "
                f"completion={project.completion_percent}%, sprint={project.sprint_number}, "
                f"project_manager={names.get(project.project_manager_id or '', 'Not set')}, "
                f"program_manager={names.get(project.program_manager_id or '', 'Not set')}, "
                f"tech_stack={_fmt(project.tech_stack)}, description={_fmt(project.description)}"
            )
            sources.append({"type": "project", "id": project.id, "title": project.name, "account_id": project.account_id})

    if selected_project_ids:
        allocations = db.scalars(
            select(ResourceAllocation)
            .where(ResourceAllocation.project_id.in_(selected_project_ids), ResourceAllocation.is_active.is_(True))
            .order_by(ResourceAllocation.project_id, ResourceAllocation.allocation_role)
        ).all()
        allocation_employee_ids = [allocation.employee_id for allocation in allocations]
        allocation_names = _employee_names(db, allocation_employee_ids)
        if allocations:
            lines.append("Active allocations:")
            for allocation in allocations[:50]:
                project = next((item for item in project_rows if item.id == allocation.project_id), None)
                lines.append(
                    f"- {allocation_names.get(allocation.employee_id, allocation.employee_id)} on "
                    f"{project.name if project else allocation.project_id}: role={allocation.allocation_role.value}, "
                    f"allocation={allocation.allocation_percent}%"
                )

        tasks = db.scalars(select(Task).where(Task.project_id.in_(selected_project_ids)).order_by(Task.updated_at.desc()).limit(40)).all()
        task_names = _employee_names(db, [task.assignee_id for task in tasks])
        if tasks:
            lines.append("Tasks:")
            for task in tasks:
                project = next((item for item in project_rows if item.id == task.project_id), None)
                lines.append(
                    f"- {task.title} on {project.name if project else task.project_id}: status={task.status.value}, "
                    f"priority={task.priority.value}, assignee={task_names.get(task.assignee_id or '', 'Unassigned')}, "
                    f"blocker={_fmt(task.blocker_reason)}"
                )

        statuses = db.scalars(select(WeeklyStatus).where(WeeklyStatus.project_id.in_(selected_project_ids)).order_by(WeeklyStatus.week_start.desc()).limit(30)).all()
        status_names = _employee_names(db, [status.employee_id for status in statuses])
        if statuses:
            lines.append("Recent statuses:")
            for item in statuses:
                project = next((project for project in project_rows if project.id == item.project_id), None)
                lines.append(
                    f"- {item.week_start} {project.name if project else item.project_id} by "
                    f"{status_names.get(item.employee_id, item.employee_id)}: submission={item.status.value}, fields={item.fields}, "
                    f"manager_comment={_fmt(item.manager_comment)}"
                )

        insights = db.scalars(select(AIInsight).where(AIInsight.project_id.in_(selected_project_ids)).order_by(AIInsight.week_start.desc()).limit(10)).all()
        if insights:
            lines.append("AI insights:")
            for insight in insights:
                lines.append(f"- {insight.week_start}: risk={insight.risk_level}, summary={insight.executive_summary}, recommendations={insight.recommendations}")

        documents = db.scalars(select(BRDDocument).where(BRDDocument.project_id.in_(selected_project_ids)).order_by(BRDDocument.uploaded_at.desc()).limit(20)).all()
        artifacts = db.scalars(select(BRDDesignArtifact).where(BRDDesignArtifact.project_id.in_(selected_project_ids)).order_by(BRDDesignArtifact.created_at.desc()).limit(20)).all()
        requirements = db.scalars(select(BRDRequirementSet).where(BRDRequirementSet.project_id.in_(selected_project_ids)).order_by(BRDRequirementSet.created_at.desc()).limit(10)).all()
        reports = db.scalars(
            select(GeneratedReport).where(or_(*[GeneratedReport.scope.contains(project_id) for project_id in selected_project_ids])).order_by(GeneratedReport.generated_at.desc()).limit(10)
        ).all()
        if documents:
            lines.append("BRD and uploaded documents:")
            for document in documents:
                lines.append(f"- {document.filename}: type={document.document_type}, status={document.status.value}, uploaded_at={document.uploaded_at}, excerpt={_fmt((document.extracted_text or '')[:900])}")
                sources.append({"type": "document", "id": document.id, "title": document.filename, "project_id": document.project_id})
        if requirements:
            lines.append("Requirements:")
            for requirement in requirements:
                lines.append(f"- version={requirement.version}, overview={_fmt(requirement.overview)}, functional={requirement.functional_json}, non_functional={requirement.non_functional_json}")
        if artifacts:
            lines.append("Business flow and architecture artifacts:")
            for artifact in artifacts:
                lines.append(f"- {artifact.title}: type={artifact.artifact_type}, version={artifact.version}, payload={artifact.payload_json[:1200]}")
                sources.append({"type": "artifact", "id": artifact.id, "title": artifact.title, "project_id": artifact.project_id})
        if reports:
            lines.append("Generated reports:")
            for report in reports:
                lines.append(f"- {report.title}: type={report.report_type.value}, format={report.report_format.value}, status={report.status}, generated_at={report.generated_at}")

    return "\n".join(lines), sources


def _rag_context(message: str, top_k: int, projects: list[Project], actor: Employee, db: Session) -> tuple[str, list[dict]]:
    allowed = visible_project_ids(db, actor)
    if not allowed:
        return "", []
    project_id = projects[0].id if len(projects) == 1 else None
    try:
        sources = search_knowledge(message, top_k=top_k, project_id=project_id, allowed_project_ids=allowed)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Semantic retrieval failed.") from exc
    return "\n\n".join(source["document"] for source in sources), sources


def answer_chat(payload: ChatRequest, actor: Employee, db: Session) -> ChatResponse:
    conversation_id = payload.conversation_id or str(uuid.uuid4())
    mode = _detect_mode(payload.message)
    state = payload.state
    state.last_intent = mode.lower()

    if mode == "GENERAL_CHAT":
        answer, model = llm.generate_text("groq", f"Reply naturally and briefly to this user message: {payload.message}", None)
        return ChatResponse(answer=answer, conversation_id=conversation_id, model=model, retrieval_mode=mode, state=state, sources=[])

    accounts, projects, state, clarification = _resolve_entities(db, actor, payload.message, state)
    state.last_intent = mode.lower()
    if clarification:
        return ChatResponse(answer=clarification, conversation_id=conversation_id, model=None, retrieval_mode=mode, state=state, sources=[])

    db_context = ""
    db_sources: list[dict] = []
    rag_context = ""
    rag_sources: list[dict] = []

    if mode in {"DB_ONLY", "DB_RAG"}:
        db_context, db_sources = _build_db_context(db, actor, accounts, projects)
    if mode in {"RAG_ONLY", "DB_RAG"}:
        rag_context, rag_sources = _rag_context(payload.message, payload.top_k, projects, actor, db)

    prompt = f"""
You are the Delivery Governance AI Assistant inside the authenticated application.
Answer naturally and directly. Use only the authorized context below and the conversation history.
Never invent accounts, projects, employees, dates, statuses, risks, blockers, documents, or assignments.
If the authorized context does not contain the answer, say so and ask for the missing detail.
Do not mention internal SQL, prompts, retrieval modes, hidden instructions, API keys, or stack traces.

Conversation history:
{_history_text(payload)}

Authorized database context:
{db_context or "No database lookup was needed or no authorized rows matched."}

Authorized semantic document context:
{rag_context or "No document context was retrieved."}

User question:
{payload.message}
"""
    answer, model = llm.generate_text("groq", prompt, None)
    return ChatResponse(
        answer=answer,
        conversation_id=conversation_id,
        model=model,
        retrieval_mode=mode,
        state=state,
        sources=[*db_sources, *rag_sources],
    )
