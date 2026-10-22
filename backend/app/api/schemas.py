"""Request models (responses are plain JSON dicts documented in docs/API.md)."""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

CONVERSATION_ID = r"^[A-Za-z0-9_-]*$"


class AgentQueryRequest(BaseModel):
    question: str = Field(default="", max_length=2000, description="Natural-language question")
    conversation_id: str | None = Field(default=None, max_length=64, pattern=CONVERSATION_ID)
    clarification_response: str | None = Field(default=None, max_length=200,
                                                description="Answer to the agent's clarifying question")
    rerun: bool = Field(default=False, description="Re-run the conversation's base question with the current filters")
    dataset_id: str | None = Field(default=None, pattern=r"^(online_retail_ii|ds_[0-9a-f]{12})$",
                                   description="Dataset to query; defaults to the conversation's dataset, else the built-in one")


class Window(BaseModel):
    start: date
    end: date = Field(description="Exclusive end date")


class ContributionRequest(BaseModel):
    anomaly_id: str | None = Field(default=None, max_length=80, pattern=r"^[a-z_]+-\d{4}-\d{2}-\d{2}$",
                                   description="Use an anomaly's metric, week and baseline weeks")
    metric: Literal["net_revenue", "units_sold", "orders", "cancelled_value"] | None = None
    dimension: Literal["product", "country", "customer", "weekday"] = "product"
    current: Window | None = None
    comparison: list[Window] | None = Field(default=None, max_length=60)
    top_n: int = Field(default=10, ge=1, le=50)


class ConversationCreate(BaseModel):
    anomaly_id: str = Field(max_length=80, pattern=r"^[a-z_]+-\d{4}-\d{2}-\d{2}$")


class ConversationPatch(BaseModel):
    remove: list[Literal["country", "year", "date_range", "stock_codes", "customer_id"]] = Field(default_factory=list)
    clear_filters: bool = False
    clear_comparison: bool = False
