"""Entry point: run the HuggingFace top-3 text-generation model comparison.

Usage:
    uv run python run_comparison.py            # run agent only
    uv run python run_comparison.py --html     # run agent + generate HTML replay
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

from flow import Executor

QUERY = (
    "Compare 5 AI coding tools by free plan and paid plan in OLLAMA - https://ollama.com/library"
)


async def _run() -> str:
    sid = f"s9-{uuid.uuid4().hex[:8]}"
    print(f"Session: {sid}")
    await Executor().run(QUERY, session_id=sid)
    return sid


def main() -> None:
    generate_html = "--html" in sys.argv
    sid = asyncio.run(_run())
    if generate_html:
        from replay_html import generate_html as gen
        out_path = Path(f"replay_{sid}.html")
        html = gen(sid)
        out_path.write_text(html, encoding="utf-8")
        print(f"HTML report written to {out_path}")


if __name__ == "__main__":
    main()
