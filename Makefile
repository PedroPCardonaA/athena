COMPOSE ?= podman-compose
.PHONY: up down dev test backup restore mcp
up:        ## start from the prebuilt image
	mkdir -p data && $(COMPOSE) up -d
down:
	$(COMPOSE) down
dev:       ## build from source and start
	mkdir -p data && $(COMPOSE) -f compose.dev.yaml up -d --build
test:
	python3 -m pytest -q tests
backup:    ## consistent copy of the database into data/backups/
	mkdir -p data/backups && sqlite3 data/ideas.db ".backup data/backups/ideas-$$(date +%F-%H%M%S).db"
restore:   ## make restore FILE=data/backups/ideas-....db  (stop the app first)
	@test -n "$(FILE)" || (echo "usage: make restore FILE=<backup.db>"; exit 1)
	cp "$(FILE)" data/ideas.db && rm -f data/ideas.db-wal data/ideas.db-shm
mcp:       ## print the commands that connect an AI agent over MCP
	@echo "claude mcp add athena -- podman exec -i athena python -m app.athena_mcp"
	@echo "codex mcp add athena -- podman exec -i athena python -m app.athena_mcp"
	@echo "(add --read-only for view-only access; see docs/mcp.md)"
