SHELL := /bin/bash
.SHELLFLAGS := -o errexit -o nounset -o pipefail -c
.DEFAULT_GOAL := help

PHONY_TARGETS := $(shell grep -E '^[a-zA-Z_-]+:' $(MAKEFILE_LIST) | sed 's/://')
.PHONY: $(PHONY_TARGETS)

help:  ## Show this help
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Targets:'
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

sync:  ## Sync Python dependencies with uv
	uv sync --frozen

test:  ## Run tests
	uv run pytest

jupyter:  ## Start JupyterLab
	uv run jupyter-lab

jupyter-debug:  ## Start JupyterLab in debug mode
	uv run jupyter-lab --debug
