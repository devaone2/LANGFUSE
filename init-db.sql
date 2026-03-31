-- ================================================================
-- PostgreSQL Initialization Script
-- Creates two databases:
--   1. langfuse      → used by Langfuse server for traces/scores
--   2. agent_memory  → used by the LangGraph agent (LTM store)
-- ================================================================

-- Create Langfuse database (if it doesn't exist)
SELECT 'CREATE DATABASE langfuse'
WHERE NOT EXISTS (
    SELECT FROM pg_database WHERE datname = 'langfuse'
)\gexec

-- Create Agent Long-Term Memory database (if it doesn't exist)
SELECT 'CREATE DATABASE agent_memory'
WHERE NOT EXISTS (
    SELECT FROM pg_database WHERE datname = 'agent_memory'
)\gexec
