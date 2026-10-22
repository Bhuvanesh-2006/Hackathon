"""Structured output contract between the agent and any LLM provider."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ChartType = Literal["bar", "line", "pie", "none"]


class ChartSpec(BaseModel):
    type: ChartType = Field(description="bar for rankings/categories, line for time series, pie for <=6 shares, none otherwise")
    x: str | None = Field(default=None, description="Result column used for the x-axis / categories")
    y: list[str] = Field(default_factory=list, description="Numeric result column(s) to plot")
    title: str | None = None


class AgentPlan(BaseModel):
    """What the model must return for every question."""

    intent: Literal["analytical", "clarification", "unsupported"] = Field(
        description="analytical: answerable with SQL; clarification: a key definition is ambiguous; "
        "unsupported: the dataset cannot answer it or it asks to modify data"
    )
    sql: str | None = Field(default=None, description="One DuckDB SELECT over table transactions (analytical only)")
    explanation: str = Field(description="Plain-English description of the calculation, naming the definitions used")
    business_rules: list[str] = Field(default_factory=list, description="IDs of business rules applied, e.g. net_revenue")
    clarification_question: str | None = None
    clarification_options: list[str] = Field(default_factory=list, description="2-4 short answer options")
    unsupported_reason: str | None = None
    chart: ChartSpec | None = None


class ConversationTurn(BaseModel):
    question: str
    sql: str | None = None
    intent: str | None = None
