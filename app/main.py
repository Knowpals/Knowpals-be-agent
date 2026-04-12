from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.config.loader import load_config
from app.ioc.pipeline import build_pipeline_worker


def main() -> None:
    cfg = load_config()
    build_pipeline_worker(cfg).run()


if __name__ == "__main__":
    main()
