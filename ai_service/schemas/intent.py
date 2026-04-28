from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any

class IntentRequest(BaseModel):
    student_input: str = Field(..., description="The student's raw text input")
    session_context: str = Field(
        default="", 
        description="The session context string (e.g. 'topic:For Loops | prev:Lists,...')"
    )
    split_compound: bool = Field(
        default=True,
        description="Whether to split compound sentences into multiple classifications"
    )
    session_id: Optional[str] = Field(
        default=None,
        description=(
            "Optional session ID.  When provided and session_context is empty, "
            "context is auto-populated from SharedSessionStore."
        ),
    )
    confidence_threshold: Optional[float] = Field(
        default=None,
        description=(
            "Override the default confidence threshold (0.55).  "
            "Predictions below this value are labelled 'Low Confidence'."
        ),
    )

class IntentPrediction(BaseModel):
    text: str = Field(..., description="The specific text segment classified")
    intent_name: str = Field(..., description="The predicted intent name (e.g. 'On-Topic Question')")
    label_id: int = Field(..., description="The integer ID of the predicted intent")
    confidence: float = Field(..., description="Confidence score for the prediction (0.0 to 1.0)")
    probabilities: Dict[str, float] = Field(..., description="Probabilities for all classes")
    raw_prediction: Optional[str] = Field(
        default=None,
        description=(
            "Original model prediction before confidence thresholding.  "
            "Non-null only when intent_name is 'Low Confidence'."
        ),
    )
    raw_confidence: Optional[float] = Field(
        default=None,
        description=(
            "Original model confidence before thresholding.  "
            "Non-null only when intent_name is 'Low Confidence'."
        ),
    )

class IntentResponse(BaseModel):
    success: bool = Field(default=True)
    predictions: List[IntentPrediction] = Field(..., description="List of predictions (multiple if split_compound is True)")
    inference_time_seconds: float = Field(..., description="Time taken for inference")

class ChatMessage(BaseModel):
    role: str = Field(description="'user' or 'system' or 'assistant'")
    content: str = Field(description="The message content")

class ChatRequest(BaseModel):
    messages: List[ChatMessage] = Field(..., description="List of previous messages in the chat")
    session_id: Optional[str] = Field(
        default=None,
        description=(
            "Optional session ID. When provided, session context is read "
            "from SharedSessionStore instead of being hardcoded to empty."
        ),
    )

class ChatResponse(BaseModel):
    response: str = Field(description="The system's response")
    intent: str = Field(description="The predicted intent behind the user's latest message")
    confidence: float = Field(description="Confidence score for the predicted intent")
