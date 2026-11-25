# Makefile for the cache simulator. Recipe lines use TAB indentation.
PYTHON ?= python
RESULTS_DIR ?= data/results/main
TUNING_DIR ?= data/results/h-tuning
FIGURES_DIR ?= data/experiments/figures

.PHONY: help install test reference experiments experiments-small figures clean

help:
	@echo "Targets:"
	@echo "  install            Install the project in editable mode (dev + plot)"
	@echo "  test               Run the unittest suite (same command as CI)"
	@echo "  reference          Run the reference trace validator (same command as CI)"
	@echo "  experiments        Run the full d_experiments pipeline"
	@echo "  experiments-small  Run the d_experiments quick check (--scale small; data/experiments/run_all_small)"
	@echo "  figures            Generate figures (default: data/experiments/figures; 512 KiB)"
	@echo "                     Set FIGURES_DIR=data/results/figures to refresh formal figures (overwrites)"
	@echo "  clean              Remove caches and build artifacts (keeps data/)"

install:
	$(PYTHON) -m pip install -e ".[dev,plot]"

test:
	$(PYTHON) -m unittest discover -s tests -t . -v

reference:
	$(PYTHON) -m cache_simulator.reference_validation

experiments:
	$(PYTHON) d_experiments/run_all.py

experiments-small:
	$(PYTHON) d_experiments/run_all.py --scale small --output-dir data/experiments/run_all_small

figures:
	$(PYTHON) d_experiments/make_plots.py --results-dir "$(RESULTS_DIR)" --tuning-dir "$(TUNING_DIR)" --figures-dir "$(FIGURES_DIR)" --bar-capacity 512

clean:
	rm -rf build dist *.egg-info src/*.egg-info .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type f -name '*.py[cod]' -delete
