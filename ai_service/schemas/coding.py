from pydantic import BaseModel

class TopicRequest(BaseModel):
    topic: str

class SubmitRequest(BaseModel):
    question: str
    code: str