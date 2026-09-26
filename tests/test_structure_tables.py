# =============================================================================
# Knowledge V2 — tablas de PDF: extracción a bloques y llegada al chunk
# =============================================================================
# Caso real (Cat31_dapp_C.pdf §4.6.2 Fee Application (byte 105)): una tabla con
# los valores del campo. Antes, las líneas dentro del bbox de la tabla se
# salteaban y la tabla quedaba sólo en `document.tables`, así que su contenido
# nunca entraba a los chunks.
from __future__ import annotations

import zlib
from uuid import uuid4

from src.core.domain.knowledge_v2 import (
    ChunkType,
    StructuredBlockKind,
    StructuredDocument,
)
from src.knowledge.structure import PdfParser, chunk_structured_document
from src.knowledge.structure.chunker import ChunkingConfig

_FILA_1 = "From among all changed fare components, apply the highest change fee"
_FILA_5 = "From among all fare components within changed pricing units, apply the highest change fee"


def _escape_text(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _pdf_con_tabla() -> bytes:
    """PDF de una página: heading 4.6.2, párrafo y una grilla con reglas."""
    ops: list[str] = []
    ops.append("BT /F1 12 Tf 60 730 Td (4.6.2 Fee Application \\(byte 105\\)) Tj ET")
    ops.append("BT /F1 11 Tf 60 706 Td (The valid values of this field are:) Tj ET")
    # grilla 3 filas x 2 columnas
    ys = [660, 640, 620, 600]
    xs = [60, 220, 560]
    for y in ys:
        ops.append(f"60 {y} m 560 {y} l S")
    for x in xs:
        ops.append(f"{x} 600 m {x} 660 l S")
    celdas = [
        ("Value", 70, 646),
        ("Definition", 230, 646),
        ("1", 70, 626),
        (_FILA_1, 230, 626),
        ("5", 70, 606),
        (_FILA_5, 230, 606),
    ]
    for texto, x, y in celdas:
        ops.append(f"BT /F1 10 Tf {x} {y} Td ({_escape_text(texto)}) Tj ET")
    ops.append("BT /F1 11 Tf 60 570 Td (More text after the table.) Tj ET")

    stream = zlib.compress("\n".join(ops).encode("latin-1"))
    objs = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj",
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj",
        (
            b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj"
        ),
        b"4 0 obj << /Length %d /Filter /FlateDecode >> stream\n" % len(stream)
        + stream
        + b"\nendstream endobj",
        b"5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj",
    ]
    head = b"%PDF-1.4\n"
    body = b""
    offsets: list[int] = []
    pos = len(head)
    for obj in objs:
        offsets.append(pos)
        body += obj + b"\n"
        pos += len(obj) + 1
    xref_pos = pos
    xref = (
        b"xref\n0 6\n0000000000 65535 f \n"
        + b"".join(f"{off:010d} 00000 n \n".encode() for off in offsets)
    )
    trailer = (
        b"trailer << /Size 6 /Root 1 0 R >>\nstartxref\n"
        + str(xref_pos).encode()
        + b"\n%%EOF\n"
    )
    return head + body + xref + trailer


def _parse() -> StructuredDocument:
    return PdfParser().parse(
        _pdf_con_tabla(),
        organization_id=uuid4(),
        external_id="cat31.pdf",
        source_name="cat31.pdf",
    )


def test_la_tabla_extraida_tambien_es_un_bloque() -> None:
    document = _parse()

    assert document.tables, "pdfplumber debería detectar la grilla"
    bloques_tabla = [b for b in document.blocks if b.kind is StructuredBlockKind.TABLE]
    assert bloques_tabla, "la tabla debe existir como bloque para poder chunquearse"

    texto = bloques_tabla[0].text
    assert "Definition" in texto
    assert "highest change fee" in texto
    assert "\n" in texto, "las filas van una por línea, no en un párrafo corrido"


def test_la_tabla_llega_al_chunk_con_su_seccion() -> None:
    document = _parse()
    chunks = chunk_structured_document(document, config=ChunkingConfig())

    con_tabla = [c for c in chunks if "highest change fee" in c.content]
    assert con_tabla, "el contenido de la tabla debe estar en algún chunk"

    titulos = [c for c in con_tabla if "byte 105" in c.content]
    assert titulos, "el chunk de la tabla debe llevar su ruta (byte 105)"

    padre = [c for c in chunks if len(c.content) > 200 and "highest change fee" in c.content]
    assert padre, "el chunk padre también conserva la tabla completa"


def test_ninguna_fila_queda_cortada_ni_duplicada() -> None:
    document = _parse()
    config = ChunkingConfig()
    chunks = chunk_structured_document(document, config=config)

    hijos = [c for c in chunks if c.chunk_type is ChunkType.PARENT_CHILD]
    piezas = [c for c in hijos if _FILA_5 in c.content]
    assert piezas, "la fila del valor 5 debe llegar a un chunk hijo"
    for pieza in piezas:
        assert len(pieza.content) <= config.child_max_chars + 1
        assert "Definition" in pieza.content, "cada pieza repite el encabezado"

    textos_hijos = [c.content for c in hijos]
    assert len(textos_hijos) == len(set(textos_hijos)), "sin hijos repetidos"
    assert len(piezas) == 1, "la fila no se duplica entre piezas"

    padres = [c for c in chunks if c.chunk_type is ChunkType.DOCUMENT_STRUCTURE]
    assert any("highest change fee" in c.content for c in padres)


# ---------------------------------------------------------------------------
# Regresión «byte 105»: el parser parte la tabla en encabezados sueltos y el
# chunker los indexaba como chunks propios de ~50 chars. El pin de entidades los
# elegía por título y la sección completa (el padre) quedaba afuera.
# ---------------------------------------------------------------------------


def test_las_piezas_diminutas_de_tabla_no_entran_sueltas() -> None:
    from src.knowledge.structure.chunker import _table_pieces

    tabla = (
        "Validating Carrier\nChanged Fare Component(s)\nApplication\n"
        "Resulting Change Fee"
    )
    piezas = _table_pieces("4.6.2 Fee Application (byte 105)", tabla, ChunkingConfig())

    assert len(piezas) <= 1, "encabezados sueltos no son chunks independientes"
    if piezas:
        assert "Validating Carrier" in piezas[0]


def test_encabezado_huerfano_sin_datos_se_descarta() -> None:
    from src.knowledge.structure.chunker import _table_pieces

    piezas = _table_pieces(
        "4.6.2 Fee Application (byte 105)", "Validating Carrier", ChunkingConfig()
    )
    assert piezas == []


def test_una_tabla_con_datos_sigue_indexada() -> None:
    from src.knowledge.structure.chunker import _table_pieces

    tabla = "Value | Definition\n1 | highest fee\n2 | highest fee of all"
    piezas = _table_pieces("4.6.2 Fee Application (byte 105)", tabla, ChunkingConfig())

    assert piezas, "una tabla con filas no se descarta"
    assert "1 | highest fee" in piezas[0]
    assert "byte 105" in piezas[0]


def test_el_overlap_no_arranca_a_mitad_de_palabra() -> None:
    from src.knowledge.structure.chunker import _align_word_start, _split_text

    assert _align_word_start("hola ghest Fee Application", 5) == 5
    assert _align_word_start("hola ghest Fee Application", 7) == len("hola ghest") + 1
    assert _align_word_start("hola", 0) == 0
    assert _align_word_start("hola", 4) == 4

    relleno_a = " ".join(f"alfa{indice:03d} beta{indice:03d}" for indice in range(40))
    relleno_b = " ".join(f"delta{indice:03d} epsilon{indice:03d}" for indice in range(40))
    texto = f"{relleno_a} ghest Fee Application byte 105 {relleno_b}"
    piezas = _split_text(texto, ChunkingConfig(child_max_chars=600, child_overlap=50))
    assert len(piezas) > 1

    offset = 0
    for pieza in piezas:
        index = texto.find(pieza, max(0, offset - 60))
        assert index >= 0, "la pieza debe existir tal cual en el texto"
        if index > 0:
            assert not (
                texto[index - 1].isalnum() and texto[index].isalnum()
            ), f"la pieza arranca a mitad de palabra: {pieza[:40]!r}"
        offset = index + len(pieza)
