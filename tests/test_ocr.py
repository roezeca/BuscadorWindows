"""Prueba funcional del OCR real cuando Tesseract está instalado."""

import pytest
from PIL import Image, ImageDraw, ImageFont

from buscador.engine import Index
from buscador.extract import tesseract_path


@pytest.mark.skipif(tesseract_path() is None, reason="OCR opcional: Tesseract no está instalado")
def test_real_ocr_image_and_scanned_pdf(tmp_path):
    root = tmp_path / "escaneados"
    root.mkdir()
    picture = Image.new("RGB", (1400, 220), "white")
    draw = ImageDraw.Draw(picture)
    draw.text((50, 70), "INVOICE ELECTRICITY NOVEMBER", font=ImageFont.load_default(size=50), fill="black")
    picture.save(root / "imagen.png")
    picture.save(root / "escaneo.pdf")
    index = Index(tmp_path / "index.db")
    report = index.scan(root, ocr=True)
    assert report.errors == 0
    found = index.search(root, "electricity november", mode="content", fuzzy=False)
    assert {result.name for result in found.results} == {"imagen.png", "escaneo.pdf"}
