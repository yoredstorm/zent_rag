# =============================================================================
# Flags Inventory — inventario de flags de runtime (auditoría, solo lectura).
# =============================================================================
# Enumera los campos tipo flag de `Settings` (nombre, default, propósito) y los
# contrasta con `.env.example` para detectar drift (clave documentada sin campo
# o flag sin documentar). No instancia Settings: lee `model_fields`.
#
# Uso:
#   python -m src.scripts.flags_inventory
#   python -m src.scripts.flags_inventory --format json --out artifacts/flags.json
#   python -m src.scripts.flags_inventory --check-drift   # exit 1 si hay drift
# =============================================================================
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENV_EXAMPLE = ROOT / ".env.example"

FLAG_PREFIXES = (
    "RUNTIME_",
    "ADAPTIVE_RAG_",
    "DECISION_",
    "JEV_",
    "NARRATIVE_",
    "LONG_CONTEXT_",
    "GATEWAY_",
    "EMBEDDING_",
    "LLM_",
    "CACHE_",
)
SECRET_MARKERS = ("API_KEY", "SECRET", "PASSWORD", "TOKEN")


def _default_of(field: object) -> str:
    default = getattr(field, "default", None)
    factory = getattr(field, "default_factory", None)
    if default is not None and str(default) != "PydanticUndefined":
        return str(default)
    if factory is not None:
        try:
            return str(factory())
        except Exception:  # noqa: BLE001 — inventario, nunca rompe
            return "<factory>"
    return ""


def collect_flags() -> list[dict]:
    from src.core.config import Settings

    flags: list[dict] = []
    for name, field in Settings.model_fields.items():
        if not name.startswith(FLAG_PREFIXES):
            continue
        if any(marker in name for marker in SECRET_MARKERS):
            continue
        flags.append(
            {
                "flag": f"RAG_{name}",
                "field": name,
                "default": _default_of(field),
                "purpose": str(getattr(field, "description", "") or "").strip(),
            }
        )
    return sorted(flags, key=lambda item: item["field"])


def collect_env_example() -> dict[str, str]:
    values: dict[str, str] = {}
    if not ENV_EXAMPLE.exists():
        return values
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip()
    return values


def compute_drift(flags: list[dict], env_keys: dict[str, str]) -> dict[str, list[str]]:
    flag_names = {item["flag"] for item in flags}
    env_flags = {
        key for key in env_keys if key.startswith(FLAG_PREFIXES)
    }
    return {
        "en_env_sin_setting": sorted(env_flags - flag_names),
        "setting_sin_env_example": sorted(flag_names - env_flags),
    }


def render_markdown(flags: list[dict], drift: dict[str, list[str]]) -> str:
    lines = [
        "# Flags de runtime — inventario",
        "",
        "Generado por `python -m src.scripts.flags_inventory` (solo lectura).",
        "`default` es el default del código; el `.env` local puede pisarlo.",
        "",
        "| Flag | Default | Propósito |",
        "|---|---|---|",
    ]
    for item in flags:
        purpose = item["purpose"].replace("\n", " ").replace("|", "/")
        if len(purpose) > 160:
            purpose = purpose[:157] + "..."
        default = item["default"].replace("|", "/") or "-"
        lines.append(f"| `{item['flag']}` | `{default}` | {purpose} |")
    lines += ["", "## Drift con .env.example", ""]
    if drift["en_env_sin_setting"]:
        lines.append(
            "- En `.env.example` sin campo en Settings: "
            + ", ".join(f"`{item}`" for item in drift["en_env_sin_setting"])
        )
    if drift["setting_sin_env_example"]:
        lines.append(
            "- Flag de Settings ausente en `.env.example`: "
            + ", ".join(f"`{item}`" for item in drift["setting_sin_env_example"])
        )
    if not drift["en_env_sin_setting"] and not drift["setting_sin_env_example"]:
        lines.append("- Sin drift: `.env.example` y Settings coinciden.")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inventario de flags de runtime")
    parser.add_argument("--format", choices=("md", "json"), default="md")
    parser.add_argument("--out", default="")
    parser.add_argument("--check-drift", action="store_true")
    args = parser.parse_args(argv)

    flags = collect_flags()
    drift = compute_drift(flags, collect_env_example())
    payload = {"flags": flags, "drift": drift} if args.format == "json" else None
    text = (
        json.dumps(payload, ensure_ascii=False, indent=2)
        if payload is not None
        else render_markdown(flags, drift)
    )
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + ("\n" if not text.endswith("\n") else ""), encoding="utf-8")
        print(f"escrito: {out_path}")
    else:
        print(text)
    if args.check_drift and (drift["en_env_sin_setting"] or drift["setting_sin_env_example"]):
        print(
            "drift detectado: "
            f"env_sin_setting={len(drift['en_env_sin_setting'])} "
            f"setting_sin_env={len(drift['setting_sin_env_example'])}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
