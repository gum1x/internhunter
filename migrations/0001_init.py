from __future__ import annotations

from internhunter.core.db import init_db


def run() -> None:
    init_db()


if __name__ == "__main__":
    run()
