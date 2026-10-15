PYTHON := .venv/bin/python
export OMP_NUM_THREADS := 1
export OPENBLAS_NUM_THREADS := 1
export MKL_NUM_THREADS := 1
.PHONY: setup demo serve pages test lint check evaluate reproduce reset
setup:
	python3 scripts/setup.py
demo: setup
	$(PYTHON) -m riskreplay demo
serve: setup
	$(PYTHON) -m riskreplay serve
pages: demo
	$(PYTHON) scripts/build_pages.py
test: setup
	$(PYTHON) -m pytest -q
lint: setup
	$(PYTHON) -m ruff check riskreplay tests scripts
	$(PYTHON) -m compileall -q riskreplay scripts
check: lint test
evaluate: setup
	$(PYTHON) -m riskreplay evaluate
reproduce: setup
	$(PYTHON) -m riskreplay verify-reproducibility
reset:
	$(PYTHON) -m riskreplay reset --yes
