.PHONY: up down logs ingest classify brief brief-synthetic seed-reset alerts costs latency eval demo demo-safe seed reset

-include .env
API := http://localhost:8000
CURL := curl -sS --fail-with-body -H "Content-Type: application/json" -H "X-API-Key: $(API_KEY)"
JSON := python -m json.tool --no-ensure-ascii

up:
	docker compose up -d --build --wait
	@echo "API:      http://localhost:8000/docs   (Authorize with API_KEY from .env)"
	@echo "n8n:      http://localhost:5678        (create the owner account on first visit)"
	@echo "Adminer:  http://localhost:8080        (System: PostgreSQL, Server: db, User: mm, Pass: mm_local_password, DB: media_monitor)"

down:
	docker compose down

reset:  ## wipe the database and start clean (keeps downloaded model weights)
	docker compose down
	docker volume rm media-monitor_db_data
	$(MAKE) up

logs:
	docker compose logs -f api

seed:
	docker compose exec api python -m scripts.seed_synthetic

seed-reset:  ## re-arm the synthetic fixtures: fresh timestamps, old classifications/alerts cleared
	docker compose exec api python -m scripts.seed_synthetic --reset

ingest:
	$(CURL) -X POST $(API)/ingest -d '{}' | $(JSON)

classify:
	$(CURL) -X POST $(API)/classify -d '{}' | $(JSON)

brief:
	$(CURL) -X POST $(API)/brief -d '{}' | $(JSON)

brief-synthetic:  ## offline demo only: a briefing built from the synthetic fixtures alone
	$(CURL) -X POST $(API)/brief -d '{"synthetic_only": true}' | $(JSON)

alerts:
	$(CURL) $(API)/alerts/pending | $(JSON)

costs:
	$(CURL) "$(API)/runs/summary?hours=24" | $(JSON)

latency:
	$(CURL) $(API)/alerts/latency | $(JSON)

eval:
	docker compose exec api python -m eval.run_eval

demo: ingest classify alerts brief
	@echo "Core loop ran end to end on live feeds. Check n8n at http://localhost:5678 for the approval workflow."

demo-safe: seed-reset classify alerts brief-synthetic
	@echo "Ran the core loop on synthetic backup data (no live feed dependency)."
