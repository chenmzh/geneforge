"""ORM models: users, projects, sequences with versioning, jobs, audit, registry."""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db.base import Base, TimestampMixin, UUIDMixin


class Role(str, enum.Enum):
    """Global role. Project-level access is refined by ProjectMember."""

    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"


class ProjectRole(str, enum.Enum):
    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Topology(str, enum.Enum):
    LINEAR = "linear"
    CIRCULAR = "circular"


class User(UUIDMixin, TimestampMixin, Base):
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255))
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), default=Role.EDITOR.value, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    settings_json: Mapped[dict] = mapped_column("settings", JSON, default=dict)

    memberships: Mapped[list[ProjectMember]] = relationship(back_populates="user", cascade="all, delete-orphan")
    api_keys: Mapped[list[ApiKey]] = relationship(back_populates="user", cascade="all, delete-orphan")

    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN.value


class ApiKey(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "api_keys"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    prefix: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    hashed_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    user: Mapped[User] = relationship(back_populates="api_keys")


class Project(UUIDMixin, TimestampMixin, Base):
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(200), unique=True, index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    metadata_json: Mapped[dict] = mapped_column("metadata_json", JSON, default=dict)

    owner: Mapped[User] = relationship(foreign_keys=[owner_id])
    members: Mapped[list[ProjectMember]] = relationship(back_populates="project", cascade="all, delete-orphan")
    sequences: Mapped[list[Sequence]] = relationship(back_populates="project", cascade="all, delete-orphan")


class ProjectMember(UUIDMixin, TimestampMixin, Base):
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_member"),)

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16), default=ProjectRole.VIEWER.value, nullable=False)

    project: Mapped[Project] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="memberships")


class Sequence(UUIDMixin, TimestampMixin, Base):
    __table_args__ = (Index("ix_sequences_project_name", "project_id", "name"),)

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    seq_type: Mapped[str] = mapped_column(String(16), default="dna", nullable=False)
    topology: Mapped[str] = mapped_column(String(16), default=Topology.LINEAR.value, nullable=False)
    molecule_type: Mapped[str] = mapped_column(String(32), default="ds-DNA")
    sequence: Mapped[str] = mapped_column(Text, nullable=False)
    length: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    gc_content: Mapped[float] = mapped_column(Float, default=0.0)
    checksum: Mapped[str] = mapped_column(String(64), default="")
    source_format: Mapped[str] = mapped_column(String(32), default="manual")
    annotations_json: Mapped[dict] = mapped_column("annotations", JSON, default=dict)
    current_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    project: Mapped[Project] = relationship(back_populates="sequences")
    features: Mapped[list[Feature]] = relationship(
        back_populates="sequence", cascade="all, delete-orphan", order_by="Feature.start"
    )
    versions: Mapped[list[SequenceVersion]] = relationship(
        back_populates="sequence", cascade="all, delete-orphan", order_by="SequenceVersion.version.desc()"
    )
    primers: Mapped[list[Primer]] = relationship(back_populates="sequence")

    @property
    def is_circular(self) -> bool:
        return self.topology == Topology.CIRCULAR.value


class Feature(UUIDMixin, TimestampMixin, Base):
    __table_args__ = (Index("ix_features_seq_pos", "sequence_id", "start"),)

    sequence_id: Mapped[str] = mapped_column(ForeignKey("sequences.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(64), default="misc_feature", nullable=False)
    name: Mapped[str] = mapped_column(String(255), default="")
    start: Mapped[int] = mapped_column(Integer, nullable=False)
    end: Mapped[int] = mapped_column(Integer, nullable=False)
    strand: Mapped[int] = mapped_column(Integer, default=1)
    color: Mapped[str | None] = mapped_column(String(16))
    segments: Mapped[list] = mapped_column(JSON, default=list)
    qualifiers: Mapped[dict] = mapped_column(JSON, default=dict)

    sequence: Mapped[Sequence] = relationship(back_populates="features")


class SequenceVersion(UUIDMixin, TimestampMixin, Base):
    __table_args__ = (UniqueConstraint("sequence_id", "version", name="uq_sequence_version"),)

    sequence_id: Mapped[str] = mapped_column(ForeignKey("sequences.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    sequence_text: Mapped[str] = mapped_column("sequence_text", Text, nullable=False)
    features_json: Mapped[list] = mapped_column("features", JSON, default=list)
    topology: Mapped[str] = mapped_column(String(16), default=Topology.LINEAR.value)
    message: Mapped[str] = mapped_column(String(500), default="")
    diff_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    sequence: Mapped[Sequence] = relationship(back_populates="versions")


class Primer(UUIDMixin, TimestampMixin, Base):
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    sequence_id: Mapped[str | None] = mapped_column(ForeignKey("sequences.id", ondelete="SET NULL"), index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    seq: Mapped[str] = mapped_column("sequence", String(500), nullable=False)
    tm: Mapped[float | None] = mapped_column(Float)
    gc_content: Mapped[float | None] = mapped_column(Float)
    binding_start: Mapped[int | None] = mapped_column(Integer)
    binding_end: Mapped[int | None] = mapped_column(Integer)
    strand: Mapped[int] = mapped_column(Integer, default=1)
    notes: Mapped[str | None] = mapped_column(Text)
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    sequence: Mapped[Sequence | None] = relationship(back_populates="primers")


class Job(UUIDMixin, TimestampMixin, Base):
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), default=JobStatus.PENDING.value, nullable=False, index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    backend: Mapped[str] = mapped_column(String(16), default="local")
    external_id: Mapped[str | None] = mapped_column(String(120))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ImportedFile(UUIDMixin, TimestampMixin, Base):
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    detected_format: Mapped[str] = mapped_column(String(32), default="unknown")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    checksum: Mapped[str] = mapped_column(String(64), default="")
    stored_path: Mapped[str | None] = mapped_column(String(500))
    record_count: Mapped[int] = mapped_column(Integer, default=0)


class ExternalResource(UUIDMixin, TimestampMixin, Base):
    """Configurable link/API registry (NCBI, Ensembl, AddGene, internal LIMS...)."""

    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), default="link")  # link | rest | blast
    description: Mapped[str | None] = mapped_column(Text)
    url_template: Mapped[str] = mapped_column(String(1000), default="")
    method: Mapped[str] = mapped_column(String(8), default="GET")
    headers: Mapped[dict] = mapped_column(JSON, default=dict)
    query_defaults: Mapped[dict] = mapped_column(JSON, default=dict)
    secret_ref: Mapped[str | None] = mapped_column(String(120))
    allow_proxy: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class AuditLog(UUIDMixin, Base):
    __tablename__ = "audit_logs"

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_type: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(36), index=True)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


__all__ = [
    "ApiKey",
    "AuditLog",
    "ExternalResource",
    "Feature",
    "ImportedFile",
    "Job",
    "JobStatus",
    "Primer",
    "Project",
    "ProjectMember",
    "ProjectRole",
    "Role",
    "Sequence",
    "SequenceVersion",
    "Topology",
    "User",
]
