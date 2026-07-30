# E4DRR ecFlow — operator entry points.
# Every target is safe to re-run. `make help` lists them.

SHELL := /bin/bash
COMPOSE := docker compose
ENV_FILE := .env

-include $(ENV_FILE)
export

ECF_PORT ?= 3141
ECF_HTTP_PORT ?= 8080
ECFLOW_VERSION ?= 5.18.0
ECFLOW_IMAGE ?= e4drr/ecflow:$(ECFLOW_VERSION)

# Run a one-off ecflow_client against the running engine.
CLIENT := $(COMPOSE) exec -T ecflow-server ecflow_client --host=localhost --port=$(ECF_PORT)

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

$(ENV_FILE):
	@cp .env.example $(ENV_FILE) && echo "Created $(ENV_FILE) from .env.example — review it."

.PHONY: init
init: $(ENV_FILE) ## Create .env and the state directory
	@mkdir -p $(or $(ECF_DATA_DIR),./data)
	@echo "State directory: $(or $(ECF_DATA_DIR),./data)"

.PHONY: build
build: ## Build the ecFlow image
	$(COMPOSE) build --build-arg ECFLOW_VERSION=$(ECFLOW_VERSION)

.PHONY: up
up: init ## Start the engine (module 1)
	$(COMPOSE) up -d ecflow-server

.PHONY: up-http
up-http: init ## Start the engine + REST proxy (modules 1-2)
	$(COMPOSE) --profile http up -d

# On crafd-gpu, also publish on Tailscale + ICPAC LAN. See docker-compose.crafd.yml.
CRAFD := -f docker-compose.yml -f docker-compose.crafd.yml

.PHONY: up-crafd
up-crafd: init acl ## Start on crafd-gpu, reachable via Tailscale + LAN
	$(COMPOSE) $(CRAFD) --profile http up -d
	@echo "Engine : $(ECF_BIND_TAILSCALE):$(ECF_PORT) (tailscale), $(ECF_BIND_LAN):$(ECF_PORT) (lan)"
	@echo "REST   : http://$(ECF_BIND_TAILSCALE):$(ECF_HTTP_PORT)/v1/suites"

.PHONY: acl
acl: ## Install the white list into the state directory
	@cp -f ecf.lists $(or $(ECF_DATA_DIR),./data)/ecf.lists
	@echo "white list -> $(or $(ECF_DATA_DIR),./data)/ecf.lists"

.PHONY: reload-acl
reload-acl: acl ## Reload the white list without restarting the engine
	@$(CLIENT) --reloadwsfile
	@echo "white list reloaded"

.PHONY: down
down: ## Stop the stack. State in ECF_DATA_DIR is preserved.
	$(COMPOSE) down

.PHONY: restart
restart: ## Restart the engine. It reloads from the checkpoint.
	$(COMPOSE) restart ecflow-server

.PHONY: logs
logs: ## Follow container logs
	$(COMPOSE) logs -f --tail=100

.PHONY: ping
ping: ## Check the engine is reachable
	@$(CLIENT) --ping

.PHONY: status
status: ## Server stats and the suite tree with states
	@$(CLIENT) --stats
	@echo "---- suites ----"
	@$(CLIENT) --get_state | head -60

.PHONY: start-engine
start-engine: ## Take the server out of HALTED into RUNNING
	@$(CLIENT) --restart
	@$(CLIENT) --ping && echo "engine RUNNING"

.PHONY: shell
shell: ## Shell inside the engine container
	$(COMPOSE) exec ecflow-server bash

.PHONY: checkpoint
checkpoint: ## Force an immediate checkpoint write
	@$(CLIENT) --check_pt

.PHONY: smoke
smoke: ## Load and run the hello suite — proves the engine end to end
	@$(CLIENT) --load=/ecflow/suites/hello/hello.def force
	@$(CLIENT) --begin=hello
	@echo "Loaded. Watch with: make status"

.PHONY: smoke-clean
smoke-clean: ## Remove the hello suite
	@$(CLIENT) --delete=force yes /hello || true

# ---- workstation access ----------------------------------------------------
# The engine binds to 127.0.0.1 on the server, so nothing is reachable over the
# network without this tunnel. That is deliberate: a plain-TCP ecFlow server has
# no authentication, and full operator control comes with the connection.
SSH_HOST ?= gpu

.PHONY: tunnel
tunnel: ## Forward the engine + REST ports from the server to this machine
	@echo "Forwarding $(SSH_HOST):$(ECF_PORT) -> localhost:$(ECF_PORT)"
	@echo "Forwarding $(SSH_HOST):$(ECF_HTTP_PORT) -> localhost:$(ECF_HTTP_PORT)"
	@echo "Point ecflow_ui at localhost:$(ECF_PORT). Ctrl-C to close."
	ssh -N -L $(ECF_PORT):localhost:$(ECF_PORT) \
	       -L $(ECF_HTTP_PORT):localhost:$(ECF_HTTP_PORT) $(SSH_HOST)

.PHONY: install-client
install-client: ## Install ecflow_ui + ecflow_client on this workstation
	@bash scripts/install-client.sh

ECFLOW_UI ?= $(HOME)/.local/share/mamba/envs/ecflow/bin/ecflow_ui

.PHONY: setup-ui
setup-ui: ## Register this server in ecflow_ui's server list
	@bash scripts/setup-ui.sh e4drr localhost $(ECF_PORT)

.PHONY: ui
ui: setup-ui ## Launch ecflow_ui against localhost:$(ECF_PORT)
	@if [ ! -x "$(ECFLOW_UI)" ]; then \
	   echo "ecflow_ui not found at $(ECFLOW_UI) — run 'make install-client' first."; exit 1; fi
	@setsid $(ECFLOW_UI) </dev/null >/tmp/ecflow_ui.log 2>&1 & \
	 echo "ecflow_ui launched. Connecting to localhost:$(ECF_PORT)."

.PHONY: backup
backup: ## Copy checkpoint + log out of the state directory
	@mkdir -p backups
	@tar czf backups/ecflow-state-$$(date +%Y%m%d-%H%M%S).tar.gz \
	    -C $(or $(ECF_DATA_DIR),./data) $$(cd $(or $(ECF_DATA_DIR),./data) && ls | grep -E 'ecf\.(check|log)' || true)
	@ls -lh backups | tail -3
