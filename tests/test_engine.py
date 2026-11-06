import os
import threading
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from buscador.engine import Index
from buscador.extract import Extraction


@pytest.fixture
def library(tmp_path):
    root = tmp_path / "Mis archivos"
    root.mkdir()
    (root / "Vacaciones Córdoba").mkdir()
    (root / "Factura eléctrica.txt").write_text("Cliente Álvarez. Consumo mensual de electricidad. Vencimiento noviembre.", encoding="utf-8")
    (root / "notas.md").write_text("Presupuesto para construcción modular. Cocina y dormitorio.", encoding="utf-8")
    Image.new("RGB", (30, 20), "white").save(root / "playa verano.png")
    (root / "programa.bin").write_bytes(b"\x00\x01\x02")
    index = Index(tmp_path / "cache" / "index.sqlite3")
    return root, index


def names(response):
    return {result.name for result in response.results}


def test_index_names_content_fuzzy_accents_and_filters(library):
    root, index = library
    report = index.scan(root)
    assert report.seen == 5 and report.errors == 0
    assert index.count(root) == 5
    assert names(index.search(root, "FACTURA electrica", mode="name", fuzzy=False)) == {"Factura eléctrica.txt"}
    assert names(index.search(root, "factrua", mode="name")) == {"Factura eléctrica.txt"}
    assert not index.search(root, "factrua", fuzzy=False).results
    assert names(index.search(root, "construcion", mode="content")) == {"notas.md"}
    assert names(index.search(root, "noviembre alvarez", mode="content", fuzzy=False)) == {"Factura eléctrica.txt"}
    assert not index.search(root, "noviembre", mode="name").results
    assert names(index.search(root, "cordoba", kind="Carpeta")) == {"Vacaciones Córdoba"}
    assert names(index.search(root, "playa", kind="Imagen", extensions="*.PNG")) == {"playa verano.png"}
    assert not index.search(root, "playa", kind="Documento").results
    assert not index.search(root, "factura", extensions="pdf,docx").results
    assert names(index.search(root, "factura", extensions=".txt;docx")) == {"Factura eléctrica.txt"}


def test_incremental_update_delete_and_clear(library):
    root, index = library
    index.scan(root)
    report = index.scan(root)
    assert report.updated == 0 and report.unchanged == 5
    (root / "notas.md").write_text("Reemplazo completo: biblioteca infantil.", encoding="utf-8")
    (root / "Factura eléctrica.txt").unlink()
    report = index.scan(root)
    assert report.removed == 1 and report.updated == 1
    assert not index.search(root, "electricidad", fuzzy=False).results
    assert not index.search(root, "modular", fuzzy=False).results
    assert names(index.search(root, "biblioteca", fuzzy=False)) == {"notas.md"}
    index.clear(str(root))
    assert index.count(root) == 0
    assert (root / "notas.md").is_file()
    assert not index.search(root, "biblioteca").results


def test_cancel_does_not_prune_or_save_partial_text(library, monkeypatch):
    root, index = library
    index.scan(root)
    stop = threading.Event()
    def interrupted(*args, **kwargs):
        stop.set()
        return Extraction("texto incompleto", "contenido", "")
    monkeypatch.setattr("buscador.engine.SafeExtractor.read", interrupted)
    report = index.scan(root, force=True, cancelled=stop)
    assert report.cancelled
    assert index.count(root) == 5
    assert not index.search(root, "incompleto", fuzzy=False).results
    assert index.search(root, "electricidad", fuzzy=False).results


def test_inaccessible_directory_does_not_prune(library, monkeypatch):
    root, index = library
    subdir = root / "Vacaciones Córdoba"
    (subdir / "reserva.txt").write_text("Hotel confirmado")
    index.scan(root)
    original = os.scandir
    def scandir(path):
        if Path(path) == subdir:
            raise PermissionError("denegado")
        return original(path)
    monkeypatch.setattr("buscador.engine.os.scandir", scandir)
    report = index.scan(root)
    assert report.errors == 1
    assert index.search(root, "confirmado", fuzzy=False).results


def test_scopes_are_separate(tmp_path):
    first = tmp_path / "uno_%"
    second = tmp_path / "dos"
    first.mkdir()
    second.mkdir()
    (first / "privado.txt").write_text("contenido compartido")
    (second / "publico.txt").write_text("contenido compartido")
    index = Index(tmp_path / "index.db")
    index.scan(first)
    index.scan(second)
    assert names(index.search(first, "compartido")) == {"privado.txt"}
    assert names(index.search(second, "compartido")) == {"publico.txt"}
    index.clear(str(first))
    assert index.count(second) == 1


def test_own_database_and_links_are_skipped(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    (root / "normal.txt").write_text("hola")
    index = Index(root / "cache.sqlite3")
    try:
        (root / "bucle").symlink_to(root, target_is_directory=True)
    except OSError:
        pass  # Windows can require privileges to create a symlink.
    index.scan(root)
    assert index.count(root) == 1


def test_document_content_search(tmp_path, pdf_factory):
    root = tmp_path / "docs"
    root.mkdir()
    pdf_factory(root / "cotizacion.pdf")
    with zipfile.ZipFile(root / "contrato.docx", "w") as archive:
        archive.writestr("word/document.xml", '<document><p><t>Arrendamiento residencial</t></p></document>')
    index = Index(tmp_path / "index.db")
    report = index.scan(root)
    assert report.errors == 0
    assert names(index.search(root, "casa modular", mode="content")) == {"cotizacion.pdf"}
    assert names(index.search(root, "arrendaminto", mode="content")) == {"contrato.docx"}


def test_bad_files_do_not_stop_scan(library):
    root, index = library
    (root / "roto.pdf").write_bytes(b"no es un PDF")
    report = index.scan(root)
    assert report.errors == 1
    assert names(index.search(root, "roto")) == {"roto.pdf"}
    assert index.search(root, "consumo").results


@pytest.mark.parametrize("query", ["", "---", '" OR * : NEAR ( )', "\x00", "a' UNION SELECT", "casa AND presupuesto"])
def test_query_is_not_sql_or_fts_code(library, query):
    root, index = library
    index.scan(root)
    index.search(root, query)
    assert index.count(root) == 5


def test_result_limit_and_cancel(library):
    root, index = library
    for number in range(5):
        (root / f"reporte {number}.txt").write_text("balance")
    index.scan(root)
    result = index.search(root, "reporte", limit=2)
    assert len(result.results) == 2 and result.truncated
    event = threading.Event()
    event.set()
    assert not index.search(root, "reporte", cancelled=event).results


def test_missing_root_is_a_clear_error(tmp_path):
    index = Index(tmp_path / "index.db")
    with pytest.raises(ValueError, match="no existe"):
        index.scan(tmp_path / "missing")


def test_ocr_settings_only_invalidate_files_that_need_ocr(library, monkeypatch):
    root, index = library
    index.scan(root)
    monkeypatch.setattr("buscador.engine.tesseract_path", lambda: "/fake/tesseract")
    monkeypatch.setattr("buscador.engine.ocr_languages", lambda _: "spa")
    monkeypatch.setattr("buscador.engine.SafeExtractor.read", lambda *args, **kwargs: Extraction("texto reconocido", "contenido", "OCR"))
    assert index.scan(root, ocr=True).updated == 1
    assert index.search(root, "reconocido", mode="content").results
    assert index.scan(root, ocr=False).updated == 0
    assert index.search(root, "reconocido", mode="content").results


def test_technical_directories_are_optional_and_old_index_survives(tmp_path):
    root = tmp_path / "usuario"
    root.mkdir()
    technical = root / ".android"
    technical.mkdir()
    (technical / "emulador.txt").write_text("texto de emulador")
    (root / "documento.txt").write_text("documento personal")
    index = Index(tmp_path / "index.db")
    report = index.scan(root)
    assert report.excluded == 1 and report.seen == 2
    assert not index.search(root, "emulador", fuzzy=False).results
    index.scan(root, skip_technical=False)
    assert index.search(root, "emulador", fuzzy=False).results
    assert index.scan(root).removed == 0
    assert index.search(root, "emulador", fuzzy=False).results
    assert index.scan(technical).seen == 1


def test_timeout_is_saved_and_only_retried_on_explicit_force(tmp_path, monkeypatch):
    root = tmp_path / "docs"
    root.mkdir()
    (root / "lento.pdf").write_bytes(b"PDF de prueba")
    index = Index(tmp_path / "index.db")
    calls = []
    def slow(*args, **kwargs):
        calls.append(1)
        return Extraction(status="tiempo", note="Se agotó el tiempo")
    monkeypatch.setattr("buscador.engine.SafeExtractor.read", slow)
    assert index.scan(root).errors == 1
    assert index.scan(root).unchanged == 1
    assert len(calls) == 1
    assert index.search(root, "lento").results[0].status == "tiempo"
    index.scan(root, force=True)
    assert len(calls) == 2


def test_search_and_read_work_during_uncommitted_update(library):
    root, index = library
    index.scan(root)
    connection = index.connect()
    try:
        connection.execute("UPDATE entries SET generation='pending'")
        reopened = Index(index.database)
        assert reopened.count(root) == 5
        assert reopened.search(root, "factura").results
    finally:
        connection.rollback()
        connection.close()
