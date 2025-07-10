"""SQLAlchemy table definitions for the v2 architecture.

This module defines the tables used in the v2 architecture,
which consolidates all state in Postgres.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY, Boolean, Column, DateTime, Enum, ForeignKey, 
    Integer, String, Table, Text, MetaData, func, text
)
from sqlalchemy.dialects.postgresql import JSON, JSONB, UUID

metadata = MetaData()

# Agent table - stores agent capabilities and heartbeat
agents = Table(
    "agents",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("task_types", ARRAY(String), nullable=False),
    Column("last_heartbeat", DateTime(timezone=True), nullable=False, 
           server_default=func.now()),
    Column("status", String(20), nullable=False, server_default="active"),
    Column("created_at", DateTime(timezone=True), nullable=False, 
           server_default=func.now()),
)

# Task table - replaces Redis queue with durable storage
tasks = Table(
    "tasks",
    metadata,
    Column("id", UUID, primary_key=True, default=uuid.uuid4),
    Column("task_type", String(64), nullable=False, index=True),
    Column("payload", JSONB, nullable=False),
    Column("status", String(20), nullable=False, server_default="queued", index=True),
    Column("agent_id", String(64), ForeignKey("agents.id"), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, 
           server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, 
           server_default=func.now(), onupdate=func.now()),
    Column("session_id", String(64), nullable=True),
)

# SQL functions and triggers
# These will be executed when creating the schema

# Function to notify on new task
notify_new_task_sql = """
CREATE OR REPLACE FUNCTION notify_new_task()
RETURNS TRIGGER AS $$
BEGIN
    PERFORM pg_notify('task_queue', NEW.id::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

# Trigger to fire notification when task is inserted - split into separate statements
drop_task_notify_trigger_sql = """
DROP TRIGGER IF EXISTS task_notify_trigger ON tasks;
"""

create_task_notify_trigger_sql = """
CREATE TRIGGER task_notify_trigger
AFTER INSERT ON tasks
FOR EACH ROW
EXECUTE FUNCTION notify_new_task();
"""

# Function to update timestamp on task update
update_task_timestamp_sql = """
CREATE OR REPLACE FUNCTION update_task_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

# Trigger to update timestamp when task is updated - split into separate statements
drop_task_timestamp_trigger_sql = """
DROP TRIGGER IF EXISTS task_timestamp_trigger ON tasks;
"""

create_task_timestamp_trigger_sql = """
CREATE TRIGGER task_timestamp_trigger
BEFORE UPDATE ON tasks
FOR EACH ROW
EXECUTE FUNCTION update_task_timestamp();
"""

# All SQL to execute when creating schema - each statement separately
schema_creation_sql = [
    notify_new_task_sql,
    drop_task_notify_trigger_sql,
    create_task_notify_trigger_sql,
    update_task_timestamp_sql,
    drop_task_timestamp_trigger_sql,
    create_task_timestamp_trigger_sql,
] 