"""Pydantic schemas — sequences, features, versions, import/export, primers."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class FeatureBase(BaseModel):
    type: str = Field(default="misc_feature", max_length=64)
    name: str = Field(default="", max_length=255)
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    strand: int = Field(default=1, ge=-1, le=1)
    color: str | None = Field(default=None, max_length=16)
    segments: list[list[int]] = Field(default_factory=list)
    qualifiers: dict = Field(default_factory=dict)

    @field_validator("segments")
    @classmethod
    def _validate_segments(cls, value: list[list[int]]) -> list[list[int]]:
        for seg in value:
            if len(seg) != 2 or seg[0] < 0 or seg[1] < seg[0]:
                raise ValueError("Each segment must be [start, end] with 0 <= start <= end")
        return value


class FeatureCreate(FeatureBase):
    pass


class FeatureUpdate(BaseModel):
    type: str | None = None
    name: str | None = None
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=0)
    strand: int | None = Field(default=None, ge=-1, le=1)
    color: str | None = None
    segments: list[list[int]] | None = None
    qualifiers: dict | None = None


class FeatureOut(ORMModel, FeatureBase):
    id: str
    sequence_id: str


class SequenceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    sequence: str = Field(default="")
    description: str | None = None
    topology: Literal["linear", "circular"] = "linear"
    molecule_type: str = "ds-DNA"
    seq_type: Literal["dna", "rna", "protein"] = "dna"
    features: list[FeatureCreate] = Field(default_factory=list)
    annotations: dict = Field(default_factory=dict)
    auto_annotate: bool = False


class SequenceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    topology: Literal["linear", "circular"] | None = None
    molecule_type: str | None = None
    annotations: dict | None = None
    is_archived: bool | None = None


class SequenceSummary(ORMModel):
    id: str
    project_id: str
    name: str
    description: str | None = None
    seq_type: str
    topology: str
    molecule_type: str
    length: int
    gc_content: float
    current_version: int
    source_format: str
    checksum: str
    created_at: datetime
    updated_at: datetime
    feature_count: int = 0


class SequenceOut(SequenceSummary):
    sequence: str
    features: list[FeatureOut] = Field(default_factory=list)
    annotations: dict = Field(
        default_factory=dict,
        validation_alias="annotations_json",
    )


class SequenceVersionOut(ORMModel):
    id: str
    sequence_id: str
    version: int
    message: str
    topology: str
    created_at: datetime
    created_by_id: str | None = None
    diff_summary: dict = Field(default_factory=dict)
    length: int = 0


class SequenceVersionDetail(SequenceVersionOut):
    sequence: str
    features: list[dict] = Field(default_factory=list)


class EditOperation(BaseModel):
    """One editing operation applied atomically to a sequence."""

    op: Literal[
        "insert",
        "delete",
        "replace",
        "reverse_complement",
        "reverse_complement_range",
        "set_origin",
        "set_topology",
    ]
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=0)
    position: int | None = Field(default=None, ge=0)
    payload: str | None = None
    origin: int | None = Field(default=None, ge=0)
    topology: Literal["linear", "circular"] | None = None


class EditRequest(BaseModel):
    operations: list[EditOperation] = Field(min_length=1)
    message: str | None = Field(default=None, max_length=500)


class ImportRequest(BaseModel):
    """Import from pasted text or a URL instead of a multipart upload."""

    content: str | None = None
    url: str | None = None
    filename: str | None = None
    format: str | None = Field(default=None, description="Force a format instead of sniffing")
    auto_annotate: bool = False
    name_prefix: str | None = None


class ImportedRecord(BaseModel):
    sequence_id: str
    name: str
    length: int
    topology: str
    feature_count: int
    source_format: str


class ImportResult(BaseModel):
    imported: list[ImportedRecord]
    skipped: list[dict] = Field(default_factory=list)
    detected_format: str
    file_id: str | None = None


class ExportRequest(BaseModel):
    format: Literal["genbank", "fasta", "plain"] = "genbank"
    include_features: bool = True


class PrimerCreate(BaseModel):
    name: str = Field(max_length=120)
    sequence: str = Field(min_length=5, max_length=500)
    sequence_id: str | None = None
    notes: str | None = None
    binding_start: int | None = None
    binding_end: int | None = None
    strand: int = 1


class PrimerOut(ORMModel):
    id: str
    project_id: str
    sequence_id: str | None = None
    name: str
    sequence: str = Field(validation_alias="seq")
    tm: float | None = None
    gc_content: float | None = None
    binding_start: int | None = None
    binding_end: int | None = None
    strand: int
    notes: str | None = None
    stats: dict = Field(default_factory=dict)
    created_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class SequenceStats(BaseModel):
    length: int
    gc: float
    topology: str
    a: int
    c: int
    g: int
    t: int
    ambiguous: int
    orf_count: int
    longest_orf: dict | None = None
    gc_track: list[dict] = Field(default_factory=list)
    molecular_weight: float = 0.0
    melting_temp: float = 0.0


class AnyDict(BaseModel):
    model_config = ConfigDict(extra="allow")
    data: dict[str, Any] = Field(default_factory=dict)
