from typing import Any, Literal
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)


class ChartPayload(BaseModel):
    type: Literal["bar", "pie", "line", "table", "kpi"]
    title: str
    data: Any
    options: dict[str, Any] = {}


class ChatResponse(BaseModel):
    success: bool = True
    text: str
    chart: ChartPayload | None = None
    tools_used: list[str] = []
    iterations: int = 0
    error: str | None = None
