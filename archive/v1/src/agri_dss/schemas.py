from enum import Enum
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Decision(str, Enum):
    REQUIRED = 'IRRIGATION_REQUIRED'
    NOT_REQUIRED = 'IRRIGATION_NOT_REQUIRED'
    INSUFFICIENT = 'INSUFFICIENT_INFORMATION'


class Snapshot(Contract):
    snapshot_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    crop: str | None = None
    growth_stage: str | None = None
    cultivation_system: str | None = None
    soil_moisture_value: float | None = Field(default=None, strict=True, ge=0)
    soil_moisture_unit: Literal['percent_vwc', 'kpa_tension'] | None = None
    source_ids: list[str] = Field(default_factory=list)


class SourceRef(Contract):
    source_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    location: str = Field(min_length=1)
    verified: bool = False


class IrrigationRule(Contract):
    rule_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    status: Literal['demo_only', 'verified']
    applicable_crop: str = Field(min_length=1)
    growth_stage: str = Field(min_length=1)
    cultivation_system: str = Field(min_length=1)
    input_unit: Literal['percent_vwc', 'kpa_tension']
    operator: Literal['<', '<=', '>', '>=']
    threshold: float | None = Field(default=None, strict=True, ge=0)
    sources: list[SourceRef] = Field(default_factory=list)


class DecisionResult(Contract):
    snapshot_id: str
    snapshot_version: str
    domain: Literal['irrigation'] = 'irrigation'
    mode: Literal['demo', 'research']
    decision: Decision
    decision_code: str
    rule_id: str
    rule_version: str
    rule_status: str
    inputs_used: dict = Field(default_factory=dict)
    calculation_steps: list[dict] = Field(default_factory=list)
    source_refs: list[SourceRef] = Field(default_factory=list)
    input_source_ids: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    numeric_result: float | None = None
    numeric_unit: str | None = None
