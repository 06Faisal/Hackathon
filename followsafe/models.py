from typing import List, Optional, Literal
from pydantic import BaseModel, Field

class Medication(BaseModel):
    name: str
    action: Literal["start", "continue", "increase", "decrease", "stop", "take"]
    dose: Optional[str] = None
    frequency: Optional[str] = None
    duration: Optional[str] = None
    source_line: str

class FollowUp(BaseModel):
    type: Literal["lab", "appointment", "imaging", "therapy", "procedure", "other"]
    description: str
    due_date: Optional[str] = None
    source_line: str

class Warning(BaseModel):
    text: str
    source_line: str

class ExtractedFacts(BaseModel):
    patient_id: str
    medications: List[Medication] = Field(default_factory=list)
    follow_ups: List[FollowUp] = Field(default_factory=list)
    warnings: List[Warning] = Field(default_factory=list)

class Task(BaseModel):
    id: str
    type: str
    description: str
    due_date: Optional[str] = None
    authorized_by: str

class ReconItem(BaseModel):
    status: Literal["matched", "date_mismatch", "missing_task", "unsupported_task"]
    description: str
    note_date: Optional[str] = None
    task_date: Optional[str] = None
    task_id: Optional[str] = None

class Draft(BaseModel):
    patient_id: str
    language: str
    text: str
    sources: List[str] = Field(default_factory=list)

class VerifyResult(BaseModel):
    passed: bool
    missing: List[str] = Field(default_factory=list)
    altered: List[str] = Field(default_factory=list)
