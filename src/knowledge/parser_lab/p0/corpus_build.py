# =============================================================================
# P0 — Corpus builder: PDFs sintéticos deterministas (sin binarios en git)
# =============================================================================
# Genera PDFs controlados para el benchmark de conocimiento. Incluye:
#   - multi-página, tablas con bordes, listas, fixed-width, multi-columna
#   - tagged PDF mínimo (StructTreeRoot + ParentTree + MCID)
# El contenido vive en corpus.py; acá solo está el motor de dibujo.
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass, field


def _escape(text: str) -> str:
    """Escapa literales PDF y convierte no-ASCII a octal WinAnsi.

    PDFBox no tolera bytes latin-1 crudos en fuentes estándar; con
    /Encoding /WinAnsiEncoding + octal el texto acentuado sobrevive en ambos
    parsers (pdfminer y PDFBox).
    """
    safe = text.encode("latin-1", errors="replace").decode("latin-1")
    parts: list[str] = []
    for char in safe:
        if char in "\\()":
            parts.append("\\" + char)
        elif ord(char) > 127:
            parts.append(f"\\{ord(char):03o}")
        else:
            parts.append(char)
    return "".join(parts)


@dataclass
class PdfCanvas:
    """Dibujo simple sobre N páginas; fuentes F1 (regular) y F2 (bold)."""

    width: float = 612.0
    height: float = 792.0
    pages: list[list[str]] = field(default_factory=list)
    _mcid: int = 0

    def __post_init__(self) -> None:
        if not self.pages:
            self.pages.append([])

    # -- estructura ---------------------------------------------------------

    @property
    def ops(self) -> list[str]:
        return self.pages[-1]

    def new_page(self) -> None:
        self.pages.append([])

    # -- primitivas ---------------------------------------------------------

    def text(
        self,
        x: float,
        y: float,
        content: str,
        *,
        size: float = 11.0,
        bold: bool = False,
        marked: bool = False,
        mcid: int | None = None,
    ) -> None:
        font = "F2" if bold else "F1"
        show = f"BT /{font} {size} Tf {x} {y} Td ({_escape(content)}) Tj ET"
        if marked:
            index = self._mcid if mcid is None else mcid
            self._mcid += 1
            self.ops.append(f"/P <</MCID {index}>> BDC")
            self.ops.append(show)
            self.ops.append("EMC")
        else:
            self.ops.append(show)

    def line(self, x0: float, y0: float, x1: float, y1: float, width: float = 1.0) -> None:
        self.ops.append(f"{width} w {x0} {y0} m {x1} {y1} l S")

    def table(
        self,
        x: float,
        y_top: float,
        column_widths: list[float],
        rows: list[list[str]],
        *,
        row_height: float = 18.0,
        size: float = 9.5,
        marked: bool = False,
    ) -> float:
        """Tabla con bordes; devuelve el y inferior."""
        total_width = sum(column_widths)
        height = row_height * len(rows)
        y_bottom = y_top - height
        for index in range(len(rows) + 1):
            y = y_top - index * row_height
            self.line(x, y, x + total_width, y, 1.0)
        x_cursor = x
        for column_width in [*column_widths, 0.0]:
            self.line(x_cursor, y_top, x_cursor, y_bottom, 1.0)
            x_cursor += column_width
        for row_index, row in enumerate(rows):
            y = y_top - row_index * row_height - row_height + 5.0
            x_cursor = x + 4.0
            for cell_index, cell in enumerate(row):
                self.text(
                    x_cursor,
                    y,
                    cell,
                    size=size,
                    bold=row_index == 0,
                    marked=marked,
                )
                x_cursor += column_widths[cell_index]
        return y_bottom

    # -- build --------------------------------------------------------------

    def build(self) -> bytes:
        objects: list[bytes] = []
        page_count = len(self.pages)
        first_page_obj = 3
        content_start = first_page_obj + page_count
        font_regular = content_start + page_count
        font_bold = font_regular + 1
        kids = " ".join(f"{first_page_obj + i} 0 R" for i in range(page_count))
        objects.append(b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj")
        objects.append(
            f"2 0 obj << /Type /Pages /Kids [{kids}] /Count {page_count} >> endobj".encode()
        )
        for index in range(page_count):
            objects.append(
                (
                    f"{first_page_obj + index} 0 obj << /Type /Page /Parent 2 0 R "
                    f"/MediaBox [0 0 {int(self.width)} {int(self.height)}] "
                    f"/Contents {content_start + index} 0 R "
                    f"/Resources << /Font << /F1 {font_regular} 0 R /F2 {font_bold} 0 R >> >> >> endobj"
                ).encode()
            )
        for index, ops in enumerate(self.pages):
            stream = "\n".join(ops).encode("latin-1", errors="replace")
            objects.append(
                b"%d 0 obj << /Length %d >> stream\n" % (content_start + index, len(stream))
                + stream
                + b"\nendstream endobj"
            )
        objects.append(
            f"{font_regular} 0 obj << /Type /Font /Subtype /Type1 "
            f"/BaseFont /Helvetica /Encoding /WinAnsiEncoding >> endobj".encode()
        )
        objects.append(
            f"{font_bold} 0 obj << /Type /Font /Subtype /Type1 "
            f"/BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >> endobj".encode()
        )
        return _assemble(objects)


def _assemble(objects: list[bytes], trailer_extra: bytes = b"") -> bytes:
    head = b"%PDF-1.4\n"
    body = b""
    offsets: list[int] = []
    position = len(head)
    for obj in objects:
        offsets.append(position)
        body += obj + b"\n"
        position += len(obj) + 1
    xref_position = position
    xref = (
        b"xref\n0 " + str(len(offsets) + 1).encode() + b"\n0000000000 65535 f \n"
        + b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    )
    trailer = (
        b"trailer << /Size " + str(len(offsets) + 1).encode()
        + b" /Root 1 0 R" + trailer_extra + b" >>\nstartxref\n"
        + str(xref_position).encode() + b"\n%%EOF\n"
    )
    return head + body + xref + trailer


def tagged_pdf(
    *,
    title: str,
    elements: list[tuple[str, str]],
    width: float = 612.0,
    height: float = 792.0,
) -> bytes:
    """PDF de una página con structure tree mínimo.

    elements: lista de (tag, text) con tag en {H1,H2,P}. Genera StructTreeRoot,
    ParentTree y MCIDs por elemento para que OpenDataLoader pueda usar
    --use-struct-tree.
    """
    canvas = PdfCanvas(width=width, height=height)
    for index, (_tag, text) in enumerate(elements):
        canvas.text(72, 720 - index * 30, text, size=14 if _tag.startswith("H") else 11, marked=True, mcid=index)
    base = canvas.build()
    # Reescribe con objetos de estructura: reconstruimos el PDF completo.
    objects: list[bytes] = []
    objects.append(
        b"1 0 obj << /Type /Catalog /Pages 2 0 R /StructTreeRoot 6 0 R "
        b"/MarkInfo << /Marked true >> >> endobj"
    )
    objects.append(b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj")
    objects.append(
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 7 0 R /F2 8 0 R >> >> /StructParents 0 >> endobj"
    )
    stream = "\n".join(canvas.pages[0]).encode("latin-1", errors="replace")
    objects.append(b"4 0 obj << /Length %d >> stream\n" % len(stream) + stream + b"\nendstream endobj")
    kids = " ".join(f"{9 + index} 0 R" for index in range(len(elements)))
    objects.append(
        f"6 0 obj << /Type /StructTreeRoot /K [{kids}] /ParentTree 5 0 R >> endobj".encode()
    )
    parent_refs = " ".join(f"{9 + index} 0 R" for index in range(len(elements)))
    objects.append(
        f"5 0 obj << /Nums [0 [{parent_refs}]] >> endobj".encode()
    )
    objects.append(
        b"7 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        b"/Encoding /WinAnsiEncoding >> endobj"
    )
    objects.append(
        b"8 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
        b"/Encoding /WinAnsiEncoding >> endobj"
    )
    for index, (tag, _text) in enumerate(elements):
        objects.append(
            (
                f"{9 + index} 0 obj << /Type /StructElem /S /{tag} /P 6 0 R "
                f"/Pg 3 0 R /K {index} >> endobj"
            ).encode()
        )
    # /Title en metadata del documento no está en este builder; el title se usa
    # solo como nombre lógico del corpus.
    _ = (base, title)
    return _assemble(objects)


__all__ = ["PdfCanvas", "tagged_pdf"]
