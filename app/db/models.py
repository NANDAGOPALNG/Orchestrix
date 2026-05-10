from datetime import datetime
from typing import Optional, List, Dict
from sqlmodel import SQLModel, Field, JSON, Column

class JobExecution(SQLModel, table=True):
    id: Optional[str] = Field(default=None, primary_key=True)
    query: str
    status: str  # "pending", "completed", "failed"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Store the full trace as a JSON object
    trace: Dict = Field(default_factory=dict, sa_column=Column(JSON))

class EvaluationRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: str = Field(foreign_key="jobexecution.id")
    category: str  # "straightforward", "ambiguous", "adversarial"
    score: float
    justification: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class PromptVersion(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    agent_id: str
    prompt_text: str
    version: int
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)