"""Comprehensive unit tests for dashboard normalizer.

Tests:
- Stripping of volatile fields (id, version, iteration) at top-level and in nested panel structures.
- Tag enforcement: injecting 'managed-by-git', deduplicating, sorting, and handling empty/malformed tags.
- Invariant enforcement: 'editable: false'.
- Envelope unwrapping: Grafana API response {"meta": {...}, "dashboard": {...}}.
- Deterministic serialization: byte-for-byte reproducibility regardless of key insertion order.
- Real sample tests against all exported sample dashboards in docs/grafana_dashboards_json/.
"""

import json
from pathlib import Path

import pytest

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
                "panels": [
                    {
                        "id": 2,
                        "iteration": 8888,
                        "title": "Nested Panel",
                    }
                ],
            }
        ],
    }

    normalized = normalize_dashboard(raw)

    # Top-level volatile fields stripped
    assert "id" not in normalized
    assert "version" not in normalized
    assert "iteration" not in normalized

    # Nested panel volatile fields stripped
    assert "iteration" not in normalized["panels"][0]
    assert "iteration" not in normalized["panels"][0]["panels"][0]

    # Panel IDs are preserved for panel references
    assert normalized["panels"][0]["id"] == 1
    assert normalized["panels"][0]["panels"][0]["id"] == 2

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


def test_normalize_handles_string_input():
    raw_str = json.dumps(
        {
            "id": 10,
            "version": 2,
            "title": "String Input Dashboard",
            "uid": "str-01",
            "editable": True,
        }
    )

    normalized = normalize_dashboard(raw_str)
    assert "id" not in normalized
    assert normalized["title"] == "String Input Dashboard"
    assert normalized["editable"] is False
    assert normalized["tags"] == [MANAGED_TAG]


def test_normalize_invalid_string_input():
    with pytest.raises(json.JSONDecodeError):
        normalize_dashboard("invalid-json-{")


def test_normalize_deeply_nested_structures():
    raw = {
        "title": "Deep Nested",
        "uid": "deep-01",
        "nested_dict": {
            "level1": {
                "iteration": 100,
                "level2": {
                    "iteration": 200,
                    "target": "metric_a",
                },
            }
        },
        "nested_list": [
            [
                {"iteration": 300, "val": 1},
                {"iteration": 400, "val": 2},
            ]
        ],
    }

    normalized = normalize_dashboard(raw)
    assert "iteration" not in normalized["nested_dict"]["level1"]
    assert "iteration" not in normalized["nested_dict"]["level1"]["level2"]
    assert normalized["nested_dict"]["level1"]["level2"]["target"] == "metric_a"
    assert "iteration" not in normalized["nested_list"][0][0]
    assert "iteration" not in normalized["nested_list"][0][1]
    assert normalized["nested_list"][0][0]["val"] == 1


def test_normalize_tags_variations():
    # Test duplicate tags and None / malformed tags
    raw = {
        "title": "Tags Test",
        "uid": "tag-01",
        "tags": ["managed-by-git", "beta", "alpha", "beta", ""],
    }
    normalized = normalize_dashboard(raw)
    assert normalized["tags"] == ["alpha", "beta", "managed-by-git"]

    # Test missing tags key entirely
    raw_no_tags = {"title": "No Tags", "uid": "tag-02"}
    normalized_no_tags = normalize_dashboard(raw_no_tags)
    assert normalized_no_tags["tags"] == ["managed-by-git"]

    # Test non-list tags key
    raw_invalid_tags = {"title": "Invalid Tags", "uid": "tag-03", "tags": "invalid"}
    normalized_invalid_tags = normalize_dashboard(raw_invalid_tags)
    assert normalized_invalid_tags["tags"] == ["managed-by-git"]


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


def test_serialize_dashboard_formatting_and_unicode():
    data = {
        "title": "Test Title – CBG \u00b0C",
        "uid": "unicode-01",
        "editable": False,
        "tags": [MANAGED_TAG],
    }
    serialized = serialize_dashboard(data)

    assert '  "editable": false,' in serialized
    assert "°C" in serialized
    assert serialized.endswith("\n")


@pytest.mark.parametrize(
    "sample_filename, expected_uid",
    [
        ("CBG Production-1792127140200.json", "c53aefd4-413c-4b93-8781-e866d07a2905"),
        ("Digester Data-1792127390606.json", "e5586707-f8eb-4c4a-a696-e81454626d9a"),
        ("Meerut CBG \u2013 Data Health-1792127669456.json", "meerut-cbg-data-health"),
    ],
)
def test_normalize_against_real_exported_samples(sample_filename, expected_uid):
    sample_dir = Path(
        "C:/Users/Pradeep/Workspaces/EnsarasWorkspace/docs/grafana_dashboards_json/orgs/circle-cbg-india-pvt-ltd/meerut-cbg-plant"
    )
    sample_path = sample_dir / sample_filename
    if not sample_path.exists():
        pytest.skip(f"Sample file {sample_filename} not found")

    with open(sample_path, "r", encoding="utf-8") as f:
        raw_json = json.load(f)

    normalized = normalize_dashboard(raw_json)

    assert "id" not in normalized
    assert "version" not in normalized
    assert normalized["editable"] is False
    assert MANAGED_TAG in normalized["tags"]
    assert normalized["uid"] == expected_uid

    serialized = serialize_dashboard(normalized)
    assert isinstance(serialized, str)
    assert serialized.endswith("\n")
