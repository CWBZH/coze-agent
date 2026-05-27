from fastapi import APIRouter, Depends

from web_api.deps import get_live_chat_service
from web_api.schemas.live_chat import LiveChatMessageRequest, LiveChatSessionCreate
from web_api.services.live_chat_service import LiveChatService


router = APIRouter(prefix="/live-chat/sessions", tags=["live-chat"])


@router.post("")
def create_session(payload: LiveChatSessionCreate, service: LiveChatService = Depends(get_live_chat_service)) -> dict:
    return service.create_session(payload.shop_id, payload.buyer_id).model_dump()


@router.post("/{session_id}/messages")
def send_message(session_id: str, payload: LiveChatMessageRequest, service: LiveChatService = Depends(get_live_chat_service)) -> dict:
    return service.send_message(session_id, payload).model_dump()
