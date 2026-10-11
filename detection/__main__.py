"""Point d'entree du module detection : `python -m detection`.

Branche les surveillants de `detection/detector.py` sur le monitor (LIVE,
Fuji) ou sur un JSONL synthetique (`--replay`). Voir `detection/pipeline.py`
et `python -m detection --help`.
"""

from __future__ import annotations

from detection.pipeline import main

if __name__ == "__main__":
    raise SystemExit(main())
