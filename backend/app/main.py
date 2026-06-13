"""Fraction entrypoint: `python -m app.main`."""
from __future__ import annotations

import uvicorn

from .config import get_config


def main() -> None:
    cfg = get_config()
    uvicorn.run(
        "app.server:app",
        host=cfg.app.host,
        port=cfg.app.port,
        log_level=cfg.app.log_level,
        reload=False,
    )


if __name__ == "__main__":
    main()
