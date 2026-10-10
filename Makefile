# Makefile - outillage commun de l'equipe 20 (Guardians of Value).
# Cibles : install, test, lint, run-dashboard.
# Sous Windows, lancer via `make` (Git Bash / WSL / choco install make).

PYTHON ?= python

.PHONY: install test lint run-dashboard help

help:
	@echo "Cibles disponibles :"
	@echo "  make install        Installe les dependances + active le pre-commit hook"
	@echo "  make test           Lance les tests pytest (test de fumee par module)"
	@echo "  make lint           Verification syntaxique basique (compileall)"
	@echo "  make run-dashboard   Lance le dashboard Streamlit"

install:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt
	git config core.hooksPath .githooks
	@echo "OK : dependances installees et pre-commit hook active (core.hooksPath=.githooks)."

test:
	$(PYTHON) -m pytest -q

lint:
	$(PYTHON) -m compileall monitor detection llm response dashboard shared

run-dashboard:
	$(PYTHON) -m streamlit run dashboard/app.py
