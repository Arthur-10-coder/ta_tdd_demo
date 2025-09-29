# Makefile
up:        ; docker compose up -d app mockoon
test:      ; docker compose run --rm tests
down:      ; docker compose down -v
ci:        ; pytest -m "unit" -q
