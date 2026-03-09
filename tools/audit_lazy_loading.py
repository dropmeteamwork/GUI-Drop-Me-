"""
Audit QML files for Image elements that miss lazy-loading hints.

Usage:
  python tools/audit_lazy_loading.py --qml-dir qml/DropMeQML --report docs/LAZY_LOADING_AUDIT.md
"""

from __future__ import annotations

import argparse
from pathlib import Path


def image_blocks(text: str):
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if "Image {" in line:
            start = i
            depth = line.count("{") - line.count("}")
            i += 1
            while i < len(lines) and depth > 0:
                depth += lines[i].count("{") - lines[i].count("}")
                i += 1
            end = min(i, len(lines))
            block = "\n".join(lines[start:end])
            yield start + 1, block
            continue
        i += 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qml-dir", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()

    qml_dir = Path(args.qml_dir).resolve()
    report_path = Path(args.report).resolve()

    findings: list[str] = []

    for qml_file in sorted(qml_dir.rglob("*.qml")):
        text = qml_file.read_text(encoding="utf-8", errors="ignore")
        for line_no, block in image_blocks(text):
            block_lower = block.lower()
            missing_async = "asynchronous:" not in block_lower
            missing_cache = "cache:" not in block_lower
            if missing_async or missing_cache:
                misses = []
                if missing_async:
                    misses.append("asynchronous")
                if missing_cache:
                    misses.append("cache")
                rel = qml_file.as_posix()
                findings.append(f"- {rel}:{line_no} missing {', '.join(misses)}")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    content = [
        "# Lazy Loading Audit",
        "",
        "This report lists QML Image blocks missing explicit lazy-loading hints.",
        "",
    ]
    if findings:
        content.extend(findings)
    else:
        content.append("- No missing lazy-loading hints detected.")

    report_path.write_text("\n".join(content) + "\n", encoding="utf-8")
    print(f"Wrote {report_path}")
    print(f"Findings: {len(findings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
