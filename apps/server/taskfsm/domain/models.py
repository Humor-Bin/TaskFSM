from __future__ import annotations
from datetime import datetime, timezone
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Table, Column, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def now():
    return datetime.now(timezone.utc)


def new_id(prefix: str):
    return f'{prefix}_{uuid.uuid4().hex[:12]}'


class Base(DeclarativeBase):
    pass


task_dependencies = Table(
    'task_dependencies', Base.metadata,
    Column('task_id', String, ForeignKey('tasks.id', ondelete='CASCADE'), primary_key=True),
    Column('dependency_id', String, ForeignKey('tasks.id', ondelete='CASCADE'), primary_key=True),
)


class Task(Base):
    __tablename__ = 'tasks'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id('task'))
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default='')
    status: Mapped[str] = mapped_column(String(32), default='backlog', index=True)
    priority: Mapped[str] = mapped_column(String(16), default='medium')
    assignee_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    assignee_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    required_capabilities: Mapped[list] = mapped_column(JSON, default=list)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    current_action: Mapped[str] = mapped_column(String(300), default='')
    source: Mapped[str] = mapped_column(String(32), default='taskfsm', index=True)
    control_mode: Mapped[str] = mapped_column(String(16), default='managed', index=True)
    external_id: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    source_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    dependencies: Mapped[list['Task']] = relationship(
        secondary=task_dependencies,
        primaryjoin=id == task_dependencies.c.task_id,
        secondaryjoin=id == task_dependencies.c.dependency_id,
        lazy='selectin',
    )


class Agent(Base):
    __tablename__ = 'agents'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id('agent'))
    name: Mapped[str] = mapped_column(String(120), unique=True)
    kind: Mapped[str] = mapped_column(String(80), default='generic')
    capabilities: Mapped[list] = mapped_column(JSON, default=list)
    token_hash: Mapped[str] = mapped_column(String(128), default='')
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Lease(Base):
    __tablename__ = 'leases'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id('lease'))
    task_id: Mapped[str] = mapped_column(ForeignKey('tasks.id'), index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey('agents.id'), index=True)
    run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Run(Base):
    __tablename__ = 'runs'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id('run'))
    task_id: Mapped[str] = mapped_column(ForeignKey('tasks.id'), index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey('agents.id'), index=True)
    status: Mapped[str] = mapped_column(String(32), default='running')
    source: Mapped[str] = mapped_column(String(32), default='taskfsm', index=True)
    control_mode: Mapped[str] = mapped_column(String(16), default='managed', index=True)
    external_session_id: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    workspace: Mapped[str | None] = mapped_column(Text, nullable=True)
    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    plan_snapshot: Mapped[list] = mapped_column(JSON, default=list)
    current_event: Mapped[dict] = mapped_column(JSON, default=dict)
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Artifact(Base):
    __tablename__ = 'artifacts'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id('artifact'))
    task_id: Mapped[str] = mapped_column(ForeignKey('tasks.id'), index=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey('runs.id'), nullable=True)
    created_by: Mapped[str] = mapped_column(String(120))
    type: Mapped[str] = mapped_column(String(40))
    uri: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Review(Base):
    __tablename__ = 'reviews'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id('review'))
    task_id: Mapped[str] = mapped_column(ForeignKey('tasks.id'), index=True)
    reviewer: Mapped[str] = mapped_column(String(120))
    decision: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Event(Base):
    __tablename__ = 'events'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str] = mapped_column(String(120), index=True)
    actor_type: Mapped[str] = mapped_column(String(32))
    actor_id: Mapped[str] = mapped_column(String(120))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
