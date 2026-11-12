import os
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from pypdf import PdfReader

from buscador.engine import Index
from buscador.extract import Extraction
from buscador.unicode_text import clean_text, preview_document


BROKEN_CMAP = b"""/CIDInit /ProcSet findresource begin
12 dict begin
begincmap
/CMapType 2 def
1 begincodespacerange
<00> <FF>
endcodespacerange
1 beginbfchar
<58> <D83D>
endbfchar
endcmap
end
end
"""


def test_real_pdf_with_unpaired_surrogate_does_not_abort_index(tmp_path, pdf_factory):
    root = tmp_path / "Documentos"
    root.mkdir()
    path = pdf_factory(root / "Presupuesto.pdf", text="A" * 964 + "X presupuesto modular", unicode_map=BROKEN_CMAP)
    # This font mapping yields the same isolated high surrogate reported by the user.
    raw = PdfReader(path).pages[0].extract_text()
    assert raw[964] == "\ud83d"
    (root / "Otro documento.txt").write_text("Archivo posterior con acentos: habitación.", encoding="utf-8")
    index = Index(tmp_path / "index.db")
    report = index.scan(root)
    assert report.errors == 0 and report.partial == 1
    assert index.count(root) == 2
    matches = index.search(root, "presupuesto modular", mode="content", fuzzy=False).results
    assert matches
    assert "\ufffd presupuesto modular" in index.content(str(root), matches[0].path)
    assert index.search(root, "habitación", mode="content", fuzzy=False).results
    assert index.scan(root).unchanged == 2


@pytest.mark.parametrize(("text", "expected"), [
    ("Habitación 🏠 中文", "Habitación 🏠 中文"),
    ("antes\ud83ddespués", "antes\ufffddespués"),
    ("antes\udc00después", "antes\ufffddespués"),
    ("\ud83d\ude00", "😀"),
    ("\ud83d\ud83d\ude00\udc00", "�😀�"),
    ("\ud83d\n\ude00", "�\n�"),
])
def test_repair_preserves_valid_unicode_and_combines_pairs(text, expected):
    assert clean_text(text) == expected
    assert clean_text(expected) == expected
    result = Extraction(text, "contenido", "Nota \ud83d")
    assert result.text == expected
    result.text.encode("utf-8")
    result.note.encode("utf-8")


def test_valid_surrogate_pair_is_not_reported_as_lost_text():
    result = Extraction("Emoji \ud83d\ude00 válido", "contenido", "Texto extraído.")
    assert result.text == "Emoji 😀 válido"
    assert result.status == "contenido"
    assert result.note == "Texto extraído."


def test_unicode_filenames_and_text_round_trip(tmp_path):
    root = tmp_path / "Documentos 🏠"
    root.mkdir()
    path = root / "Contrato 📝 Córdoba.txt"
    path.write_text("Habitación 🏠 y construcción. 中文", encoding="utf-8")
    index = Index(tmp_path / "index.db")
    assert index.scan(root).errors == 0
    found = index.search(root, "cordoba", mode="name", fuzzy=False).results
    assert len(found) == 1 and Path(found[0].path) == path
    assert index.content(str(root), found[0].path) == path.read_text(encoding="utf-8")


def test_unrepresentable_filename_does_not_alias_or_prune(tmp_path, monkeypatch):
    root = tmp_path / "docs"
    root.mkdir()
    legitimate = root / "nombre-�.txt"
    legitimate.write_text("Contenido válido", encoding="utf-8")
    old = root / "anterior.txt"
    old.write_text("Conservar registro si el recorrido fue incompleto", encoding="utf-8")
    index = Index(tmp_path / "index.db")
    index.scan(root)
    old.unlink()
    original = os.scandir
    @contextmanager
    def entries(folder):
        with original(folder) as stream:
            real = list(stream)
        if Path(folder) == root:
            yield iter([SimpleNamespace(path=str(root / "nombre-\ud83d.txt")), *real])
        else:
            yield iter(real)
    monkeypatch.setattr("buscador.engine.os.scandir", entries)
    report = index.scan(root)
    assert report.errors == 1 and report.removed == 0
    assert "\\ud83d" in report.warnings[0]
    for warning in report.warnings:
        warning.encode("utf-8")
    assert index.count(root) == 2
    found = index.search(root, "nombre", mode="name", fuzzy=False).results
    assert len(found) == 1 and Path(found[0].path) == legitimate
    assert index.content(str(root), found[0].path) == "Contenido válido"
    assert index.search(root, "anterior", mode="name").results
    assert "\\ud83d" in (tmp_path / "actividad.log").read_text(encoding="utf-8")


def test_preview_text_drops_controls_and_breaks_long_lines():
    raw = "figuras\u202e" + ("patron" * 100) + "\ud800 fin"
    shown = preview_document(raw, width=20)
    assert "\u202e" not in shown and "\ud800" not in shown
    assert shown.startswith("figuras")
    assert max(len(line) for line in shown.splitlines()) <= 20
    assert "fin" in shown


@pytest.mark.parametrize("operation", ["scan", "count", "clear", "search"])
def test_invalid_selected_root_has_a_useful_error(tmp_path, operation):
    index = Index(tmp_path / "index.db")
    root = str(tmp_path / "carpeta-\ud83d")
    args = (root, "factura") if operation == "search" else (root,)
    with pytest.raises(ValueError, match="ruta contiene caracteres Unicode inválidos"):
        getattr(index, operation)(*args)
