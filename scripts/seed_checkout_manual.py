"""Refresca el snapshot congelado del checkout manual P20-11.

Uso:
    python scripts/seed_checkout_manual.py          # escribe el JSON
    python scripts/seed_checkout_manual.py --check  # verifica sin escribir
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.platform.commerce.checkout_manual import snapshot_payload  # noqa: E402

SNAPSHOT = (
    _ROOT
    / "src"
    / "infrastructure"
    / "db_init"
    / "seeds"
    / "retail_checkout_manual.json"
)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    payload = snapshot_payload()
    if args and args[0] == "--check":
        frozen = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        if frozen != payload:
            print("SNAPSHOT DESACTUALIZADO: corre el script sin --check")  # noqa: T201
            return 1
        print("checkout snapshot OK")  # noqa: T201
        return 0
    SNAPSHOT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"checkout snapshot refrescado en {SNAPSHOT}")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
