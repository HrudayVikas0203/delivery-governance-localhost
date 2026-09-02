"""
Production-quality governance chatbot service.

Implements:
- Entity resolution (accounts, projects, employees)
- Conversation memory and context
- Hybrid retrieval (database + RAG)
- RBAC enforcement
- Natural language response generation
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.delivery import Account, AllocationRole, Project, ResourceAllocation
from app.models.people import Employee, Role
from app.models.status import WeeklyStatus
from app.rag.store import search_knowledge
from app.services.access import visible_account_ids, visible_project_ids
from app.services.llm import generate_text

logger = logging.getLogger(__name__)


@dataclass
class EntityResolutionResult:
    """Result of entity resolution."""
    entity_type: str  # "account", "project", "employee", "ambiguous", "not_found"
    resolved_ids: dict[str, Any] = field(default_factory=dict)  # id -> object
    ambiguous_matches: list[dict[str, Any]] = field(default_factory=list)
    query_text: str = ""


@dataclass
class ConversationContext:
    """Maintains conversation state across multiple turns."""
    active_account_id: str | None = None
    active_project_id: str | None = None
    active_employee_id: str | None = None
    active_task_id: str | None = None
    active_date_range: tuple[date, date] | None = None
    last_intent: str | None = None
    last_retrieved_entities: dict[str, Any] = field(default_factory=dict)
    message_history: list[dict[str, str]] = field(default_factory=list)

    def update_from_resolution(self, resolution: EntityResolutionResult) -> None:
        """Update context based on entity resolution result."""
        if resolution.entity_type == "account" and resolution.resolved_ids:
            account_id = list(resolution.resolved_ids.keys())[0]
            self.active_account_id = account_id
            self.last_retrieved_entities["account"] = resolution.resolved_ids[account_id]
        elif resolution.entity_type == "project" and resolution.resolved_ids:
            project_id = list(resolution.resolved_ids.keys())[0]
            self.active_project_id = project_id
            self.last_retrieved_entities["project"] = resolution.resolved_ids[project_id]
        elif resolution.entity_type == "employee" and resolution.resolved_ids:
            employee_id = list(resolution.resolved_ids.keys())[0]
            self.active_employee_id = employee_id
            self.last_retrieved_entities["employee"] = resolution.resolved_ids[employee_id]


class EntityResolver:
    """Resolves natural language references to database entities."""

    def __init__(self, db: Session, actor: Employee):
        self.db = db
        self.actor = actor
        self.allowed_account_ids = visible_account_ids(db, actor)
        self.allowed_project_ids = visible_project_ids(db, actor)

    def resolve_account(self, query: str) -> EntityResolutionResult:
        """Resolve natural language query to account(s)."""
        query_normalized = query.lower().strip()
        
        if not self.allowed_account_ids:
            return EntityResolutionResult(
                entity_type="not_found",
                query_text=query,
            )

        # Fetch allowed accounts
        accounts = self.db.scalars(
            select(Account)
            .where(Account.id.in_(sorted(self.allowed_account_ids)))
            .order_by(Account.name)
        ).all()

        # Exact match
        for account in accounts:
            if account.name.lower() == query_normalized:
                return EntityResolutionResult(
                    entity_type="account",
                    resolved_ids={account.id: account},
                    query_text=query,
                )

        # Case-insensitive exact match
        for account in accounts:
            if account.name.lower() == query_normalized:
                return EntityResolutionResult(
                    entity_type="account",
                    resolved_ids={account.id: account},
                    query_text=query,
                )

        # Partial match
        partial_matches = [a for a in accounts if query_normalized in a.name.lower()]
        if len(partial_matches) == 1:
            account = partial_matches[0]
            return EntityResolutionResult(
                entity_type="account",
                resolved_ids={account.id: account},
                query_text=query,
            )
        elif len(partial_matches) > 1:
            return EntityResolutionResult(
                entity_type="ambiguous",
                ambiguous_matches=[{"id": a.id, "name": a.name} for a in partial_matches],
                query_text=query,
            )

        return EntityResolutionResult(
            entity_type="not_found",
            query_text=query,
        )

    def resolve_project(self, query: str) -> EntityResolutionResult:
        """Resolve natural language query to project(s)."""
        query_normalized = query.lower().strip()
        
        if not self.allowed_project_ids:
            return EntityResolutionResult(
                entity_type="not_found",
                query_text=query,
            )

        # Fetch allowed projects
        projects = self.db.scalars(
            select(Project)
            .where(Project.id.in_(sorted(self.allowed_project_ids)))
            .order_by(Project.name)
        ).all()

        # Exact match
        for project in projects:
            if project.name.lower() == query_normalized:
                return EntityResolutionResult(
                    entity_type="project",
                    resolved_ids={project.id: project},
                    query_text=query,
                )

        # Partial match
        partial_matches = [p for p in projects if query_normalized in p.name.lower()]
        if len(partial_matches) == 1:
            project = partial_matches[0]
            return EntityResolutionResult(
                entity_type="project",
                resolved_ids={project.id: project},
                query_text=query,
            )
        elif len(partial_matches) > 1:
            return EntityResolutionResult(
                entity_type="ambiguous",
                ambiguous_matches=[{"id": p.id, "name": p.name} for p in partial_matches],
                query_text=query,
            )

        return EntityResolutionResult(
            entity_type="not_found",
            query_text=query,
        )

    def resolve_employee(self, query: str) -> EntityResolutionResult:
        """Resolve natural language query to employee(s)."""
        query_normalized = query.lower().strip()

        # Fetch all employees (based on role visibility)
        employees = self.db.scalars(select(Employee).order_by(Employee.name)).all()

        # Exact name match
        for emp in employees:
            if emp.name.lower() == query_normalized:
                return EntityResolutionResult(
                    entity_type="employee",
                    resolved_ids={emp.id: emp},
                    query_text=query,
                )

        # Partial name match
        partial_matches = [e for e in employees if query_normalized in e.name.lower()]
        if len(partial_matches) == 1:
            emp = partial_matches[0]
            return EntityResolutionResult(
                entity_type="employee",
                resolved_ids={emp.id: emp},
                query_text=query,
            )
        elif len(partial_matches) > 1:
            return EntityResolutionResult(
                entity_type="ambiguous",
                ambiguous_matches=[{"id": e.id, "name": e.name} for e in partial_matches],
                query_text=query,
            )

        return EntityResolutionResult(
            entity_type="not_found",
            query_text=query,
        )


class GovernanceChatbot:
    """Production governance chatbot powered by Groq."""

    def __init__(self, db: Session, actor: Employee, conversation_context: ConversationContext | None = None):
        self.db = db
        self.actor = actor
        self.context = conversation_context or ConversationContext()
        self.resolver = EntityResolver(db, actor)
        self.settings = get_settings()

    def _extract_entities_from_query(self, question: str) -> dict[str, Any]:
        """Extract entity references from user question."""
        entities: dict[str, Any] = {}
        
        # Look for account names
        for account_id in self.resolver.allowed_account_ids:
            account = self.db.get(Account, account_id)
            if account and account.name.lower() in question.lower():
                entities.setdefault("accounts", []).append({
                    "id": account.id,
                    "name": account.name
                })

        # Look for project names
        for project_id in self.resolver.allowed_project_ids:
            project = self.db.get(Project, project_id)
            if project and project.name.lower() in question.lower():
                entities.setdefault("projects", []).append({
                    "id": project.id,
                    "name": project.name,
                    "account_id": project.account_id
                })

        return entities

    def _determine_intent(self, question: str) -> str:
        """Determine the intent of the user's question."""
        q_lower = question.lower()
        
        intents = {
            "list": ["list", "show", "get", "display"],
            "count": ["how many", "count", "total"],
            "status": ["status", "health", "phase"],
            "assignment": ["assigned", "allocation", "resource", "team", "who"],
            "tasks": ["task", "todo", "work item"],
            "risks": ["risk", "blocker", "issue", "problem"],
            "timeline": ["deadline", "timeline", "schedule", "date"],
            "details": ["details", "info", "information", "explain", "describe"],
            "search": ["search", "find", "look for"],
        }

        for intent, keywords in intents.items():
            if any(keyword in q_lower for keyword in keywords):
                return intent
        
        return "general"

    def _retrieve_account_data(self, account_id: str) -> dict[str, Any]:
        """Retrieve comprehensive account information."""
        account = self.db.get(Account, account_id)
        if not account:
            return {}

        projects = self.db.scalars(
            select(Project).where(Project.account_id == account_id)
        ).all()

        program_manager = None
        if account.program_manager_id:
            program_manager = self.db.get(Employee, account.program_manager_id)

        return {
            "account": account,
            "projects": projects,
            "program_manager": program_manager,
            "project_count": len(projects),
        }

    def _retrieve_project_data(self, project_id: str) -> dict[str, Any]:
        """Retrieve comprehensive project information."""
        project = self.db.get(Project, project_id)
        if not project:
            return {}

        account = self.db.get(Account, project.account_id)
        
        allocations = self.db.scalars(
            select(ResourceAllocation)
            .where(ResourceAllocation.project_id == project_id, ResourceAllocation.is_active.is_(True))
        ).all()

        employees_by_role = {}
        for alloc in allocations:
            emp = self.db.get(Employee, alloc.employee_id)
            if emp:
                role = alloc.allocation_role.value
                if role not in employees_by_role:
                    employees_by_role[role] = []
                employees_by_role[role].append({
                    "name": emp.name,
                    "role": role,
                    "percent": alloc.allocation_percent
                })

        project_manager = None
        if project.project_manager_id:
            project_manager = self.db.get(Employee, project.project_manager_id)

        # Get recent status
        latest_status = self.db.scalars(
            select(WeeklyStatus)
            .where(WeeklyStatus.project_id == project_id)
            .order_by(WeeklyStatus.week_start.desc())
            .limit(1)
        ).first()

        return {
            "project": project,
            "account": account,
            "project_manager": project_manager,
            "allocations": allocations,
            "employees_by_role": employees_by_role,
            "latest_status": latest_status,
            "allocation_count": len(allocations),
        }

    def _build_context_for_question(self, question: str) -> str:
        """Build structured context for the LLM based on the question and entities."""
        context_lines = [
            f"User: {self.actor.name}",
            f"Role: {self.actor.role.value}",
            "",
        ]

        # Add active context if available
        if self.context.active_account_id:
            account_data = self._retrieve_account_data(self.context.active_account_id)
            if account_data.get("account"):
                account = account_data["account"]
                context_lines.append(f"Current Account: {account.name}")
                context_lines.append(f"  - Industry: {account.industry}")
                context_lines.append(f"  - Status: {account.status.value}")
                context_lines.append(f"  - Health: {account.health.value}")
                context_lines.append(f"  - Projects: {account_data.get('project_count', 0)}")
                if account_data.get("program_manager"):
                    context_lines.append(f"  - Program Manager: {account_data['program_manager'].name}")
                context_lines.append("")

        if self.context.active_project_id:
            project_data = self._retrieve_project_data(self.context.active_project_id)
            if project_data.get("project"):
                project = project_data["project"]
                context_lines.append(f"Current Project: {project.name}")
                context_lines.append(f"  - Phase: {project.phase.value}")
                context_lines.append(f"  - Health: {project.health.value}")
                context_lines.append(f"  - Risk Level: {project.risk.value}")
                context_lines.append(f"  - Completion: {project.completion_percent}%")
                if project_data.get("project_manager"):
                    context_lines.append(f"  - Project Manager: {project_data['project_manager'].name}")
                context_lines.append(f"  - Team Members: {project_data.get('allocation_count', 0)}")
                
                # Add team breakdown
                if project_data.get("employees_by_role"):
                    context_lines.append("  - Team Breakdown:")
                    for role, emps in project_data["employees_by_role"].items():
                        emp_names = ", ".join([e["name"] for e in emps])
                        context_lines.append(f"    - {role}: {emp_names}")
                context_lines.append("")

        # Extract entities mentioned in question
        entities = self._extract_entities_from_query(question)
        if entities:
            context_lines.append("Referenced Entities:")
            if entities.get("accounts"):
                for acc_ref in entities["accounts"]:
                    context_lines.append(f"  - Account: {acc_ref['name']}")
            if entities.get("projects"):
                for proj_ref in entities["projects"]:
                    context_lines.append(f"  - Project: {proj_ref['name']}")
            context_lines.append("")

        # Add RAG sources if available
        rag_sources = search_knowledge(
            question,
            top_k=3,
            project_id=self.context.active_project_id,
            allowed_project_ids=self.resolver.allowed_project_ids if self.resolver.allowed_project_ids else set()
        )
        
        if rag_sources:
            context_lines.append("Related Knowledge:")
            for source in rag_sources:
                doc = source.get("document", "")
                if doc:
                    # Truncate long documents
                    doc_preview = doc[:300] + "..." if len(doc) > 300 else doc
                    context_lines.append(f"  - {doc_preview}")
            context_lines.append("")

        return "\n".join(context_lines)

    def answer(self, question: str) -> dict[str, Any]:
        """
        Generate an answer to a governance question.
        
        Returns:
            {
                "answer": str,
                "context_type": "database|rag|hybrid",
                "entities_used": list[dict],
                "sources": list[dict],
            }
        """
        try:
            # Determine intent
            intent = self._determine_intent(question)
            self.context.last_intent = intent

            # Build context
            context_text = self._build_context_for_question(question)

            # Retrieve sources
            rag_sources = search_knowledge(
                question,
                top_k=5,
                project_id=self.context.active_project_id,
                allowed_project_ids=self.resolver.allowed_project_ids if self.resolver.allowed_project_ids else set()
            )

            # Construct prompt
            prompt = self._construct_prompt(question, context_text, rag_sources)

            # Generate response
            try:
                answer, model = generate_text("groq", prompt, self.settings.groq_default_model)
            except Exception as llm_exc:
                # If LLM fails, provide a helpful response
                logger.warning("LLM generation failed, returning context-based response: %s", str(llm_exc))
                answer = self._fallback_answer(question, context_text)
                model = "fallback"

            # Add to message history
            self.context.message_history.append({
                "role": "user",
                "content": question
            })
            self.context.message_history.append({
                "role": "assistant",
                "content": answer
            })

            context_type = "hybrid" if rag_sources else "database"
            
            return {
                "answer": answer,
                "context_type": context_type,
                "provider": "groq",
                "model": model,
                "sources": rag_sources,
                "entities_used": list(self.context.last_retrieved_entities.values()),
            }

        except Exception as exc:
            logger.exception("Chatbot answer generation failed for question: %s", question)
            raise

    def _fallback_answer(self, question: str, context: str) -> str:
        """Generate a simple response when LLM is unavailable."""
        q_lower = question.lower()
        
        if any(word in q_lower for word in ["hello", "hi", "hey", "who are you"]):
            return f"Hello! I'm the Governance Chatbot, here to help you with delivery information. You are {self.actor.name} with role {self.actor.role.value}."
        
        if any(word in q_lower for word in ["account", "list"]):
            return f"I can help you find information about accounts. Currently, you have access to {len(self.resolver.allowed_account_ids)} accounts."
        
        if any(word in q_lower for word in ["project", "list"]):
            return f"I can help you find information about projects. Currently, you have access to {len(self.resolver.allowed_project_ids)} projects."
        
        return "I'm here to help with your delivery governance questions. The AI backend is currently unavailable, but I can still help you navigate the system data. What would you like to know?"


    def _construct_prompt(self, question: str, context: str, sources: list[dict]) -> str:
        """Construct the LLM prompt."""
        sources_text = ""
        if sources:
            sources_text = "\n\n---\n\n".join(source.get("document", "") for source in sources)
            sources_text = f"\n\nRelated Documentation:\n{sources_text}"

        system_message = """You are a senior delivery governance analyst for an enterprise IT services organization.
You provide concise, factual, client-safe delivery insights.
You focus on risks, blockers, ownership, and next actions when relevant.
Answer using only the supplied governance context.
Do NOT invent facts or data.
If information is unavailable, say it clearly.
Be direct and professional, avoiding filler language."""

        return f"""{system_message}

GOVERNANCE CONTEXT:
{context}
{sources_text}

QUESTION:
{question}

ANSWER:
"""
