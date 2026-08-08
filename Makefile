# Makefile for Project Environment

-include .env
export

.PHONY: up down logs db-shell info

up:
	@echo "🚀 Starting environment..."
	docker compose up -d

down:
	@echo "🛑 Stopping environment..."
	docker compose down

logs:
	@echo "📜 Streaming logs..."
	docker compose logs -f

db-shell:
	@echo "🐘 Opening database shell..."
	docker compose exec db psql -U $(POSTGRES_USER) -d $(POSTGRES_DB)

info:
	@echo "📊 Project Metadata:"
	@echo "Version: 1.0.0"
	@echo "Status: 🏗️ In Progress"
