from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.people import Employee
from app.schemas.common import ChatRequest, ChatResponse
from app.services.chat import answer_chat

router = APIRouter(prefix="/chat", tags=["chatbot"])


@router.post("", response_model=ChatResponse)
def chat(payload: ChatRequest, actor: Employee = Depends(get_current_user), db: Session = Depends(get_db)) -> ChatResponse:
    try:
        return answer_chat(payload, actor, db)
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The governance database is temporarily unavailable.",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The chatbot could not process this request.",
        ) from exc
