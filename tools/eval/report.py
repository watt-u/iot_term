# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Print the 9.1b accuracy table (docs/evaluation.md) from docs/eval_data/trials.csv.

Usage:
    uv run tools/eval/report.py
    uv run tools/eval/report.py --csv docs/eval_data/trials.csv --subject alice

Rows with valid == 0 (no vision messages during the window) are skipped and counted.
Ratios with a zero denominator are shown as "n/a".
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_CSV = REPO / "docs" / "eval_data" / "trials.csv"

# Condition keys stored in trials.csv -> row names in the docs/evaluation.md table.
# Keep in sync with tools/eval/trials.py.
CONDITIONS: dict[str, str] = {
    "good": "Good light, no glasses",
    "dim": "Dim light (cabin at dusk)",
    "glasses": "Clear glasses",
    "sunglasses": "Sunglasses",
    "head30": "Head turned about 30°",
}


def _truthy(value: str | None) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def is_valid(row: dict) -> bool:
    # Older rows without a "valid" column count as valid.
    v = row.get("valid")
    return v is None or v == "" or _truthy(v)


def counts(rows: list[dict]) -> dict[str, int]:
    """Confusion-matrix counts for valid rows (label pos/neg, fired 0/1)."""
    c = {"TP": 0, "FN": 0, "FP": 0, "TN": 0}
    for r in rows:
        if not is_valid(r):
            continue
        pos = r["label"].strip().lower() in {"pos", "positive", "1"}
        fired = _truthy(r["fired"])
        if pos and fired:
            c["TP"] += 1
        elif pos:
            c["FN"] += 1
        elif fired:
            c["FP"] += 1
        else:
            c["TN"] += 1
    return c


def _ratio(num: int, den: int) -> float | None:
    return num / den if den else None


def metrics(c: dict[str, int]) -> dict[str, float | None]:
    total = c["TP"] + c["FN"] + c["FP"] + c["TN"]
    return {
        "accuracy": _ratio(c["TP"] + c["TN"], total),
        "precision": _ratio(c["TP"], c["TP"] + c["FP"]),
        "recall": _ratio(c["TP"], c["TP"] + c["FN"]),
    }


def fmt_pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}%"


def load(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def table(rows: list[dict]) -> str:
    lines = [
        "| Condition | TP | FN | FP | TN | Accuracy | Precision | Recall |",
        "|---|---|---|---|---|---|---|---|",
    ]

    def line(name: str, subset: list[dict]) -> str:
        c = counts(subset)
        m = metrics(c)
        return (
            f"| {name} | {c['TP']} | {c['FN']} | {c['FP']} | {c['TN']} | "
            f"{fmt_pct(m['accuracy'])} | {fmt_pct(m['precision'])} | {fmt_pct(m['recall'])} |"
        )

    for key, name in CONDITIONS.items():
        lines.append(line(name, [r for r in rows if r["condition"] == key]))
    # Any condition keys not in the standard list get their own row.
    for key in sorted({r["condition"] for r in rows} - set(CONDITIONS)):
        lines.append(line(key, [r for r in rows if r["condition"] == key]))
    lines.append(line("**All**", rows))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Print the accuracy table from trials.csv as markdown.")
    p.add_argument("--csv", type=Path, default=DEFAULT_CSV, help=f"trials CSV (default: {DEFAULT_CSV.relative_to(REPO)})")
    p.add_argument("--subject", action="append", help="only include this subject (repeatable)")
    args = p.parse_args(argv)

    if not args.csv.exists():
        print(f"error: {args.csv} not found. Run tools/eval/trials.py first.", file=sys.stderr)
        return 1
    rows = load(args.csv)
    if args.subject:
        rows = [r for r in rows if r.get("subject") in set(args.subject)]

    invalid = sum(1 for r in rows if not is_valid(r))
    print(table(rows))
    print()
    subjects = sorted({r.get("subject", "") for r in rows})
    print(f"{len(rows) - invalid} valid trials, {invalid} invalid (skipped); subjects: {', '.join(subjects) or '-'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
