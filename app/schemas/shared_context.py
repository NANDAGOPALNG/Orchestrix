from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime
import uuid

class AgentStep(BaseModel):
    agent_id: str
    thought: str      # Required reasoning justification
    action: str       # e.g., "call_search", "respond"
    output: Any
    tokens_used: int
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class ToolResult(BaseModel):
    tool_name: str
    ok: bool
    data: Any = None
    error: Optional[str] = None
    attempts: int = 0
    fallback_used: bool = False
    citations: List[Dict[str, Any]] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class SharedContext(BaseModel):
    job_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    original_query: str
    
    # The Plan (Filled by Decomposition Agent)
    tasks: List[Dict[str, Any]] = Field(default_factory=list)
    
    # The Memory (Every agent's output goes here)
    history: List[AgentStep] = Field(default_factory=list)
    
    # Tool Data Repository
    tool_results: Dict[str, Any] = Field(default_factory=dict)
    
    # Context Budgeting (Requirement 3)
    total_tokens: int = 0
    max_budget: int = 4096
    compressed_summary: Optional[str] = None
    compression_events: List[Dict[str, Any]] = Field(default_factory=list)
    
    # The Final Output
    final_answer: Optional[str] = None
    provenance_map: Dict[str, Any] = Field(default_factory=dict) # Map sentence index to source agent/chunk
    route_state: Dict[str, Any] = Field(default_factory=dict)
