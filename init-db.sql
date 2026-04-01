-- ================================================================
-- PostgreSQL Initialization Script
--
-- IMPORTANT: This script runs ONCE on fresh volume creation only.
--
-- The `langfuse` database is created automatically by Docker via
-- POSTGRES_DB=langfuse in docker-compose.yml — no need to create
-- it here.
--
-- This script only creates the agent_memory database used by the
-- LangGraph agent for Long-Term Memory (conversation history,
-- notes, session metrics).
-- ================================================================

-- Create Agent Long-Term Memory database
SELECT 'CREATE DATABASE agent_memory'
WHERE NOT EXISTS (
    SELECT FROM pg_database WHERE datname = 'agent_memory'
)\gexec
