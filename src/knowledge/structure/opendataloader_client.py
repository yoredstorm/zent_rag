# =============================================================================
# OpenDataLoader PDF — cliente JVM (cliente oficial opendataloader-pdf)
# =============================================================================
# El paquete oficial es un wrapper Python sobre el CLI Java. Acá encapsulamos:
#   - resolución del binario java (11+) sin depender del PATH del host
#   - construcción de flags (local/hybrid, struct tree, tablas, orden lectura)
#   - ejecución por documento en un directorio temporales aislado
#   - lectura del JSON como única fuente canónica (nunca Markdown)
#
# Un convert() lanza una JVM. El caller decide cuándo pagar ese costo; este
# módulo no cachea documentos, solo versiones de Java.
# =============================================================================
from __future__ import annotations

import importlib.resources as resources
import json
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Callable

from src.knowledge.structure.base import StructuredParserError

_LIB_NAME = "opendataloader-pdf"
_JAR_NAME = "opendataloader-pdf-cli.jar"
_JAR_PACKAGE = "opendataloader_pdf"
_MIN_JAVA_MAJOR = 11
_VERSION_RE = re.compile(r'version "(\d+)(?:\.(\d+))?')

_DEFAULT_TIMEOUT_SECONDS = 180

#: Formatos soportados por el CLI (comma-separated en una sola JVM).
SUPPORTED_FORMATS: tuple[str, ...] = ("json", "markdown", "html", "text", "pdf", "tagged-pdf")

#: Separador de página por defecto del Markdown LLM-ready (rastreable).
DEFAULT_MARKDOWN_PAGE_SEPARATOR = "<!-- page:%%page-number%% -->"


@dataclass(frozen=True, kw_only=True)
class OpenDataLoaderOptions:
    """Flags efectivos del CLI. El parser no lee variables globales."""

    java: str = ""
    java_home: str = ""
    mode: str = "local"  # local | hybrid
    hybrid_backend: str = "docling-fast"
    hybrid_url: str = ""
    hybrid_mode: str = "auto"
    force_ocr: bool = False
    use_struct_tree: bool | None = None  # None = decidir por PDF (auto)
    table_method: str = "default"
    reading_order: str = "xycut"
    include_header_footer: bool = False
    threads: int = 1
    timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS
    extra_args: tuple[str, ...] = ()
    #: Formatos de UNA sola conversión (comma-separated dentro del CLI).
    #: Default histórico: solo JSON (StructuredDocument). Con "markdown" nace
    #: la representación LLM-ready del mismo run.
    formats: tuple[str, ...] = ("json",)
    #: Separador de página del Markdown (%%page-number%% se sustituye).
    markdown_page_separator: str = DEFAULT_MARKDOWN_PAGE_SEPARATOR
    #: HTML dentro del Markdown para tablas con spans complejos (opcional).
    markdown_with_html: bool = False

    def fingerprint(self) -> dict[str, Any]:
        """Metadata serializable de la corrida (provenance del parser)."""
        return {
            "mode": self.mode,
            "hybrid_backend": self.hybrid_backend if self.mode == "hybrid" else None,
            "hybrid_url": self.hybrid_url if self.mode == "hybrid" else None,
            "hybrid_mode": self.hybrid_mode if self.mode == "hybrid" else None,
            "force_ocr": self.force_ocr,
            "use_struct_tree": self.use_struct_tree,
            "table_method": self.table_method,
            "reading_order": self.reading_order,
            "include_header_footer": self.include_header_footer,
            "threads": self.threads,
            "formats": list(self.formats),
            "markdown_with_html": bool(self.markdown_with_html),
            "markdown_page_separator": (
                self.markdown_page_separator if "markdown" in self.formats else None
            ),
        }

    @property
    def wants_markdown(self) -> bool:
        return "markdown" in {str(item).strip().lower() for item in self.formats}

    def resolved_formats(self) -> tuple[str, ...]:
        """Formatos válidos y ordenados; JSON primero (canónico)."""
        requested = [
            str(item).strip().lower()
            for item in self.formats
            if str(item).strip().lower() in SUPPORTED_FORMATS
        ]
        if not requested:
            requested = ["json"]
        ordered = ["json", *[item for item in requested if item != "json"]]
        return tuple(dict.fromkeys(ordered))


@dataclass(frozen=True)
class OpenDataLoaderConversion:
    """Resultado crudo de UNA corrida ODL: JSON canónico + representaciones."""

    data: dict[str, Any]
    output_json_bytes: int = 0
    #: Proyección LLM-ready del MISMO run (vacío si no se pidió markdown).
    markdown: str = ""
    output_markdown_bytes: int = 0
    #: HTML opcional (mismo run); nunca es autoridad estructural.
    html: str = ""
    output_html_bytes: int = 0
    elapsed_seconds: float = 0.0
    java: str = ""
    command: tuple[str, ...] = ()
    output_path: str | None = None
    output_markdown_path: str | None = None
    output_html_path: str | None = None

    @property
    def has_markdown(self) -> bool:
        return bool(self.markdown.strip())

    @classmethod
    def from_payload(
        cls, payload: dict[str, Any] | "OpenDataLoaderConversion"
    ) -> "OpenDataLoaderConversion":
        if isinstance(payload, OpenDataLoaderConversion):
            return payload
        return cls(data=payload)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "json_bytes": int(self.output_json_bytes),
            "markdown_bytes": int(self.output_markdown_bytes),
            "html_bytes": int(self.output_html_bytes),
            "elapsed_seconds": round(float(self.elapsed_seconds or 0.0), 3),
            "java": self.java,
        }


#: Firma del runner inyectable en tests/benchmarks.
ConversionRunner = Callable[[bytes, OpenDataLoaderOptions], "OpenDataLoaderConversion | dict[str, Any]"]


def odl_library_version() -> str:
    """Versión del paquete oficial instalado (la registra el parser)."""
    try:
        return version(_LIB_NAME)
    except PackageNotFoundError:
        return "unknown"


def _java_candidates(options: OpenDataLoaderOptions) -> list[str]:
    candidates: list[str] = []
    if options.java:
        candidates.append(options.java)
    if options.java_home:
        candidates.append(str(Path(options.java_home) / "bin" / "java"))
    which = shutil.which("java")
    if which:
        candidates.append(which)
    return candidates


def _major_from_version_output(output: str) -> int | None:
    match = _VERSION_RE.search(output or "")
    if match is None:
        return None
    first = int(match.group(1))
    if first == 1 and match.group(2):
        return int(match.group(2))
    return first


def java_major_version(java: str) -> int | None:
    """Mayor de Java (8, 11, 17, ...) o None si no se pudo leer."""
    try:
        result = subprocess.run(  # noqa: S603 — binario resuelto explícitamente
            [java, "-version"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return _major_from_version_output(f"{result.stderr}\n{result.stdout}")


def resolve_java(options: OpenDataLoaderOptions) -> tuple[str, int] | None:
    """Primer java 11+ válido entre los candidatos; None si no hay."""
    seen: set[str] = set()
    for candidate in _java_candidates(options):
        key = str(candidate).lower()
        if key in seen:
            continue
        seen.add(key)
        major = java_major_version(candidate)
        if major is not None and major >= _MIN_JAVA_MAJOR:
            return candidate, major
    return None


def availability(options: OpenDataLoaderOptions | None = None) -> dict[str, Any]:
    """Diagnóstico sin lanzar excepciones: ¿puede correr OpenDataLoader?"""
    opts = options or OpenDataLoaderOptions()
    lib_version = odl_library_version()
    if lib_version == "unknown":
        return {
            "ready": False,
            "library": lib_version,
            "java": None,
            "java_major": None,
            "reason": "opendataloader-pdf no está instalado",
        }
    resolved = resolve_java(opts)
    if resolved is None:
        return {
            "ready": False,
            "library": lib_version,
            "java": None,
            "java_major": None,
            "reason": "no se encontró java 11+ (ODL_JAVA / ODL_JAVA_HOME / PATH)",
        }
    java, major = resolved
    return {
        "ready": True,
        "library": lib_version,
        "java": java,
        "java_major": major,
        "reason": "",
    }


def _build_command(
    *,
    java: str,
    jar: str,
    pdf_path: Path,
    output_dir: Path,
    options: OpenDataLoaderOptions,
    use_struct_tree: bool,
) -> list[str]:
    formats = options.resolved_formats()
    command = [
        java,
        "-Djava.awt.headless=true",
        "-jar",
        jar,
        "--format",
        ",".join(formats),
        "--quiet",
        "--image-output",
        "off",
        "--output-dir",
        str(output_dir),
        "--table-method",
        options.table_method,
        "--reading-order",
        options.reading_order,
        "--threads",
        str(max(int(options.threads), 1)),
    ]
    # Una sola JVM produce JSON + Markdown: el Markdown nace de la misma
    # conversión (no es un segundo parseo ni una segunda fuente).
    if "markdown" in formats:
        if options.markdown_page_separator:
            command.extend(
                ["--markdown-page-separator", options.markdown_page_separator]
            )
        if options.markdown_with_html:
            command.append("--markdown-with-html")
    if use_struct_tree:
        command.append("--use-struct-tree")
    if options.include_header_footer:
        command.append("--include-header-footer")
    if options.mode == "hybrid":
        command.extend(["--hybrid", options.hybrid_backend])
        if options.hybrid_url:
            command.extend(["--hybrid-url", options.hybrid_url])
        if options.hybrid_mode:
            command.extend(["--hybrid-mode", options.hybrid_mode])
    command.extend(str(arg) for arg in options.extra_args)
    command.append(str(pdf_path))
    return command


def _pick_artifact(output_dir: Path, pdf_path: Path, suffix: str) -> Path | None:
    candidate = output_dir / f"{pdf_path.stem}{suffix}"
    if candidate.is_file():
        return candidate
    found = sorted(output_dir.glob(f"*{suffix}"))
    return found[0] if found else None


def _read_output_artifacts(
    output_dir: Path, pdf_path: Path
) -> tuple[dict[str, Any], int, str, str, int, str | None, str, int, str | None]:
    """Lee TODOS los artefactos de UNA conversión (JSON canónico + extras).

    Devuelve:
      payload, json_bytes, json_path, markdown, markdown_bytes, markdown_path,
      html, html_bytes, html_path
    El JSON es obligatorio (contrato estructural); markdown/html son opcionales
    y su ausencia no invalida la conversión (quality gate decide después).
    """
    json_path = _pick_artifact(output_dir, pdf_path, ".json")
    if json_path is None:
        raise StructuredParserError(
            f"OpenDataLoader no produjo JSON para {pdf_path.name} "
            f"(output_dir={output_dir})"
        )
    raw = json_path.read_bytes()
    try:
        payload = json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError as exc:
        raise StructuredParserError(
            f"OpenDataLoader produjo JSON inválido para {pdf_path.name}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise StructuredParserError(
            f"OpenDataLoader devolvió un JSON no-objeto para {pdf_path.name}"
        )

    markdown = ""
    markdown_bytes = 0
    markdown_path: str | None = None
    md_file = _pick_artifact(output_dir, pdf_path, ".md")
    if md_file is not None:
        md_raw = md_file.read_bytes()
        markdown = md_raw.decode("utf-8", errors="replace")
        markdown_bytes = len(md_raw)
        markdown_path = str(md_file)

    html = ""
    html_bytes = 0
    html_path: str | None = None
    html_file = _pick_artifact(output_dir, pdf_path, ".html")
    if html_file is not None:
        html_raw = html_file.read_bytes()
        html = html_raw.decode("utf-8", errors="replace")
        html_bytes = len(html_raw)
        html_path = str(html_file)

    return (
        payload,
        len(raw),
        str(json_path),
        markdown,
        markdown_bytes,
        markdown_path,
        html,
        html_bytes,
        html_path,
    )


def convert_pdf(
    data: bytes,
    *,
    options: OpenDataLoaderOptions,
    use_struct_tree: bool = False,
    workdir: str | Path | None = None,
) -> OpenDataLoaderConversion:
    """UNA ejecución ODL -> JSON canónico + representaciones pedidas.

    `options.formats` decide los artefactos (p.ej. ("json", "markdown")): el
    CLI los produce en la MISMA JVM. El JSON sigue siendo la representación
    estructural canónica; markdown/html son proyecciones.

    Todo el I/O ocurre en un directorio aislado por documento; con `workdir`
    explícito no se borra (diagnóstico/benchmark).
    """
    resolved = resolve_java(options)
    if resolved is None:
        raise StructuredParserError(
            "OpenDataLoader requiere Java 11+ y no se encontró ninguno "
            "(configurá ODL_JAVA, ODL_JAVA_HOME o instalá un JDK)"
        )
    java, _major = resolved

    try:
        jar_ref = resources.files(_JAR_PACKAGE).joinpath("jar", _JAR_NAME)
    except (ModuleNotFoundError, FileNotFoundError) as exc:
        raise StructuredParserError(
            "opendataloader-pdf no está instalado (pip install opendataloader-pdf)"
        ) from exc

    temp_dir = None
    if workdir is None:
        temp_dir = Path(tempfile.mkdtemp(prefix="zent_odl_"))
        root = temp_dir
    else:
        root = Path(workdir)
        root.mkdir(parents=True, exist_ok=True)
    pdf_path = root / "input.pdf"
    pdf_path.write_bytes(data)
    output_dir = root / "output"
    output_dir.mkdir(exist_ok=True)

    keep = workdir is not None or temp_dir is None
    try:
        with resources.as_file(jar_ref) as jar_path:
            command = _build_command(
                java=java,
                jar=str(jar_path),
                pdf_path=pdf_path,
                output_dir=output_dir,
                options=options,
                use_struct_tree=use_struct_tree,
            )
            started = time.perf_counter()
            try:
                result = subprocess.run(  # noqa: S603 — java resuelto y args fijos
                    command,
                    capture_output=True,
                    text=True,
                    timeout=max(int(options.timeout_seconds), 5),
                    encoding="utf-8",
                    errors="replace",
                )
            except subprocess.TimeoutExpired as exc:
                raise StructuredParserError(
                    f"OpenDataLoader excedió {options.timeout_seconds}s "
                    f"(input={pdf_path.name})"
                ) from exc
            except FileNotFoundError as exc:
                raise StructuredParserError(
                    f"No se pudo ejecutar java '{java}': {exc}"
                ) from exc
            elapsed = time.perf_counter() - started
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "").strip()[-800:]
                raise StructuredParserError(
                    f"OpenDataLoader falló (rc={result.returncode}): {detail}"
                )
            (
                payload,
                json_bytes,
                output_path,
                markdown,
                markdown_bytes,
                markdown_path,
                html,
                html_bytes,
                html_path,
            ) = _read_output_artifacts(output_dir, pdf_path)
        return OpenDataLoaderConversion(
            data=payload,
            output_json_bytes=json_bytes,
            markdown=markdown,
            output_markdown_bytes=markdown_bytes,
            html=html,
            output_html_bytes=html_bytes,
            elapsed_seconds=elapsed,
            java=java,
            command=tuple(command),
            output_path=output_path if keep else None,
            output_markdown_path=markdown_path if keep else None,
            output_html_path=html_path if keep else None,
        )
    finally:
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)


def convert_pdf_to_json(
    data: bytes,
    *,
    options: OpenDataLoaderOptions,
    use_struct_tree: bool = False,
    workdir: str | Path | None = None,
) -> OpenDataLoaderConversion:
    """Compat histórica: misma conversión forzada a JSON-only."""
    from dataclasses import replace

    json_only = replace(options, formats=("json",))
    return convert_pdf(
        data,
        options=json_only,
        use_struct_tree=use_struct_tree,
        workdir=workdir,
    )


__all__ = [
    "ConversionRunner",
    "DEFAULT_MARKDOWN_PAGE_SEPARATOR",
    "OpenDataLoaderConversion",
    "OpenDataLoaderOptions",
    "SUPPORTED_FORMATS",
    "availability",
    "convert_pdf",
    "convert_pdf_to_json",
    "java_major_version",
    "odl_library_version",
    "resolve_java",
]
