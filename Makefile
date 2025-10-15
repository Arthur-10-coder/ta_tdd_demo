.PHONY: venv deps build enable-input run logs down package install-tests run-tests clean

APP_VERSION := $$(jq -r '.meta.version' globalConfig.json)
APP_NAME    := $$(jq -r '.meta.name' globalConfig.json)
BASE_URL    ?= http://localhost:3000
API_KEY     ?= dummy-key

venv:
	python3 -m venv .venv

deps: venv
	. .venv/bin/activate; \
	pip install --upgrade pip; \
	# NO instales splunk-packaging-toolkit local (evita permisos/manpages)
	pip install splunk-add-on-ucc-framework; \
	pip install -r package/lib/requirements.txt; \
	pip install pytest requests-mock

build: deps
	. .venv/bin/activate; \
	ucc-gen build --ta-version=$(APP_VERSION); \
	mkdir -p output/$(APP_NAME)/local

enable-input:
	sed 's/disabled = 1/disabled = 0/' etc/cicd/inputs.conf > output/$(APP_NAME)/local/inputs.conf
	printf "[demo_account]\nbase_url = $(BASE_URL)\napi_key = $(API_KEY)\n" > output/$(APP_NAME)/local/ta_tdd_demo_account.conf
	chmod -R +r output && chmod -R go-w output

run: build enable-input
	# Fuerza plataforma x86 en Mac ARM para ambas imágenes
	DOCKER_DEFAULT_PLATFORM=linux/amd64 APP_NAME=$(APP_NAME) docker compose up -d

logs:
	docker compose logs -f --tail=100

down:
	docker compose down -v

package: build enable-input
	mkdir -p dist
	# ucc-gen package no requiere splunk-packaging-toolkit instalado globalmente
	ucc-gen package --path output/$(APP_NAME) -o dist

install-tests: deps

run-tests: install-tests
	cd tests && pytest -q integration

clean:
	rm -rf .venv output dist
