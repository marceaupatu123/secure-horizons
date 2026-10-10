# Makefile - outillage commun de l'equipe 20 (Guardians of Value).
# Cibles : install, test, lint, data, run-dashboard.
# Sous Windows, lancer via `make` (Git Bash / WSL / choco install make).

PYTHON ?= python
ARGS ?= list

.PHONY: install test lint data calibrate run-dashboard dashboard-progress demo help

help:
	@echo "Cibles disponibles :"
	@echo "  make install            Installe les dependances + active le pre-commit hook"
	@echo "  make test               Lance les tests pytest (test de fumee par module)"
	@echo "  make lint               Verification syntaxique basique (compileall)"
	@echo "  make data               Genere les jeux synthetiques JSONL (data/generated, SEED=42)"
	@echo "  make calibrate          Mesure les valeurs de #3 sur le trafic synthetique (data/generated)"
	@echo "  make run-dashboard      Lance le dashboard metier Streamlit (dashboard/app.py)"
	@echo "  make dashboard-progress Lance le tableau de bord d'avancement (issues GitHub via gh)"
	@echo "  make demo ARGS=\"run A --seed 20\"  Liste/lance les scenarios de demo (#47)"

install:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt
	git config core.hooksPath .githooks
	-chmod +x .githooks/pre-commit
	@echo "OK : dependances installees et pre-commit hook active (core.hooksPath=.githooks)."

test:
	$(PYTHON) -m pytest -q

lint:
	$(PYTHON) -m compileall monitor detection llm response dashboard shared data

SEED ?= 42

data:
	$(PYTHON) -m data.generate --scenario all --seed $(SEED)

calibrate:
	$(PYTHON) -m data.calibrate --seed $(SEED)

run-dashboard:
	$(PYTHON) -m streamlit run dashboard/app.py

dashboard-progress:
	$(PYTHON) -m streamlit run tools/progress_dashboard.py
demo:
	$(PYTHON) -m dashboard.demo $(ARGS)
