from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.people import Employee
from app.schemas.common import ChatRequest, ChatResponse
from app.services.chat import answer_chat

router = APIRouter(prefix="/chat", tags=["chatbot"])


@router.post("", response_model=ChatResponse)
def chat(payload: ChatRequest, actor: Employee = Depends(get_current_user), db: Session = Depends(get_db)) -> ChatResponse:
    return answer_chat(payload, actor, db)
