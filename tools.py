"""
tools.py — Not used in the current multi-agent architecture.

The system now uses three specialised LLM agents instead of tool-calling:
  • Orchestrator Agent  — routes requests
  • Rephrase Agent      — expands short text
  • Summary Agent       — condenses long text

This file is kept as a placeholder for future tool extensions.
To add tools, define them here with @tool and import them in agent.py.
"""
