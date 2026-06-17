"""
Intent Router for classification endpoints.

Integrates with SharedSessionStore so that when ``session_context`` is
empty the context is auto-populated from the shared session state.
"""

import logging
import os
import re

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, Field
from services.intent_service import get_intent_service, reload_intent_service
from services.session_store import get_session_store
from schemas.intent import IntentRequest, IntentResponse, ChatRequest, ChatResponse

# Internal service key — must match Django's INTERNAL_SERVICE_KEY.
# If empty, service-only endpoints like /intent/reload are disabled.
logger = logging.getLogger(__name__)

INTERNAL_SERVICE_KEY = os.getenv("INTERNAL_SERVICE_KEY", "")

# A.10: Allowed root directory for model loading.
# The /intent/reload endpoint will only load checkpoints from within this path.
_INTENT_MODEL_DIR = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "intent_model")
)

router = APIRouter(
    prefix="/intent",
    tags=["Intent Classification"]
)

@router.post("/classify", response_model=IntentResponse)
async def classify_intent(request: IntentRequest):
    """
    Classify a student's text input into one of 6 pedagogical intents.
    Supports compound sentence splitting.

    When ``session_context`` is empty and a ``session_id`` is provided,
    context is automatically read from SharedSessionStore.
    """
    try:
        # ── Auto-populate context from SharedSessionStore ───────────
        session_context = request.session_context
        if not session_context and request.session_id:
            store = get_session_store()
            session_context = store.build_context_string(request.session_id)
            logger.info(
                "Intent /classify: auto-populated context from store for session %s",
                request.session_id,
            )

        # ── Resolve confidence threshold ────────────────────────────
        threshold = request.confidence_threshold if request.confidence_threshold is not None else 0.65

        service = get_intent_service()
        predictions, inference_time = service.classify(
            student_input=request.student_input,
            session_context=session_context,
            split_compound=request.split_compound,
            confidence_threshold=threshold,
        )
        
        return IntentResponse(
            success=True,
            predictions=predictions,
            inference_time_seconds=inference_time
        )
        
    except FileNotFoundError as e:
        logger.error(f"Model file missing: {e}")
        raise HTTPException(
            status_code=503,
            detail="Intent model is currently unavailable (model file missing)."
        )
    except Exception as e:
        logger.error(f"Classification error: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to classify intent: {str(e)}"
        )


@router.post("/chat", response_model=ChatResponse)
async def chat_intent(request: ChatRequest):
    """
    Simulated chat endpoint for intent classification testing.
    Takes a list of messages and classifies the last user message.

    When ``session_id`` is provided, session context is read from
    SharedSessionStore instead of being hardcoded to an empty string.
    """
    try:
        if not request.messages:
            raise HTTPException(status_code=400, detail="No messages provided")
            
        # Get the latest user message
        last_message = None
        for msg in reversed(request.messages):
            if msg.role == "user":
                last_message = msg.content
                break
                
        if not last_message:
            raise HTTPException(status_code=400, detail="No user message found in the chat history")

        # ── Build session context from SharedSessionStore ───────────
        session_context = ""
        if request.session_id:
            store = get_session_store()
            session_context = store.build_context_string(request.session_id)
            logger.info(
                "Intent /chat: auto-populated context from store for session %s",
                request.session_id,
            )

        # Classify the message
        service = get_intent_service()
        predictions, _ = service.classify(
            student_input=last_message,
            session_context=session_context,
            split_compound=False  # Usually false for direct chat response
        )
        
        if not predictions:
            raise HTTPException(status_code=500, detail="No prediction generated")
            
        top_prediction = predictions[0]
        intent = top_prediction['intent_name']
        confidence = top_prediction['confidence']
        
        # Responses based on intent.
        # NOTE: 'Repeat/clarification' tells the frontend to call POST /tutor/repeat
        # (default mode: "rephrase").  The intent classifier already resolves this
        # label — no additional sub-intent detection is required here.
        responses = {
            'On-Topic Question': "That's a great question about the material! Let me explain...",
            'Off-Topic Question': "That seems a bit off-topic. Let's try to focus on the current subject.",
            'Emotional-State': "I understand you might be feeling overwhelmed. Let's take it step by step.",
            'Pace-Related': "I can adjust my pace. Would you like me to go faster or slower?",
            'Repeat/clarification': (
                "Of course! I'll explain that again in a simpler way. "
                "[ACTION: POST /tutor/repeat {\"mode\": \"rephrase\"}]"
            ),
            'Debugging/Code-Sharing': (
                "I can see you're sharing some code. Let me take a look and help you debug it."
            ),
            'Unknown': (
                "I'm not quite sure what you mean. Could you rephrase that? "
                "I want to make sure I understand you correctly."
            ),
        }
        
        response_text = responses.get(intent, f"I understood your intent as: {intent}.")
        
        # Prepend profanity warning if detected
        if top_prediction.get('contains_profanity'):
            profanity_warning = (
                "I can see you might be frustrated. "
                "Let's keep things respectful and focus on the code. "
            )
            response_text = profanity_warning + response_text
        
        return ChatResponse(
            response=response_text,
            intent=intent,
            confidence=confidence
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process chat: {str(e)}"
        )

class ReloadModelRequest(BaseModel):
    model_path: str = Field(default="best_model.pt", description="Checkpoint filename inside intent_model/")


def _verify_service_key(x_service_key: str = Header(...)):
    """Dependency: require a valid X-Service-Key header for internal endpoints."""
    if not INTERNAL_SERVICE_KEY:
        logger.warning("INTERNAL_SERVICE_KEY not configured; /intent/reload is disabled")
        raise HTTPException(status_code=503, detail="Reload endpoint is not configured")
    if not x_service_key or x_service_key != INTERNAL_SERVICE_KEY:
        logger.warning("Invalid or missing X-Service-Key on /intent/reload")
        raise HTTPException(status_code=401, detail="Invalid or missing service key")


def _safe_model_path(model_path: str) -> str:
    """Resolve and validate that the requested checkpoint stays inside intent_model/."""
    # Only allow simple filenames
    if not re.fullmatch(r"[\w\-. ]+", model_path):
        raise HTTPException(status_code=400, detail="Invalid model filename")

    base = os.path.dirname(os.path.abspath(__file__))
    intent_model_dir = os.path.abspath(os.path.join(base, "..", "intent_model"))
    full_path = os.path.abspath(os.path.join(intent_model_dir, model_path))
    # Ensure the resolved path is still under intent_model/
    if os.path.commonpath([full_path, intent_model_dir]) != intent_model_dir:
        raise HTTPException(status_code=400, detail="Invalid model path")
    return model_path


@router.post("/reload")
async def reload_model(
    request: ReloadModelRequest,
    _auth: None = Depends(_verify_service_key),
):
    """Reload the production intent classifier checkpoint without restarting the service.

    Requires ``X-Service-Key`` header matching ``INTERNAL_SERVICE_KEY``.
    The requested filename is constrained to the ``intent_model/`` directory.
    """
    safe_path = _safe_model_path(request.model_path)
    try:
        service = reload_intent_service(model_path=safe_path)
        return {
            "success": True,
            "model_path": service.model_path,
            "model_loaded": service.classifier is not None and getattr(service.classifier, 'model', None) is not None,
        }
    except FileNotFoundError as e:
        logger.error(f"Model file missing: {e}")
        raise HTTPException(
            status_code=503,
            detail="Intent model is currently unavailable (model file missing)."
        )
    except Exception as e:
        logger.error(f"Model reload error: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to reload intent model: {str(e)}"
        )


@router.get("/health")
async def intent_health():
    """Check if the Intent classification service is loaded and ready."""
    try:
        service = get_intent_service()
        
        # Verify model object is loaded in underlying TinyBert wrapper
        is_loaded = service.classifier is not None and getattr(service.classifier, 'model', None) is not None
        
        return {
            "status": "healthy" if is_loaded else "degraded",
            "model_loaded": is_loaded,
            "model_path": service.model_path 
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }
