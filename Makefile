.PHONY: install run debug

PYTHON ?= $(shell if command -v pyenv >/dev/null 2>&1; then pyenv which python3; else command -v python3; fi)

install:
	$(PYTHON) -m pip install -r requirements.txt

run:
	DEBUG=0 $(PYTHON) src/main.py

debug:
	DEBUG=1 $(PYTHON) src/main.py
