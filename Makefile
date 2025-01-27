.PHONY: clean clean-test clean-pyc clean-build docs help
.DEFAULT_GOAL := help

define BROWSER_PYSCRIPT
import os, webbrowser, sys

from urllib.request import pathname2url

webbrowser.open("file://" + pathname2url(os.path.abspath(sys.argv[1])))
endef
export BROWSER_PYSCRIPT

define PRINT_HELP_PYSCRIPT
import re, sys

for line in sys.stdin:
	match = re.match(r'^([a-zA-Z_-]+):.*?## (.*)$$', line)
	if match:
		target, help = match.groups()
		print("%-20s %s" % (target, help))
endef
export PRINT_HELP_PYSCRIPT

BROWSER := python -c "$$BROWSER_PYSCRIPT"

help:
	@python -c "$$PRINT_HELP_PYSCRIPT" < $(MAKEFILE_LIST)

fmt: ## format style with black and isort
	poetry run black .
	poetry run isort .

test: ## run tests quickly with pytest
	poetry run pytest

install: clean ## install the package to the active Python's site-packages
	poetry install

mypy: ## run type hinting check
	poetry run mypy pydapper

test-cov: ## run the tests with coverage turned on
	poetry run pytest --cov=. --cov-branch -v --durations=25

cov: ## check code coverage and run the html report
	poetry run pytest --cov=. --cov-branch -v --durations=25
	poetry run coverage report -m
	poetry run coverage html
	$(BROWSER) htmlcov/index.html

clean: clean-build clean-pyc clean-test ## remove all build, test, coverage and Python artifacts

clean-build: ## remove build artifacts
	rm -fr build/
	rm -fr dist/
	rm -fr .eggs/
	find . -name '*.egg-info' -exec rm -fr {} +
	find . -name '*.egg' -exec rm -f {} +

clean-pyc: ## remove Python file artifacts
	find . -name '*.pyc' -exec rm -f {} +
	find . -name '*.pyo' -exec rm -f {} +
	find . -name '*~' -exec rm -f {} +
	find . -name '__pycache__' -exec rm -fr {} +

docs: ## spin up a local server for mkdocs
	poetry run mkdocs serve

resetlock: ## reset the poetry lock file from main
	rm poetry.lock
	git checkout main poetry.lock
	poetry lock --no-update
