"""Unit tests for dashboard normalizer."""

import json
from pathlib import Path

from grafana_dashboards.tools.normalizer import (
    MANAGED_TAG,
    normalize_dashboard,
    serialize_dashboard,
)


def test_normalize_strips_volatile_fields():
    raw = {
        "id": 123,
        "version": 45,
        "iteration": 1729000000,
        "title": "Plant Overview",
        "uid": "plant-ov-01",
        "editable": True,
        "tags": ["prod"],
        "panels": [
            {
                "id": 1,
                "title": "Flow Rate",
                "iteration": 9999,
            }
        ],
    }

    normalized = normalize_dashboard(raw)

    # Volatile fields stripped
    assert "id" not in normalized
    assert "version" not in normalized
    assert "iteration" not in normalized
    assert "iteration" not in normalized["panels"][0]

    # Invariants enforced
    assert normalized["editable"] is False
    assert MANAGED_TAG in normalized["tags"]
    assert "prod" in normalized["tags"]
    assert normalized["uid"] == "plant-ov-01"


def test_normalize_handles_api_envelope():
    raw_api_envelope = {
        "meta": {"canSave": True, "created": "2026-01-01"},
        "dashboard": {
            "id": 55,
            "version": 12,
            "title": "Enveloped Dashboard",
            "uid": "env-01",
            "editable": True,
        },
    }

    normalized = normalize_dashboard(raw_api_envelope)
    assert "meta" not in normalized
    assert "id" not in normalized
    assert normalized["title"] == "Enveloped Dashboard"
    assert normalized["editable"] is False
    assert normalized["tags"] == [MANAGED_TAG]


def test_normalize_deterministic_byte_for_byte():
    data_a = {
        "z_field": "last",
        "a_field": "first",
        "tags": ["beta", "alpha"],
        "panels": [{"b": 2, "a": 1}],
    }
    data_b = {
        "a_field": "first",
        "z_field": "last",
        "tags": ["alpha", "beta"],
        "panels": [{"a": 1, "b": 2}],
    }

    str_a = serialize_dashboard(normalize_dashboard(data_a))
    str_b = serialize_dashboard(normalize_dashboard(data_b))

    assert str_a == str_b
    assert str_a.endswith("\n")


def test_normalize_against_real_exported_sample():
    sample_path = Path("C:/Users/Pradeep/Workspaces/EnsarasWorkspace/docs/grafana_dashboards_json/orgs/circle-cbg-india-pvt-ltd/meerut-cbg-plant/CBG Production-1792127140200.json")
    if not sample_path.exists():
        return

    with open(sample_path, "r", encoding="utf-8") as f:
        raw_json = json.load(f)

    assert raw_json.get("id") == 202
    assert raw_json.get("version") == 97
    assert raw_json.get("editable") is True

    normalized = normalize_dashboard(raw_json)

    assert "id" not in normalized
    assert "version" not in normalized
    assert normalized["editable"] is False
    assert MANAGED_TAG in normalized["tags"]
    assert normalized["uid"] == "c53aefd4-413c-4b93-8781-e866d07a2905"

    serialized = serialize_dashboard(normalized)
    assert isinstance(serialized, str)
    assert serialized.endswith("\n")
