.PHONY: help export export-all diff validate deploy test check

help:
	@echo "Usage:"
	@echo "  make export ORG=<slug>  Export dashboards for a specific organization"
	@echo "  make export-all         Export dashboards for all organizations"
	@echo "  make diff [ORG=<slug>]  Compare local dashboard JSON against live production"
	@echo "  make validate          Run offline JSON, identity, reference, isolation, and deletion checks"
	@echo "  make deploy ENV=<staging|production> BASE=<ref> [HEAD=<ref>]  Deploy changed dashboards"
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

validate:
	uv run python -m grafana_dashboards.tools.validate $(if $(BASE),--base-ref $(BASE),) $(if $(HEAD),--head-ref $(HEAD),)

deploy:
	uv run python -m grafana_dashboards.tools.deploy --environment $(ENV) --base-ref $(BASE) $(if $(HEAD),--head-ref $(HEAD),)

test:
	uv run pytest -v

check:
	uv run ruff check .
	uv run pytest -v
