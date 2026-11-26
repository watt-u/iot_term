"""Tests for the metric math in report.py.  Run: uv run --with pytest pytest tools/eval"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import report  # noqa: E402

SAMPLE = """\
timestamp,subject,condition,label,fired,min_ear,frames_seen,valid
2026-11-30T10:00:00+07:00,alice,good,pos,1,0.12,22,1
2026-11-30T10:00:15+07:00,alice,good,pos,1,0.10,21,1
2026-11-30T10:00:30+07:00,alice,good,pos,0,0.19,20,1
2026-11-30T10:00:45+07:00,alice,good,neg,0,0.25,22,1
2026-11-30T10:01:00+07:00,alice,good,neg,1,0.15,22,1
2026-11-30T10:01:15+07:00,alice,good,neg,0,0.24,21,1
2026-11-30T10:01:30+07:00,alice,good,neg,0,,0,0
2026-11-30T10:02:00+07:00,bob,sunglasses,pos,0,,20,1
2026-11-30T10:02:15+07:00,bob,sunglasses,neg,0,,20,1
"""


def load_sample(tmp_path):
    p = tmp_path / "trials.csv"
    p.write_text(SAMPLE, encoding="utf-8")
    return report.load(p)


def by_cond(rows, key):
    return [r for r in rows if r["condition"] == key]


def test_counts_skip_invalid(tmp_path):
    rows = load_sample(tmp_path)
    assert report.counts(by_cond(rows, "good")) == {"TP": 2, "FN": 1, "FP": 1, "TN": 2}
    assert report.counts(rows) == {"TP": 2, "FN": 2, "FP": 1, "TN": 3}


def test_metrics_values(tmp_path):
    rows = load_sample(tmp_path)
    m = report.metrics(report.counts(by_cond(rows, "good")))
    assert m["accuracy"] == 4 / 6
    assert m["precision"] == 2 / 3
    assert m["recall"] == 2 / 3

    m_all = report.metrics(report.counts(rows))
    assert m_all["accuracy"] == 5 / 8
    assert m_all["precision"] == 2 / 3
    assert m_all["recall"] == 2 / 4


def test_divide_by_zero():
    # Sunglasses: one FN, one TN, never fired -> precision undefined.
    m = report.metrics({"TP": 0, "FN": 1, "FP": 0, "TN": 1})
    assert m["precision"] is None
    assert m["recall"] == 0.0
    assert m["accuracy"] == 0.5
    # No trials at all.
    empty = report.metrics({"TP": 0, "FN": 0, "FP": 0, "TN": 0})
    assert empty == {"accuracy": None, "precision": None, "recall": None}
    assert report.fmt_pct(None) == "n/a"


def test_table_rows(tmp_path):
    rows = load_sample(tmp_path)
    out = report.table(rows).splitlines()
    assert out[0].startswith("| Condition | TP | FN | FP | TN |")
    assert "| Good light, no glasses | 2 | 1 | 1 | 2 | 66.7% | 66.7% | 66.7% |" in out
    assert "| Sunglasses | 0 | 1 | 0 | 1 | 50.0% | n/a | 0.0% |" in out
    assert "| Dim light (cabin at dusk) | 0 | 0 | 0 | 0 | n/a | n/a | n/a |" in out
    assert out[-1] == "| **All** | 2 | 2 | 1 | 3 | 62.5% | 66.7% | 50.0% |"
    assert len(out) == 2 + len(report.CONDITIONS) + 1


def test_main_prints_table(tmp_path, capsys):
    p = tmp_path / "trials.csv"
    p.write_text(SAMPLE, encoding="utf-8")
    assert report.main(["--csv", str(p), "--subject", "bob"]) == 0
    out = capsys.readouterr().out
    assert "| **All** | 0 | 1 | 0 | 1 | 50.0% | n/a | 0.0% |" in out
    assert "2 valid trials, 0 invalid" in out
