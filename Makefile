# ================================================================
# Makefile — convenience commands for the LangGraph + Langfuse stack
# ================================================================

.PHONY: help up down logs ps setup install check test chat clean

# Default target
help:
	@echo ""
	@echo "  LangGraph + Langfuse Local Agent — Available Commands"
	@echo "  ───────────────────────────────────────────────────────"
	@echo "  make up       Start all Docker services (Langfuse, PostgreSQL, Redis)"
	@echo "  make down     Stop and remove all containers"
	@echo "  make logs     Tail logs from all containers"
	@echo "  make ps       Show container status"
	@echo "  make setup    Copy .env.example → .env (first-time setup)"
	@echo "  make install  Install Python dependencies"
	@echo "  make check    Check service connectivity"
	@echo "  make test     Run automated agent test suite (generates Langfuse traces)"
	@echo "  make chat     Start interactive chat session"
	@echo "  make clean    Remove Docker volumes (⚠️  deletes all data)"
	@echo ""

# ── Docker ──────────────────────────────────────────────────────

up:
	docker compose up -d
	@echo ""
	@echo "  ✅ Services starting…"
	@echo "  📊 Langfuse UI → http://localhost:3000"
	@echo "  🐘 PostgreSQL  → localhost:5432"
	@echo "  🔴 Redis       → localhost:6379"
	@echo ""
	@echo "  Next steps:"
	@echo "    1. Open http://localhost:3000 and create an account"
	@echo "    2. Create a project and copy the API keys"
	@echo "    3. Paste the keys into .env (LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY)"
	@echo "    4. make test"

down:
	docker compose down

logs:
	docker compose logs -f

ps:
	docker compose ps

# ── Python ──────────────────────────────────────────────────────

setup:
	@if [ ! -f .env ]; then \
	    cp .env.example .env; \
	    echo "  ✅ .env created — edit it with your API keys"; \
	else \
	    echo "  ℹ️  .env already exists — skipping"; \
	fi

install:
	pip install -r requirements.txt

check:
	python run_agent.py --check

test:
	python run_agent.py --test

chat:
	python run_agent.py --chat

# ── Cleanup ─────────────────────────────────────────────────────

clean:
	@echo "⚠️  This will delete all PostgreSQL and Redis data."
	@read -p "Are you sure? [y/N] " ans; \
	if [ "$$ans" = "y" ]; then docker compose down -v; echo "Volumes removed."; fi
