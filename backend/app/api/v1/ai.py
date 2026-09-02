from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.people import Employee, Role
from app.schemas.common import RagQueryIn, RagQueryOut, ChatMessageIn, ChatMessageOut
from app.services.chatbot import GovernanceChatbot, ConversationContext
from app.services.llm import available_providers
from app.services.rag import answer_with_rag

router = APIRouter(prefix="/ai", tags=["ai"])

# In-memory conversation storage (replace with database for production)
_conversations: dict[str, ConversationContext] = {}


@router.get("/providers", response_model=list[dict])
def providers(_: Employee = Depends(get_current_user)) -> list[dict]:
    return [provider.__dict__ for provider in available_providers()]


@router.post("/rag/query", response_model=RagQueryOut)
def rag_query(payload: RagQueryIn, actor: Employee = Depends(get_current_user), db: Session = Depends(get_db)) -> RagQueryOut:
    return answer_with_rag(payload, actor, db)


@router.post("/chat", response_model=ChatMessageOut)
def chat_message(
    payload: ChatMessageIn,
    actor: Employee = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChatMessageOut:
    """
    Send a message to the governance chatbot.
    
    - Creates or retrieves conversation context
    - Maintains conversation history
    - Respects user's RBAC
    - Returns grounded, factual response
    """
    try:
        # Get or create conversation context
        conversation_id = payload.conversation_id or actor.id
        if conversation_id not in _conversations:
            _conversations[conversation_id] = ConversationContext()
        
        context = _conversations[conversation_id]

        # Update active project if specified
        if payload.project_id:
            context.active_project_id = payload.project_id

        # Create chatbot instance
        chatbot = GovernanceChatbot(db, actor, context)

        # Generate response
        response_data = chatbot.answer(payload.message)

        # Return formatted response
        return ChatMessageOut(
            conversation_id=conversation_id,
            message=response_data["answer"],
            context_type=response_data.get("context_type", "hybrid"),
            provider=response_data.get("provider", "groq"),
            model=response_data.get("model", ""),
            sources=response_data.get("sources", []),
            entities_used=response_data.get("entities_used", []),
            timestamp=datetime.now(timezone.utc),
        )

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process chat message",
        ) from exc

