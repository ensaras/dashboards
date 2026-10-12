.PHONY: help export export-all diff test check

help:
	@echo "Usage:"
	@echo "  make export ORG=<slug>  Export dashboards for a specific organization"
	@echo "  make export-all         Export dashboards for all organizations"
	@echo "  make diff [ORG=<slug>]  Compare local dashboard JSON against live production"
	@echo "  make test               Run unit tests"
	@echo "  make check              Run linter and tests"

export:
	uv run python -m grafana_dashboards.tools.export --org $(ORG)

export-all:
	uv run python -m grafana_dashboards.tools.export --all

diff:
ifdef ORG
	uv run python -m grafana_dashboards.tools.diff --org $(ORG)
else
	uv run python -m grafana_dashboards.tools.diff --all
endif

test:
	uv run pytest -v

check:
	uv run ruff check .
	uv run pytest -v
