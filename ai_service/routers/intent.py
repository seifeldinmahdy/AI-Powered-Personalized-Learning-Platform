"""
Intent Router for classification endpoints.

Integrates with SharedSessionStore so that when ``session_context`` is
empty the context is auto-populated from the shared session state.
"""

from fastapi import APIRouter, HTTPException
import logging
from services.intent_service import get_intent_service
from services.session_store import get_session_store
from schemas.intent import IntentRequest, IntentResponse, ChatRequest, ChatResponse

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/intent",
    tags=["Intent Classification"]
)

@router.post("/classify", response_model=IntentResponse)
async def classify_intent(request: IntentRequest):
    """
    Classify a student's text input into one of 5 pedagogical intents.
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
        threshold = request.confidence_threshold if request.confidence_threshold is not None else 0.55

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
        
        # Simulated responses based on intent
        responses = {
            'On-Topic Question': "That's a great question about the material! Let me explain...",
            'Off-Topic Question': "That seems a bit off-topic. Let's try to focus on the current subject.",
            'Emotional-State': "I understand you might be feeling overwhelmed. Let's take it step by step.",
            'Pace-Related': "I can adjust my pace. Would you like me to go faster or slower?",
            'Repeat/clarification': "Of course, I can clarify that for you. Here it is in different words...",
            'Low Confidence': (
                "I'm not quite sure what you mean. Could you rephrase that? "
                "I want to make sure I understand you correctly."
            ),
        }
        
        response_text = responses.get(intent, f"I understood your intent as: {intent}.")
        
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
