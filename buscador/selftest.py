"""Prueba del ejecutable distribuido usando únicamente documentos temporales."""

from __future__ import annotations

import json
import platform
import sys
import tempfile
import time
import zipfile
from pathlib import Path

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from buscador.app import MainWindow, STYLE
from buscador.engine import Index
from buscador import __version__


def run(report_path: Path) -> int:
    """Comprueba dependencias, GUI y búsqueda; escribe un informe incluso sin consola."""
    report_path = report_path.resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    checks: list[str] = []
    result = {"status": "failed", "version": __version__, "platform": sys.platform, "python": platform.python_version(),
              "frozen": bool(getattr(sys, "frozen", False)), "checks": checks}
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    app.setQuitOnLastWindowClosed(False)
    window = None
    try:
        with tempfile.TemporaryDirectory(prefix="buscador-verificacion-") as temporary:
            base = Path(temporary)
            documents = base / "Documentos con acentos á"
            documents.mkdir()
            (documents / "Factura eléctrica.txt").write_text("Cliente María. Consumo de electricidad en noviembre.", encoding="utf-8")
            with zipfile.ZipFile(documents / "Contrato.docx", "w") as archive:
                archive.writestr("word/document.xml", "<document><p><t>Construcción modular</t></p></document>")
            writer = PdfWriter()
            page = writer.add_blank_page(width=300, height=200)
            font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                     NameObject("/Subtype"): NameObject("/Type1"),
                                     NameObject("/BaseFont"): NameObject("/Helvetica")})
            mapping = DecodedStreamObject()
            mapping.set_data(b"begincmap\n/CMapType 2 def\n1 begincodespacerange\n<00> <FF>\nendcodespacerange\n1 beginbfchar\n<58> <D83D>\nendbfchar\nendcmap")
            font[NameObject("/ToUnicode")] = writer._add_object(mapping)
            page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
            stream = DecodedStreamObject()
            stream.set_data(b"BT /F1 12 Tf 10 150 Td (Presupuesto casa modular X) Tj ET")
            page[NameObject("/Contents")] = writer._add_object(stream)
            writer.write(str(documents / "Presupuesto.pdf"))
            # Load the native PDF DLL from the frozen package, as required by PDF OCR.
            import pypdfium2
            pdf = pypdfium2.PdfDocument(str(documents / "Presupuesto.pdf"))
            rendered_page = pdf[0]
            bitmap = rendered_page.render(scale=1)
            bitmap.to_pil().save(documents / "Imagen.png")
            bitmap.close()
            rendered_page.close()
            pdf.close()
            checks.append("PDFium: biblioteca nativa y renderizado PDF")
            index = Index(base / "indice.sqlite3")
            settings = QSettings(str(base / "settings.ini"), QSettings.Format.IniFormat)
            settings.setValue("location", str(documents))
            window = MainWindow(index, settings)
            window.resize(1280, 800)
            window.show()
            window.start_scan()
            stage = 0
            started = time.monotonic()
            failed = False

            def require(condition: bool, label: str) -> None:
                if not condition:
                    raise RuntimeError(label)
                checks.append(label)

            def tick() -> None:
                nonlocal stage, failed
                try:
                    if time.monotonic() - started > 60 and not failed:
                        raise TimeoutError("La comprobación excedió 60 segundos")
                    if failed:
                        for _thread, _worker, cancelled in window.jobs.values():
                            cancelled.set()
                        if not window.jobs:
                            timer.stop()
                            window.close()
                            app.exit(1)
                        return
                    if window.jobs:
                        return
                    if stage == 0:
                        require(index.count(documents) == 4, "Indexación desde la interfaz: 4 archivos")
                        pdf_match = index.search(documents, "presupuesto", mode="name", fuzzy=False).results
                        require(bool(pdf_match) and "modular �" in index.content(str(documents), pdf_match[0].path),
                                "PDF con Unicode defectuoso: texto conservado y actualización completada")
                        window.query.setText("factrua")
                        window.request_search()
                    elif stage == 1:
                        require(window.table.rowCount() == 1 and "María" in window.preview_text.toPlainText(),
                                "Búsqueda aproximada, acentos y vista previa de texto")
                        window.mode.setCurrentIndex(2)
                        window.query.setText("modular")
                        window.request_search()
                    elif stage == 2:
                        require({item.name for item in window.results} == {"Contrato.docx", "Presupuesto.pdf"},
                                "Búsqueda dentro de Word y PDF")
                        window.grab().save(str(report_path.with_suffix(".png")))
                        window.mode.setCurrentIndex(1)
                        window.kind.setCurrentText("Imagen")
                        window.query.setText("imagen")
                        window.request_search()
                    elif stage == 3:
                        require(window.table.rowCount() == 1 and not window.thumbnail.pixmap().isNull(),
                                "Filtro de imágenes y miniatura")
                        window.force.setChecked(True)
                        window.start_scan()
                        QTimer.singleShot(10, window.cancel_scan)
                    elif stage == 4:
                        require(window.index_button.isEnabled() and index.count(documents) == 4,
                                "Detención del proceso de indexación conservando el índice")
                        timer.stop()
                        window.close()
                        checks.append("Cierre sin trabajadores pendientes")
                        result["status"] = "passed"
                        app.exit(0)
                    stage += 1
                except Exception as error:
                    result["error"] = f"{type(error).__name__}: {error}"
                    failed = True

            timer = QTimer()
            timer.timeout.connect(tick)
            timer.start(50)
            app.exec()
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if result["status"] == "passed" else 1
