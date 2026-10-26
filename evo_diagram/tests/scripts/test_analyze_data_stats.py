from __future__ import annotations

import json

from evo_diagram.scripts.analyze_data_stats import format_summary, main, summarize_dataset


def test_summarize_dataset_counts_types_areas_and_text_lengths():
    records = [
        {
            "diagram_type": "flowchart",
            "content_area": "ops",
            "content": "abcd",
            "query": "go",
        },
        {
            "diagram_type": "architecture",
            "content_area": "ops",
            "content": "abcdef",
            "query": "ship",
        },
    ]

    summary = summarize_dataset(records)

    assert summary["total_records"] == 2
    assert summary["diagram_type_counts"] == {"flowchart": 1, "architecture": 1}
    assert summary["content_area_counts"] == {"ops": 2}
    assert summary["length_stats"]["content"] == {"mean": 5, "min": 4, "max": 6}
    assert summary["length_stats"]["query"] == {"mean": 3, "min": 2, "max": 4}
    assert "Total records: 2" in format_summary(summary)


def test_analyze_data_stats_cli_json_output(tmp_path, capsys):
    dataset_path = tmp_path / "data.json"
    dataset_path.write_text(
        json.dumps(
            [
                {
                    "diagram_type": "flowchart",
                    "content_area": "ops",
                    "content": "abc",
                    "query": "q",
                }
            ],
        ),
        encoding="utf-8",
    )

    assert main(["--input-json", str(dataset_path), "--json"]) == 0

    out = json.loads(capsys.readouterr().out)
    assert out["total_records"] == 1
    assert out["diagram_type_counts"] == {"flowchart": 1}
