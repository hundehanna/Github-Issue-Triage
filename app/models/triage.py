from typing import Literal

from pydantic import BaseModel, Field


class TriageResult(BaseModel):
    repo: str
    issue_number: int = Field(ge=1)
    category: Literal["Bug", "Feature Request", "Documentation", "Question", "Other"]
    priority: Literal["High", "Medium", "Low"]
    suggested_labels: list[str]
    reason: str

