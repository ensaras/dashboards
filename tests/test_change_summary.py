from grafana_dashboards.tools.change_summary import (
    DashboardChange,
    panel_change_summary,
    render_summary,
)


def test_panel_change_summary_counts_add_remove_and_modification():
    previous = {
        "panels": [
            {"id": 1, "title": "unchanged"},
            {"id": 2, "title": "before"},
            {"id": 3, "title": "removed"},
        ]
    }
    current = {
        "panels": [
            {"id": 1, "title": "unchanged"},
            {"id": 2, "title": "after"},
            {"id": 4, "title": "added"},
        ]
    }

    assert panel_change_summary(previous, current) == "1 added; 1 modified; 1 removed"


def test_render_summary_escapes_markdown_cells():
    result = render_summary(
        [DashboardChange("org", "team", "Flow | Rate", "Modified", "2 modified")]
    )

    assert "Flow \\| Rate" in result
