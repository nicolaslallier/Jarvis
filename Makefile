# Makefile for Project Environment

-include .env
export

.PHONY: up down logs info

up:
	@echo "🚀 Starting environment..."
	docker compose up -d

down:
	@echo "🛑 Stopping environment..."
	docker compose down

logs:
	@echo "📜 Streaming logs..."
	docker compose logs -f

info:
	@echo "📊 Project Metadata:"
	@echo "Version: 1.0.0"
	@echo "Status: 🏗️ In Progress"
