# ===== Config =====
ROOT            := $(shell pwd)
NETWORK         := shared-net

MOCK_JSON       ?= $(ROOT)/tests/openweather_mock.json
MOCK_NAME       := mockoon
MOCK_IMAGE      ?= mockoon/cli:latest
MOCK_PORT       ?= 3000
MOCK_HOST_PORT  ?= 3000
MOCK_SUBCMD     ?= start
MOCK_ARGS       := --data /data/mock.json --index 0 --hostname 0.0.0.0 --port $(MOCK_PORT) --log-transaction

SPLUNK_NAME     := splunk
SPLUNK_IMAGE    ?= splunk/splunk:9.4.1
SPLUNK_PASSWORD ?= password
SPLUNK_ARGS     := -e SPLUNK_START_ARGS="--answer-yes --no-prompt --accept-license" -e SPLUNK_PASSWORD="$(SPLUNK_PASSWORD)" -e SPLUNK_USER="root"
SPLUNK_WEB_PORT ?= 8000
SPLUNK_API_PORT ?= 8089

CURL            ?= curl -sSf
DOCKER          ?= docker

# ===== Helpers =====
define wait_for_http
i=0; max=$${2:-30}; \
until $(CURL) "$1" >/dev/null 2>&1; do \
  i=$$((i+1)); if [ $$i -ge $$max ]; then echo "Timeout esperando $1"; exit 1; fi; \
  echo "Esperando $1 ... ($$i/$${max})"; sleep 2; \
done; \
echo "OK -> $1"
endef

# ===== Phony =====
.PHONY: all ci \
        docker-check network \
        mockoon-up mockoon-logs mockoon-health mockoon-version mockoon-curl mockoon-down mockoon-ps \
        splunk-up splunk-logs splunk-wait splunk-curl splunk-down \
        sanity clean

# ===== Default =====
all: ci

# ===== Prechecks =====
docker-check:
	@command -v $(DOCKER) >/dev/null 2>&1 || { echo "Docker no está en PATH"; exit 1; }
	@$(DOCKER) info >/dev/null 2>&1 || { echo "Docker daemon no disponible"; exit 1; }

network: docker-check
	-@$(DOCKER) network create $(NETWORK) >/dev/null 2>&1 || true
	@echo "Red disponible: $(NETWORK)"

# ===== Mockoon =====
mockoon-up: network
	@echo "Levantando Mockoon con $(MOCK_IMAGE) ..."
	-@$(DOCKER) rm -f $(MOCK_NAME) >/dev/null 2>&1 || true
	@ls -l $(MOCK_JSON)
	@$(DOCKER) run -d --name $(MOCK_NAME) \
		--network $(NETWORK) \
		-v "$(MOCK_JSON)":/data/mock.json:ro \
		-p $(MOCK_HOST_PORT):$(MOCK_PORT) \
		$(MOCK_IMAGE) \
		$(MOCK_SUBCMD) \
		$(MOCK_ARGS)
	@$(MAKE) mockoon-version
	@$(MAKE) mockoon-ps
	@$(MAKE) mockoon-health || { echo "Logs recientes de Mockoon:"; $(MAKE) -s mockoon-logs; exit 1; }
	@$(MAKE) sanity

mockoon-version:
	@echo "Mockoon CLI version:"
	-@$(DOCKER) exec $(MOCK_NAME) mockoon-cli --version || true

mockoon-ps:
	@$(DOCKER) ps --filter name=$(MOCK_NAME)
	@echo "Puertos contenedor:"
	@$(DOCKER) inspect -f '{{json .NetworkSettings.Ports}}' $(MOCK_NAME)

mockoon-logs:
	@$(DOCKER) logs --tail=200 $(MOCK_NAME) || true

mockoon-health:
	@echo "Comprobando salud de Mockoon en localhost:$(MOCK_HOST_PORT)/health ..."
	@bash -c '$(call wait_for_http,http://localhost:$(MOCK_HOST_PORT)/health,30)'

mockoon-curl:
	@$(CURL) "http://localhost:$(MOCK_HOST_PORT)/health" | (which jq >/dev/null 2>&1 && jq . || cat)
	@$(CURL) "http://localhost:$(MOCK_HOST_PORT)/geo/1.0/direct?q=guanacaste,CR&limit=1&appid=dummy-key" >/dev/null
	@$(CURL) "http://localhost:$(MOCK_HOST_PORT)/data/2.5/weather?lat=10.5&lon=-85.4&appid=dummy-key" >/dev/null
	@echo "Sanity endpoints OK"

mockoon-down:
	-@$(DOCKER) rm -f $(MOCK_NAME) >/dev/null 2>&1 || true

# ===== Splunk (opcional) =====
splunk-up: network
	@echo "Levantando Splunk $(SPLUNK_IMAGE) ..."
	-@$(DOCKER) rm -f $(SPLUNK_NAME) >/dev/null 2>&1 || true
	@$(DOCKER) run -d --name $(SPLUNK_NAME) \
		--network $(NETWORK) \
		$(SPLUNK_ARGS) \
		-p $(SPLUNK_WEB_PORT):8000 \
		-p $(SPLUNK_API_PORT):8089 \
		$(SPLUNK_IMAGE)
	@$(MAKE) splunk-wait
	@$(MAKE) splunk-curl

splunk-logs:
	@$(DOCKER) logs --tail=200 $(SPLUNK_NAME) || true

splunk-wait:
	@echo "Esperando Splunk (~150s) ..."
	@sleep 150
	@$(MAKE) splunk-logs
	@echo "Buscando línea de ready ..."
	@$(DOCKER) logs $(SPLUNK_NAME) 2>&1 | tail -n 200 | grep -F "Ansible playbook complete, will begin streaming splunkd_stderr.log" >/dev/null || \
		{ echo "Splunk no parece listo"; exit 1; }

splunk-curl:
	@echo "Comprobando conectividad Splunk -> Mockoon ..."
	@$(DOCKER) exec $(SPLUNK_NAME) curl -sSf http://$(MOCK_NAME):$(MOCK_PORT)/health >/dev/null
	@echo "Conectividad OK"

splunk-down:
	-@$(DOCKER) rm -f $(SPLUNK_NAME) >/dev/null 2>&1 || true

# ===== Sanity =====
sanity: mockoon-curl
	@echo "Sanity local completado ✅"

# ===== Pipeline local end-to-end =====
ci: docker-check mockoon-up  ## Agrega 'splunk-up' si quieres probar conectividad desde Splunk
	@echo "CI local (solo Mockoon) OK. Para incluir Splunk: 'make splunk-up'"

# ===== Limpieza =====
clean: mockoon-down splunk-down
	-@$(DOCKER) network rm $(NETWORK) >/dev/null 2>&1 || true
	@echo "Limpieza completa"
