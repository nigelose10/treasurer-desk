.PHONY: up down seed desk unit lint e2e demo video reset register

PY ?= python3

up:
	bash scripts/up.sh

down:
	bash scripts/down.sh

seed:
	$(PY) scripts/seed.py

desk:
	bash scripts/desk.sh

register:
	$(PY) scripts/register_agents.py

unit:
	$(PY) -m pytest -q tests/unit

lint:
	$(PY) -m ruff check desk tests scripts

e2e:
	$(PY) -m pytest -q tests/e2e

demo: reset up seed desk
	bash scripts/wait-ready.sh
	$(MAKE) e2e

video: 
	bash scripts/wait-ready.sh
	$(PY) demo/record.py
	bash demo/build_video.sh

reset:
	bash scripts/down.sh --volumes || true
	rm -rf .state
	mkdir -p .state
