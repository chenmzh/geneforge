"""Pydantic schemas — analysis tool requests, jobs, external resources."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SequenceInput(BaseModel):
    """Either an inline sequence or a stored sequence id."""

    sequence: str | None = None
    sequence_id: str | None = None
    circular: bool | None = None


class TranslateRequest(SequenceInput):
    table_id: int = Field(default=1, description="NCBI codon table id (1, 2, 11)")
    frame: int = Field(default=0, ge=-3, le=3)
    six_frame: bool = False
    to_stop: bool = False


class EnzymeSearchRequest(SequenceInput):
    enzymes: list[str] = Field(default_factory=list)
    common_only: bool = True
    unique_only: bool = False


class DigestRequest(SequenceInput):
    enzymes: list[str] = Field(min_length=1)
    ladder: str = "1kb_plus"
    gel_percent: float = Field(default=1.0, ge=0.4, le=3.0)


class PrimerAnalyzeRequest(BaseModel):
    sequence: str = Field(min_length=4, max_length=500)
    primer_conc_nM: float = Field(default=500.0, gt=0)
    na_mM: float = Field(default=50.0, ge=0)
    mg_mM: float = Field(default=1.5, ge=0, description="Mg2+ concentration; 1.5 mM matches a standard PCR buffer")


class PrimerDesignRequest(SequenceInput):
    target_start: int = Field(ge=0)
    target_end: int = Field(ge=1)
    min_len: int = Field(default=18, ge=10, le=60)
    max_len: int = Field(default=27, ge=12, le=60)
    opt_tm: float = Field(default=60.0, ge=40, le=80)
    min_tm: float = Field(default=57.0, ge=35, le=80)
    max_tm: float = Field(default=65.0, ge=40, le=85)
    max_tm_diff: float = Field(default=3.0, ge=0.5, le=10)
    product_min: int = Field(default=0, ge=0)
    product_max: int = Field(default=0, ge=0)
    max_pairs: int = Field(default=5, ge=1, le=20)
    fwd_enzyme_site: str | None = None
    rev_enzyme_site: str | None = None


class PcrRequest(SequenceInput):
    forward: str = Field(min_length=6, max_length=200)
    reverse: str = Field(min_length=6, max_length=200)
    max_mismatches: int = Field(default=3, ge=0, le=8)
    min_3prime_match: int = Field(default=12, ge=6, le=30)


class GibsonRequest(BaseModel):
    insert: str = Field(min_length=20)
    vector_left: str = Field(min_length=10)
    vector_right: str = Field(min_length=10)
    overlap: int = Field(default=25, ge=15, le=60)


class AlignRequest(BaseModel):
    query: str | None = None
    target: str | None = None
    query_sequence_id: str | None = None
    target_sequence_id: str | None = None
    mode: Literal["global", "local", "glocal"] = "global"
    match: int = 2
    mismatch: int = -3
    gap_open: int = -6
    gap_extend: int = -2
    try_reverse_complement: bool = True
    async_job: bool = False


class MultiAlignRequest(BaseModel):
    sequences: list[dict] = Field(default_factory=list, description="[{name, sequence}]")
    sequence_ids: list[str] = Field(default_factory=list)
    async_job: bool = False


class OrfRequest(SequenceInput):
    min_aa: int = Field(default=50, ge=10, le=5000)
    table_id: int = 1
    both_strands: bool = True
    require_start: bool = True


class AnnotateRequest(SequenceInput):
    include_orfs: bool = True
    min_orf_aa: int = Field(default=80, ge=20, le=2000)
    extra_library: list[dict] = Field(default_factory=list)
    apply: bool = Field(default=False, description="Persist detected features to the stored sequence")


class TransferAnnotationRequest(BaseModel):
    reference_sequence_id: str
    target_sequence_id: str
    min_identity: float = Field(default=80.0, ge=0, le=100)
    apply: bool = False


class JobOut(ORMModel):
    id: str
    project_id: str | None = None
    type: str
    status: str
    progress: float
    params: dict = Field(default_factory=dict)
    result: dict | None = None
    error: str | None = None
    backend: str
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class JobSubmitted(BaseModel):
    job_id: str
    status: str
    type: str


class ExternalResourceCreate(BaseModel):
    name: str = Field(max_length=120)
    kind: Literal["link", "rest", "blast"] = "link"
    description: str | None = None
    url_template: str = Field(max_length=1000)
    method: Literal["GET", "POST"] = "GET"
    headers: dict = Field(default_factory=dict)
    query_defaults: dict = Field(default_factory=dict)
    allow_proxy: bool = False
    is_enabled: bool = True


class ExternalResourceUpdate(BaseModel):
    description: str | None = None
    url_template: str | None = None
    method: Literal["GET", "POST"] | None = None
    headers: dict | None = None
    query_defaults: dict | None = None
    allow_proxy: bool | None = None
    is_enabled: bool | None = None


class ExternalResourceOut(ORMModel):
    id: str
    name: str
    kind: str
    description: str | None = None
    url_template: str
    method: str
    query_defaults: dict = Field(default_factory=dict)
    allow_proxy: bool
    is_enabled: bool
    created_at: datetime


class ExternalFetchRequest(BaseModel):
    params: dict = Field(default_factory=dict)
    import_to_project: str | None = None
    auto_annotate: bool = False
