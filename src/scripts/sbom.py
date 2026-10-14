# =============================================================================
# SBOM — CycloneDX 1.5 desde los lockfiles congelados
# =============================================================================
# Sin red y sin dependencias nuevas: lee uv.lock (Python), portal/package-lock
# y sdk/node/package-lock (npm) y los Dockerfile (imágenes base). El SBOM es
# determinista: el serialNumber se deriva del contenido (mismo lock ⇒ mismo
# SBOM), lo que lo hace verificable en CI con `--check`.
#
# Uso:
#   python -m src.scripts.sbom --out artifacts/release/<sha>/sbom.json
#   python -m src.scripts.sbom --check --out artifacts/release/<sha>/sbom.json
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tomllib
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC_VERSION = "1.5"
_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # namespace DNS


def _pypi_components(lock: Path) -> list[dict]:
    data = tomllib.loads(lock.read_text(encoding="utf-8"))
    components = []
    for package in data.get("package") or []:
        name = str(package.get("name") or "")
        version = str(package.get("version") or "")
        if not name or not version:
            continue
        components.append(
            {
                "type": "library",
                "name": name,
                "version": version,
                "purl": f"pkg:pypi/{name}@{version}",
                "properties": [{"name": "zent:target", "value": "python"}],
            }
        )
    return components


def _npm_components(lock: Path, target: str) -> list[dict]:
    data = json.loads(lock.read_text(encoding="utf-8"))
    components = []
    for path, meta in (data.get("packages") or {}).items():
        if not path or not isinstance(meta, dict):
            continue
        version = meta.get("version")
        if not version:
            continue
        name = meta.get("name") or path.split("node_modules/")[-1]
        if not name:
            continue
        components.append(
            {
                "type": "library",
                "name": name,
                "version": str(version),
                "purl": f"pkg:npm/{name}@{version}",
                "properties": [
                    {"name": "zent:target", "value": target},
                    {"name": "zent:lockfile", "value": lock.name},
                ],
            }
        )
    return components


def _container_components(dockerfiles: list[Path]) -> list[dict]:
    components = []
    for dockerfile in dockerfiles:
        if not dockerfile.exists():
            continue
        for match in re.finditer(
            r"^FROM\s+(\S+)(?:\s+AS\s+(\S+))?", dockerfile.read_text(encoding="utf-8"), re.M
        ):
            image = match.group(1)
            if image.startswith("$") or image.startswith("scratch"):
                continue
            components.append(
                {
                    "type": "container",
                    "name": image,
                    "version": image.split(":")[-1] if ":" in image else "latest",
                    "properties": [
                        {"name": "zent:target", "value": dockerfile.name},
                        {
                            "name": "zent:pinned_by_digest",
                            "value": "true" if "@sha256:" in image else "false",
                        },
                    ],
                }
            )
    return components


def build_bom() -> dict:
    components = [
        *_pypi_components(ROOT / "uv.lock"),
        *_npm_components(ROOT / "portal" / "package-lock.json", "portal"),
        *_npm_components(ROOT / "sdk" / "node" / "package-lock.json", "sdk-node"),
        *_container_components(
            [ROOT / "Dockerfile.api", ROOT / "portal" / "Dockerfile"]
        ),
    ]
    components.sort(key=lambda c: (c["properties"][0]["value"], c["name"], c["version"]))
    digest = hashlib.sha256(
        json.dumps(components, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {
        "bomFormat": "CycloneDX",
        "specVersion": SPEC_VERSION,
        "serialNumber": f"urn:uuid:{uuid.uuid5(_NS, digest)}",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "component": {
                "type": "application",
                "name": "zent-rag",
                "version": "1.0.0",
            },
            "properties": [
                {"name": "zent:content_sha256", "value": digest},
                {"name": "zent:source", "value": "uv.lock + package-lock.json (frozen)"},
            ],
        },
        "components": components,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="SBOM CycloneDX de los artifacts desplegables")
    parser.add_argument("--out", default="")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    bom = build_bom()
    rendered = json.dumps(bom, indent=2, ensure_ascii=False) + "\n"
    out = Path(args.out) if args.out else ROOT / "artifacts" / "release" / "sbom.json"
    if args.check:
        expected = bom["metadata"]["properties"][0]["value"]
        current_digest = ""
        if out.exists():
            try:
                current = json.loads(out.read_text(encoding="utf-8"))
                current_digest = current["metadata"]["properties"][0]["value"]
            except Exception:  # noqa: BLE001 - SBOM ilegible = desactualizado
                current_digest = ""
        if current_digest != expected:
            print(f"SBOM desactualizado o lockfiles cambiaron: {out}")
            return 1
        print("SBOM OK (mismo contenido de dependencias)")
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(rendered, encoding="utf-8")
    print(
        json.dumps(
            {
                "out": str(out),
                "components": len(bom["components"]),
                "content_sha256": bom["metadata"]["properties"][0]["value"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
