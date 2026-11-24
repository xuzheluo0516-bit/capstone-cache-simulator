# Makefile for the cache simulator. Recipe lines use TAB indentation.
PYTHON ?= python
RESULTS_DIR ?= data/results/main
TUNING_DIR ?= data/results/h-tuning
FIGURES_DIR ?= data/results/figures

.PHONY: help install test reference experiments figures clean

help:
	@echo "Targets:"
	@echo "  install     Install the project in editable mode"
	@echo "  test        Run the unittest suite (same command as CI)"
	@echo "  reference   Run the reference trace validator (same command as CI)"
	@echo "  experiments Run the batch experiment scaffold"
	@echo "  figures     Generate figures from committed experiment tables"
	@echo "  clean       Remove caches and build artifacts (keeps data/)"

install:
	$(PYTHON) -m pip install -e .

test:
	$(PYTHON) -m unittest discover -s tests -t . -v

reference:
	$(PYTHON) -m cache_simulator.reference_validation

experiments:
	$(PYTHON) -m cache_simulator.experiments

figures:
	$(PYTHON) d_experiments/make_plots.py --results-dir $(RESULTS_DIR) --tuning-dir $(TUNING_DIR) --figures-dir $(FIGURES_DIR)

clean:
	rm -rf build dist *.egg-info src/*.egg-info .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type f -name '*.py[cod]' -delete
