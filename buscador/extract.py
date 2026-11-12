"""Extractores con límites de recursos; nunca ejecutan el contenido indexado."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import threading
import zipfile
from dataclasses import dataclass
from pathlib import Path

from defusedxml import ElementTree
from PIL import Image, ExifTags
from pypdf import PdfReader
from buscador.unicode_text import clean_text

MAX_FILE_BYTES = 40 * 1024 * 1024
MAX_TEXT_CHARS = 1_000_000
MAX_XML_BYTES = 12 * 1024 * 1024
MAX_PDF_PAGES = 300
MAX_OCR_PAGES = 20
EXTRACTOR_VERSION = 1

TEXT_EXTENSIONS = set(".txt .md .csv .tsv .log .json .xml .html .htm .css .js .ts .tsx .jsx .py .java .c .cpp .h .cs .sql .yaml .yml .toml .ini .cfg .srt .vtt .ps1 .bat .sh .tex".split())
IMAGE_EXTENSIONS = set(".png .jpg .jpeg .webp .bmp .tif .tiff .gif .ico".split())
OFFICE_EXTENSIONS = {".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp"}
DOCUMENT_EXTENSIONS = TEXT_EXTENSIONS | OFFICE_EXTENSIONS | {".pdf", ".doc", ".xls", ".ppt", ".rtf"}


@dataclass(frozen=True)
class Extraction:
    text: str = ""
    status: str = "solo_nombre"
    note: str = "Formato sin extracción de contenido; se puede buscar por nombre."

    def __post_init__(self):
        text = clean_text(self.text)
        note = clean_text(self.note)
        status = clean_text(self.status)
        if text != self.text and text.count("\ufffd") > self.text.count("\ufffd"):
            note += " Se reemplazaron caracteres Unicode inválidos por �; el resto del texto se conservó."
            if status in {"contenido", "metadatos"}:
                status = "parcial"
        object.__setattr__(self, "text", text)
        object.__setattr__(self, "note", note)
        object.__setattr__(self, "status", status)


def file_kind(path: Path) -> str:
    extension = path.suffix.lower()
    if extension in IMAGE_EXTENSIONS:
        return "Imagen"
    if extension in DOCUMENT_EXTENSIONS:
        return "Documento"
    if extension in {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac"}:
        return "Audio"
    if extension in {".mp4", ".mkv", ".avi", ".mov", ".webm", ".wmv"}:
        return "Video"
    return "Archivo"


def tesseract_path() -> str | None:
    found = shutil.which("tesseract")
    if found:
        return found
    import os
    for variable in ("ProgramFiles", "LOCALAPPDATA"):
        base = os.environ.get(variable)
        if base:
            candidate = Path(base) / "Tesseract-OCR" / "tesseract.exe"
            if candidate.is_file():
                return str(candidate)
    return None


def ocr_languages(executable: str) -> str:
    result = subprocess.run(
        [executable, "--list-langs"], capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=10,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=True,
    )
    languages = set(result.stdout.splitlines()[1:])
    selected = [language for language in ("spa", "eng") if language in languages]
    if not selected:
        raise RuntimeError("Tesseract necesita el idioma español (spa) o inglés (eng).")
    return "+".join(selected)


def _ocr(image: Image.Image, executable: str, languages: str) -> str:
    image = image.convert("RGB")
    image.thumbnail((2400, 2400))
    with tempfile.TemporaryDirectory(prefix="buscador-ocr-") as folder:
        source = Path(folder) / "pagina.png"
        image.save(source)
        result = subprocess.run(
            [executable, str(source), "stdout", "-l", languages],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode:
            raise RuntimeError("Tesseract no pudo leer la imagen.")
        return result.stdout[:MAX_TEXT_CHARS]


def _decode(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    if b"\x00" in data[:4096]:
        raise ValueError("El archivo parece binario; no se interpretó como texto.")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _office(path: Path, cancelled: threading.Event) -> tuple[str, bool]:
    parts = []
    count = 0
    budget = 0
    with zipfile.ZipFile(path) as archive:
        selected = []
        for item in archive.infolist():
            name = item.filename
            if (re.fullmatch(r"word/(document|header\d*|footer\d*|footnotes|endnotes)\.xml", name)
                    or re.fullmatch(r"xl/(sharedStrings|worksheets/sheet\d+)\.xml", name)
                    or re.fullmatch(r"ppt/(slides/slide\d+|notesSlides/notesSlide\d+)\.xml", name)
                    or name == "content.xml"):
                selected.append(item)
        if not selected:
            raise ValueError("El documento no contiene las partes esperadas.")
        for item in selected:
            if cancelled.is_set():
                return "\n".join(parts), True
            budget += item.file_size
            if item.file_size > MAX_XML_BYTES or budget > MAX_FILE_BYTES:
                return "\n".join(parts), True
            root = ElementTree.fromstring(archive.read(item))
            # Formatting runs can split a single word. Keep adjacent runs together,
            # but separate paragraphs and cells so unrelated words never fuse.
            def local_tag(node):
                return node.tag.rsplit("}", 1)[-1]

            if item.filename.startswith(("word/", "ppt/")):
                paragraphs = []
                for paragraph in root.iter():
                    if local_tag(paragraph) == "p":
                        paragraphs.append("".join(
                            (node.text or "") if local_tag(node) == "t" else " "
                            for node in paragraph.iter() if local_tag(node) in {"t", "tab", "br"}
                        ))
                chunk = "\n".join(paragraphs)
            elif item.filename == "xl/sharedStrings.xml":
                chunk = "\n".join("".join(node.itertext()) for node in root.iter() if local_tag(node) == "si")
            elif item.filename.startswith("xl/worksheets/"):
                chunk = "\n".join("".join(
                    child.text or "" for child in node.iter() if local_tag(child) in {"t", "v"}
                ) for node in root.iter() if local_tag(node) == "c")
            else:
                chunk = "\n".join("".join(node.itertext()) for node in root.iter() if local_tag(node) in {"p", "h"})
            parts.append(chunk[:MAX_TEXT_CHARS - count])
            count += len(chunk)
            if count >= MAX_TEXT_CHARS:
                return "\n".join(parts)[:MAX_TEXT_CHARS], True
    return "\n".join(parts), False


def _pdf(path: Path, cancelled: threading.Event, executable: str | None, languages: str) -> Extraction:
    reader = PdfReader(path)
    if reader.is_encrypted and not reader.decrypt(""):
        return Extraction(status="protegido", note="PDF protegido por contraseña; solo se indexó el nombre.")
    parts: list[str] = []
    total = 0
    scanned = 0
    limited = len(reader.pages) > MAX_PDF_PAGES
    pdf_image = None
    try:
        for number, page in enumerate(reader.pages[:MAX_PDF_PAGES]):
            if cancelled.is_set():
                break
            text = page.extract_text() or ""
            if not text.strip():
                scanned += 1
                if executable and scanned <= MAX_OCR_PAGES:
                    import pypdfium2
                    if pdf_image is None:
                        pdf_image = pypdfium2.PdfDocument(str(path))
                    rendered_page = pdf_image[number]
                    try:
                        width, height = rendered_page.get_size()
                        scale = min(2.0, 2400 / max(width, height, 1))
                        bitmap = rendered_page.render(scale=scale)
                        try:
                            text = _ocr(bitmap.to_pil(), executable, languages)
                        finally:
                            bitmap.close()
                    finally:
                        rendered_page.close()
                else:
                    limited = True
            parts.append(text[:MAX_TEXT_CHARS - total])
            total += len(text)
            if total >= MAX_TEXT_CHARS:
                limited = True
                break
    finally:
        if pdf_image is not None:
            pdf_image.close()
    note = "Texto extraído del PDF."
    if scanned:
        note = ("Incluye texto reconocido con OCR." if executable else
                "Tiene páginas sin texto extraíble; activa OCR para buscar en ellas.")
    if limited:
        note += " Extracción parcial: páginas sin OCR o límite de tamaño/páginas."
    return Extraction("\n".join(parts), "parcial" if limited else "contenido", note)


def extract(path: Path, cancelled: threading.Event, executable: str | None = None, languages: str = "eng") -> Extraction:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return Extraction(status="limite", note="Supera 40 MiB; se indexó únicamente el nombre.")
        extension = path.suffix.lower()
        if extension in TEXT_EXTENSIONS:
            with path.open("rb") as stream:
                data = stream.read(MAX_FILE_BYTES + 1)
            text = _decode(data)
            limited = len(text) > MAX_TEXT_CHARS
            return Extraction(text[:MAX_TEXT_CHARS], "parcial" if limited else "contenido",
                              "Se alcanzó el límite de texto." if limited else "Texto extraído.")
        if extension in OFFICE_EXTENSIONS:
            text, limited = _office(path, cancelled)
            return Extraction(text, "parcial" if limited else "contenido",
                              "Extracción parcial por límites de tamaño." if limited else "Texto extraído del documento.")
        if extension == ".pdf":
            return _pdf(path, cancelled, executable, languages)
        if extension in IMAGE_EXTENSIONS:
            with Image.open(path) as picture:
                metadata = []
                for key, value in picture.getexif().items():
                    if isinstance(value, str):
                        metadata.append(f"{ExifTags.TAGS.get(key, key)}: {value[:2000]}")
                if executable and not cancelled.is_set():
                    metadata.append(_ocr(picture, executable, languages))
                return Extraction("\n".join(metadata)[:MAX_TEXT_CHARS], "contenido" if executable else "metadatos",
                                  "Texto reconocido con OCR y metadatos." if executable else
                                  "Nombre y metadatos. Activa OCR para reconocer texto visible en la imagen.")
        return Extraction()
    except Exception as error:
        # Corrupt, unsupported, encrypted or inaccessible files must not stop an entire scan.
        return Extraction(status="error", note=f"No se pudo extraer el contenido ({type(error).__name__}).")
