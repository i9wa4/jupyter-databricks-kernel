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

install:  ## Install mise tools
	mise install

sync:  ## Sync Python dependencies with uv
	mise exec -- uv sync --frozen

test:  ## Run tests
	mise exec -- uv run pytest

jupyter:  ## Start JupyterLab
	mise exec -- uv run jupyter-lab --debug
