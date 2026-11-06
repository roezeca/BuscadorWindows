import threading
import zipfile

import pytest
from PIL import Image

from buscador.extract import extract


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "cp1252"])
def test_text_encodings(tmp_path, encoding):
    path = tmp_path / "texto.txt"
    path.write_bytes("Información del año: habitación".encode(encoding))
    result = extract(path, threading.Event())
    assert "habitación" in result.text
    assert result.status == "contenido"


@pytest.mark.parametrize(("extension", "member", "xml", "expected"), [
    ("docx", "word/document.xml", "<document><p><t>Contrato de alquiler</t></p></document>", "alquiler"),
    ("xlsx", "xl/sharedStrings.xml", "<sst><si><t>Ventas trimestrales</t></si></sst>", "trimestrales"),
    ("xlsx", "xl/worksheets/sheet1.xml", "<worksheet><c><is><t>Inventario</t></is></c></worksheet>", "Inventario"),
    ("pptx", "ppt/slides/slide1.xml", "<slide><p><t>Objetivos anuales</t></p></slide>", "Objetivos"),
    ("odt", "content.xml", "<document><p>Memoria descriptiva</p></document>", "descriptiva"),
    ("docx", "word/document.xml", "<document><p><r><t>construc</t></r><r><t>ción</t></r></p><p><t>modular</t></p></document>", "construcción\nmodular"),
    ("xlsx", "xl/sharedStrings.xml", "<sst><si><r><t>Presu</t></r><r><t>puesto</t></r></si></sst>", "Presupuesto"),
])
def test_office_formats(tmp_path, extension, member, xml, expected):
    path = tmp_path / ("documento." + extension)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(member, xml)
    result = extract(path, threading.Event())
    assert result.status == "contenido"
    assert expected in result.text


def test_pdf_text_and_encryption(tmp_path, pdf_factory):
    assert "casa modular" in extract(pdf_factory(tmp_path / "texto.pdf"), threading.Event()).text
    locked = extract(pdf_factory(tmp_path / "protegido.pdf", encrypted=True), threading.Event())
    assert locked.status == "protegido" and not locked.text


def test_image_metadata_and_ocr_dispatch(tmp_path, monkeypatch):
    path = tmp_path / "foto.jpg"
    metadata = Image.Exif()
    metadata[270] = "Paisaje montanoso"
    Image.new("RGB", (100, 60), "white").save(path, exif=metadata)
    result = extract(path, threading.Event())
    assert "Paisaje" in result.text and result.status == "metadatos"
    monkeypatch.setattr("buscador.extract._ocr", lambda *args: "Cartel de bienvenida")
    result = extract(path, threading.Event(), executable="tesseract", languages="spa")
    assert "bienvenida" in result.text and result.status == "contenido"


def test_xml_entities_are_rejected(tmp_path):
    path = tmp_path / "malicioso.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", '<!DOCTYPE x [<!ENTITY a "expansion">]><x>&a;</x>')
    assert extract(path, threading.Event()).status == "error"


def test_limits_are_reported(tmp_path, monkeypatch):
    path = tmp_path / "texto.txt"
    path.write_text("un texto muy largo")
    monkeypatch.setattr("buscador.extract.MAX_TEXT_CHARS", 5)
    result = extract(path, threading.Event())
    assert result.status == "parcial" and len(result.text) == 5
    monkeypatch.setattr("buscador.extract.MAX_FILE_BYTES", 3)
    assert extract(path, threading.Event()).status == "limite"


def test_unknown_and_binary_content(tmp_path):
    unknown = tmp_path / "archivo.xyz"
    unknown.write_bytes(b"datos")
    assert extract(unknown, threading.Event()).status == "solo_nombre"
    binary = tmp_path / "binario.txt"
    binary.write_bytes(b"\x00\x00abc")
    assert extract(binary, threading.Event()).status == "error"
