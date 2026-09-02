from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.people import Employee, Role
from app.schemas.common import RagQueryIn, RagQueryOut
from app.services.llm import available_providers
from app.services.rag import answer_with_rag

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/providers", response_model=list[dict])
def providers(_: Employee = Depends(get_current_user)) -> list[dict]:
    return [provider.__dict__ for provider in available_providers()]


@router.post("/rag/query", response_model=RagQueryOut)
def rag_query(payload: RagQueryIn, actor: Employee = Depends(get_current_user), db: Session = Depends(get_db)) -> RagQueryOut:
    return answer_with_rag(payload, actor, db)
