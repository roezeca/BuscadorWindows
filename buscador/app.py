"""Interfaz de escritorio. Las lecturas, el OCR y las búsquedas corren fuera de la UI."""

from __future__ import annotations

import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QSettings, QStandardPaths, Qt, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget, QAbstractItemView, QScrollArea, QLayout,
)

from buscador.engine import Index, ScanReport, SearchResponse, SearchResult
from buscador.extract import tesseract_path
from buscador.processes import load_preview, run_task
from buscador.unicode_text import preview_document
from buscador import __version__


STYLE = """
QMainWindow, QWidget#canvas { background: #f3f5f8; color: #192b3f; }
QWidget { font-family: 'Segoe UI', 'Noto Sans', sans-serif; font-size: 13px; }
QLabel { color: #192b3f; }
QLabel#brand { font-size: 28px; font-weight: 700; }
QLabel#subtitle, QLabel#hint { color: #617184; }
QLabel#section { font-size: 12px; font-weight: 700; color: #536679; }
QFrame#card { background: white; border: 1px solid #dfe5ec; border-radius: 12px; }
QLineEdit, QComboBox, QPlainTextEdit { background: white; color: #192b3f; border: 1px solid #cbd5e1; border-radius: 6px; padding: 9px; selection-background-color: #087f8c; }
QLineEdit, QComboBox { min-height: 18px; }
QLineEdit:focus, QComboBox:focus { border: 2px solid #087f8c; }
QPushButton { min-height: 18px; padding: 10px 16px; border: 1px solid #cbd5e1; border-radius: 6px; background: white; color: #22364b; font-weight: 600; }
QPushButton:hover { background: #eef6f7; border-color: #087f8c; }
QPushButton#primary { background: #087f8c; color: white; border: 1px solid #087f8c; }
QPushButton#primary:hover { background: #066874; }
QPushButton:disabled { background: #e9edf2; color: #8a97a5; border-color: #dfe5ec; }
QCheckBox { spacing: 8px; color: #263c50; }
QTableWidget { background: white; alternate-background-color: #f8fafc; border: 0; color: #192b3f; gridline-color: #edf1f5; selection-background-color: #dff1f2; selection-color: #12525b; }
QHeaderView::section { background: #f3f6f9; color: #607184; border: 0; padding: 12px 8px; font-weight: 600; }
QTableWidget::item { padding: 8px; border-bottom: 1px solid #eef2f6; }
QProgressBar { border: 0; border-radius: 3px; background: #dfe7ed; max-height: 6px; }
QProgressBar::chunk { background: #087f8c; border-radius: 3px; }
QSplitter::handle { background: #e2e8f0; }
"""


def size_label(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return ""


class Worker(QObject):
    result = Signal(str, object)
    failed = Signal(str, str)
    progress = Signal(object, str)
    finished = Signal()

    def __init__(self, name: str, operation: Callable):
        super().__init__()
        self.name = name
        self.operation = operation

    @Slot()
    def run(self) -> None:
        try:
            self.result.emit(self.name, self.operation(self))
        except Exception as error:
            self.failed.emit(self.name, str(error))
        finally:
            self.finished.emit()


class MainWindow(QMainWindow):
    def __init__(self, index: Index, settings: QSettings | None = None):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.index = index
        self.settings = settings if settings is not None else QSettings()
        self.jobs: dict[str, tuple[QThread, Worker, threading.Event]] = {}
        self.results: list[SearchResult] = []
        self.pending_search = False
        self.pending_tasks = {}
        self.scan_epoch = 0
        self.preview_generation = 0
        self.closing = False
        self.search_generation = 0
        self.results_root = ""
        self.setWindowTitle(f"Buscador {__version__} · Archivos y contenido")
        self.resize(1280, 830)
        self.setMinimumSize(1000, 680)
        canvas = QWidget(objectName="canvas")
        self.setCentralWidget(canvas)
        layout = QVBoxLayout(canvas)
        layout.setContentsMargins(26, 22, 26, 18)
        layout.setSpacing(16)

        header = QHBoxLayout()
        title = QVBoxLayout()
        title.addWidget(QLabel("Buscador", objectName="brand"))
        title.addWidget(QLabel("Encuentra archivos, incluso cuando no recuerdas el nombre exacto.", objectName="subtitle"))
        header.addLayout(title)
        header.addStretch()
        privacy = QLabel("ÍNDICE LOCAL\nTus documentos quedan en este equipo", objectName="hint")
        privacy.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(privacy)
        layout.addLayout(header)

        location_card = QFrame(objectName="card")
        location_layout = QVBoxLayout(location_card)
        location_layout.setContentsMargins(16, 12, 16, 14)
        location_layout.addWidget(QLabel("1  ·  ELIGE DÓNDE BUSCAR", objectName="section"))
        path_row = QHBoxLayout()
        self.location = QLineEdit(str(self.settings.value("location", str(Path.home()))))
        self.location.setPlaceholderText("Carpeta, unidad o ubicación de red…")
        self.location.setAccessibleName("Ubicación de búsqueda")
        self.browse = QPushButton("Elegir carpeta…")
        self.index_button = QPushButton("Actualizar índice", objectName="primary")
        self.stop = QPushButton("Detener")
        self.stop.setEnabled(False)
        path_row.addWidget(self.location, 1)
        path_row.addWidget(self.browse)
        path_row.addWidget(self.index_button)
        path_row.addWidget(self.stop)
        location_layout.addLayout(path_row)
        self.scan_status = QLabel("Elige una carpeta y actualiza el índice para empezar.", objectName="hint")
        self.scan_status.setWordWrap(True)
        location_layout.addWidget(self.scan_status)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.hide()
        location_layout.addWidget(self.progress)
        layout.addWidget(location_card)

        search_row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setMinimumHeight(48)
        self.query.setPlaceholderText("2  ·  Busca un nombre, una palabra o algo que recuerdes del documento…")
        self.query.setAccessibleName("Texto de búsqueda")
        self.search_button = QPushButton("Buscar", objectName="primary")
        self.search_button.setMinimumHeight(48)
        search_row.addWidget(self.query, 1)
        search_row.addWidget(self.search_button)
        layout.addLayout(search_row)
        self.search_progress = QProgressBar()
        self.search_progress.setTextVisible(False)
        self.search_progress.setAccessibleName("Progreso de la búsqueda")
        self.search_progress.hide()
        layout.addWidget(self.search_progress)

        body = QHBoxLayout()
        filters_card = QFrame(objectName="card")
        filters = QVBoxLayout(filters_card)
        filters.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        filters.setContentsMargins(16, 18, 16, 18)
        filters.setSpacing(12)
        filters.addWidget(QLabel("AJUSTAR BÚSQUEDA", objectName="section"))
        filters.addWidget(QLabel("Buscar en"))
        self.mode = QComboBox()
        for label, data in (("Nombre y contenido", "both"), ("Solo nombres", "name"), ("Solo contenido", "content")):
            self.mode.addItem(label, data)
        filters.addWidget(self.mode)
        filters.addWidget(QLabel("Tipo de resultado"))
        self.kind = QComboBox()
        self.kind.addItems(["Todos", "Documento", "Imagen", "Carpeta", "Audio", "Video", "Archivo"])
        filters.addWidget(self.kind)
        filters.addWidget(QLabel("Extensiones"))
        self.extensions = QLineEdit()
        self.extensions.setPlaceholderText("Ej.: pdf, docx, jpg")
        self.extensions.setAccessibleName("Filtrar por extensiones")
        filters.addWidget(self.extensions)
        self.fuzzy = QCheckBox("Palabras parecidas")
        self.fuzzy.setChecked(True)
        self.fuzzy.setToolTip("Tolera errores de escritura y busca palabras de forma parecida. No es búsqueda por significado.")
        filters.addWidget(self.fuzzy)
        hint = QLabel("No hace falta escribir los acentos. Las palabras se pueden encontrar en cualquier orden.", objectName="hint")
        hint.setWordWrap(True)
        filters.addWidget(hint)
        filters.addSpacing(16)
        filters.addWidget(QLabel("LECTURA DE DOCUMENTOS", objectName="section"))
        self.ocr = QCheckBox("Reconocer texto (OCR)")
        self.ocr.setChecked(self.settings.value("ocr", False, type=bool))
        self.ocr.setToolTip("Lee texto de imágenes y PDF escaneados al actualizar el índice. Requiere Tesseract; puede tardar.")
        filters.addWidget(self.ocr)
        self.ocr_status = QLabel("Tesseract disponible" if tesseract_path() else "OCR opcional: instala Tesseract con español o inglés.", objectName="hint")
        self.ocr_status.setWordWrap(True)
        filters.addWidget(self.ocr_status)
        self.skip_technical = QCheckBox("Omitir carpetas técnicas")
        self.skip_technical.setChecked(self.settings.value("skip_technical", True, type=bool))
        self.skip_technical.setToolTip("Evita AppData, .android, node_modules, entornos y cachés. No borra entradas antiguas ni archivos. Puedes elegir directamente una de esas carpetas para recorrerla.")
        filters.addWidget(self.skip_technical)
        self.technical_hint = QLabel("Recomendado al buscar en todo tu usuario o una unidad. El OCR puede tardar mucho en colecciones grandes.", objectName="hint")
        self.technical_hint.setWordWrap(True)
        filters.addWidget(self.technical_hint)
        self.force = QCheckBox("Volver a leer todo")
        self.force.setToolTip("Reprocesa incluso los archivos que no cambiaron.")
        filters.addWidget(self.force)
        self.log_button = QPushButton("Ver registro de actividad")
        self.log_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.index.database.parent / "actividad.log"))))
        filters.addWidget(self.log_button)
        filters.addStretch()
        self.clear_button = QPushButton("Borrar este índice")
        self.clear_button.setToolTip("Borra las entradas locales de esta ubicación. No elimina tus archivos.")
        filters.addWidget(self.clear_button)
        filters_scroll = QScrollArea()
        filters_scroll.setFrameShape(QFrame.Shape.NoFrame)
        filters_scroll.setWidgetResizable(True)
        filters_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        filters_scroll.setFixedWidth(250)
        filters_scroll.setWidget(filters_card)
        body.addWidget(filters_scroll)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        results_card = QFrame(objectName="card")
        results_layout = QVBoxLayout(results_card)
        results_layout.setContentsMargins(12, 14, 12, 12)
        self.result_status = QLabel("Escribe qué quieres encontrar", objectName="section")
        self.result_status.setWordWrap(True)
        results_layout.addWidget(self.result_status)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Nombre", "Tipo", "Tamaño", "Coincidencia"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(43)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        results_layout.addWidget(self.table)
        self.expanded = QLabel("", objectName="hint")
        self.expanded.setWordWrap(True)
        results_layout.addWidget(self.expanded)
        splitter.addWidget(results_card)

        preview_card = QFrame(objectName="card")
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(16, 14, 16, 16)
        preview_layout.addWidget(QLabel("VISTA PREVIA", objectName="section"))
        self.preview_title = QLabel("Selecciona un resultado")
        self.preview_title.setWordWrap(True)
        self.preview_title.setTextFormat(Qt.TextFormat.PlainText)
        self.preview_title.setStyleSheet("font-size: 17px; font-weight: 600;")
        preview_layout.addWidget(self.preview_title)
        self.preview_meta = QLabel("Aquí verás su ubicación y el texto extraído.", objectName="hint")
        self.preview_meta.setWordWrap(True)
        self.preview_meta.setTextFormat(Qt.TextFormat.PlainText)
        self.preview_meta.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        preview_layout.addWidget(self.preview_meta)
        self.thumbnail = QLabel()
        self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail.setMaximumHeight(180)
        self.thumbnail.hide()
        preview_layout.addWidget(self.thumbnail)
        self.preview_text = QPlainTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setPlaceholderText("El texto del documento aparecerá aquí.")
        preview_layout.addWidget(self.preview_text, 1)
        self.preview_note = QLabel("", objectName="hint")
        self.preview_note.setWordWrap(True)
        self.preview_note.setTextFormat(Qt.TextFormat.PlainText)
        preview_layout.addWidget(self.preview_note)
        self.open_button = QPushButton("Abrir archivo")
        self.folder_button = QPushButton("Abrir ubicación")
        self.open_button.setEnabled(False)
        self.folder_button.setEnabled(False)
        preview_layout.addWidget(self.open_button)
        preview_layout.addWidget(self.folder_button)
        splitter.addWidget(preview_card)
        splitter.setSizes([650, 320])
        body.addWidget(splitter, 1)
        layout.addLayout(body, 1)
        footer = QLabel("La búsqueda usa la última actualización del índice. Actualízalo cuando agregues o cambies archivos.", objectName="hint")
        footer.setWordWrap(True)
        layout.addWidget(footer)

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(350)
        self.timer.timeout.connect(self.request_search)
        self.query.textChanged.connect(self.schedule_search)
        self.extensions.textChanged.connect(self.schedule_search)
        self.location.textChanged.connect(self.location_changed)
        self.mode.currentIndexChanged.connect(self.schedule_search)
        self.kind.currentIndexChanged.connect(self.schedule_search)
        self.fuzzy.toggled.connect(self.schedule_search)
        self.query.returnPressed.connect(self.request_search)
        self.search_button.clicked.connect(self.request_search)
        self.browse.clicked.connect(self.choose_folder)
        self.index_button.clicked.connect(self.start_scan)
        self.stop.clicked.connect(self.cancel_scan)
        self.clear_button.clicked.connect(self.clear_index)
        self.table.itemSelectionChanged.connect(self.show_preview)
        self.table.cellDoubleClicked.connect(lambda _row, _column: self.open_selected())
        self.open_button.clicked.connect(self.open_selected)
        self.folder_button.clicked.connect(lambda: self.open_selected(folder=True))
        self.location_changed()

    def choose_folder(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Elige la ubicación de búsqueda", self.location.text())
        if chosen:
            self.location.setText(chosen)

    def location_changed(self, *_args) -> None:
        self.schedule_search()
        if self.location.text().strip():
            root = self.location.text().strip()
            self.scan_status.setText("Consultando el índice guardado…")
            self.queue_task("count", {"root": root}, (root, self.scan_epoch), 15)

    def queue_task(self, name, arguments, token, timeout):
        self.pending_tasks[name] = (arguments, token, timeout)
        if name in self.jobs:
            self.jobs[name][2].set()
        else:
            self.start_queued(name)

    def start_queued(self, name):
        if self.closing:
            return
        arguments, token, timeout = self.pending_tasks.pop(name)
        cancelled = threading.Event()
        if name == "preview":
            operation = lambda _worker: (token, load_preview(
                self.index.database, arguments["root"], arguments["path"], arguments.get("image", False), cancelled))
        else:
            operation = lambda _worker: (token, run_task(self.index.database, name, arguments, cancelled, timeout=timeout))
        self.start_job(name, operation, cancelled)

    def schedule_search(self, *_args) -> None:
        self.search_generation += 1
        if "search" in self.jobs:
            self.jobs["search"][2].set()
        self.timer.start()

    def start_job(self, name: str, operation: Callable, cancelled: threading.Event) -> None:
        thread = QThread(self)
        worker = Worker(name, operation)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.result.connect(self.job_result)
        worker.failed.connect(self.job_failed)
        worker.progress.connect(self.scan_progress)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self.thread_finished)
        thread.setObjectName(name)
        self.jobs[name] = (thread, worker, cancelled)
        thread.start()

    @Slot()
    def thread_finished(self) -> None:
        thread = self.sender()
        name = thread.objectName()
        self.jobs.pop(name, None)
        thread.deleteLater()
        if name == "scan":
            self.set_scanning(False)
        if name == "clear":
            self.index_button.setEnabled(True)
            self.clear_button.setEnabled(True)
        if self.closing and not self.jobs:
            self.close()
        elif name == "search" and self.pending_search:
            self.pending_search = False
            self.request_search()
        elif name == "search":
            self.set_searching(False)
        elif name in self.pending_tasks and not self.closing:
            self.start_queued(name)

    def set_searching(self, active: bool) -> None:
        self.search_progress.setVisible(active)
        self.search_progress.setRange(0, 0 if active else 100)

    def set_scanning(self, active: bool) -> None:
        for widget in (self.index_button, self.location, self.browse, self.ocr, self.force, self.skip_technical, self.clear_button):
            widget.setEnabled(not active)
        self.stop.setEnabled(active)
        self.progress.setVisible(active)
        self.progress.setRange(0, 0 if active else 100)

    def start_scan(self) -> None:
        if "scan" in self.jobs or "clear" in self.jobs or not self.location.text().strip():
            return
        root = self.location.text().strip()
        self.settings.setValue("location", root)
        ocr, force = self.ocr.isChecked(), self.force.isChecked()
        self.settings.setValue("ocr", ocr)
        self.settings.setValue("skip_technical", self.skip_technical.isChecked())
        self.scan_epoch += 1
        cancelled = threading.Event()
        self.set_scanning(True)
        self.scan_status.setText("Leyendo archivos… Puedes seguir buscando en el índice existente.")
        arguments = dict(root=root, ocr=ocr, force=force, skip_technical=self.skip_technical.isChecked())
        self.start_job("scan", lambda worker: run_task(
            self.index.database, "scan", arguments, cancelled, progress=worker.progress.emit), cancelled)

    def cancel_scan(self) -> None:
        if "scan" in self.jobs:
            self.jobs["scan"][2].set()
            self.stop.setEnabled(False)
            self.scan_status.setText("Deteniendo la lectura y conservando los lotes guardados…")

    @Slot(object, str)
    def scan_progress(self, report: dict, path: str) -> None:
        if "scan" in self.jobs and not self.jobs["scan"][2].is_set():
            minutes = int(report.get("elapsed", 0)) // 60
            current = int(report.get("current_seconds", 0))
            self.scan_status.setText(f"{report['seen']:,} revisadas · {report['updated']:,} actualizadas · {report['unchanged']:,} sin cambios · {report['errors']} errores · {minutes} min\n"
                                     f"{report.get('excluded', 0)} carpetas técnicas omitidas · Lectura actual: {current} s · {path[-120:]}")

    def request_search(self) -> None:
        self.timer.stop()
        if self.closing:
            return
        if "search" in self.jobs:
            self.jobs["search"][2].set()
            self.pending_search = True
            self.set_searching(True)
            return
        root, query = self.location.text().strip(), self.query.text().strip()
        if not root or not query:
            self.set_searching(False)
            self.display_results(SearchResponse([], {}))
            self.result_status.setText("Escribe qué quieres encontrar")
            return
        generation = self.search_generation
        options = dict(mode=self.mode.currentData(), kind=self.kind.currentText(),
                       extensions=self.extensions.text(), fuzzy=self.fuzzy.isChecked())
        cancelled = threading.Event()
        self.result_status.setText("Buscando…")
        self.set_searching(True)
        self.start_job("search", lambda _worker: (generation, root, run_task(
            self.index.database, "search", dict(root=root, query=query, **options), cancelled, timeout=30)), cancelled)

    @Slot(str, object)
    def job_result(self, name: str, value) -> None:
        if self.closing:
            return
        if name == "scan":
            report: ScanReport = value
            if report is None:
                self.scan_status.setText("Detenido. Se conservan los lotes guardados.")
                return
            self.scan_status.setText(
                f"{'Detenido' if report.cancelled else 'Índice actualizado'} · {report.seen:,} revisadas · "
                f"{report.updated:,} actualizadas · {report.unchanged:,} sin cambios · {report.removed:,} retiradas\n"
                f"{report.errors} errores · {report.partial} lecturas parciales · {report.excluded} carpetas técnicas omitidas · Registro disponible"
            )
            self.scan_status.setToolTip("\n".join(report.warnings))
            self.request_search()
        elif name == "search":
            generation, root, response = value
            if generation == self.search_generation and response is not None:
                self.set_searching(False)
                self.results_root = root
                self.display_results(response)
            elif not self.pending_search:
                self.set_searching(False)
        elif name == "count":
            token, count = value
            if count is not None and token == (self.location.text().strip(), self.scan_epoch) and "scan" not in self.jobs:
                self.scan_status.setText(f"{count:,} entradas guardadas. Puedes buscar sin actualizar." if count else
                                         "Esta ubicación aún no tiene índice. Pulsa «Actualizar índice».")
        elif name == "preview":
            token, data = value
            if token == self.preview_generation and data is not None:
                content, thumbnail = data
                result = self.selected()
                if result:
                    prefix = f"COINCIDENCIA\n{preview_document(result.excerpt, limit=2000)}\n\nTEXTO DEL ARCHIVO\n" if result.excerpt else ""
                    self.preview_text.setPlainText(prefix + content)
                    if thumbnail:
                        picture = QPixmap()
                        if picture.loadFromData(thumbnail, "PNG"):
                            self.thumbnail.setPixmap(picture)
                            self.thumbnail.show()
        elif name == "clear":
            self.scan_epoch += 1
            self.location_changed()

    @Slot(str, str)
    def job_failed(self, name: str, message: str) -> None:
        if self.closing:
            return
        if name == "scan":
            self.scan_status.setText("No se pudo completar la actualización.")
            QMessageBox.warning(self, "No se pudo actualizar el índice", message)
        elif name == "search":
            self.set_searching(False)
            self.result_status.setText("No se pudo completar la búsqueda: " + message)
        elif name == "preview":
            self.preview_text.setPlainText("No se pudo cargar la vista previa.")
            self.preview_note.setText("No se pudo cargar la vista previa: " + message)
        else:
            self.scan_status.setText("No se pudo completar la operación: " + message)

    def display_results(self, response: SearchResponse) -> None:
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(0)
            self.results = response.results
            self.table.setRowCount(len(self.results))
            for row, result in enumerate(self.results):
                for column, value in enumerate((result.name, result.kind, "—" if result.kind == "Carpeta" else size_label(result.size), result.match)):
                    item = QTableWidgetItem(value)
                    item.setToolTip(result.path)
                    self.table.setItem(row, column, item)
        finally:
            self.table.blockSignals(False)
        count = len(self.results)
        self.result_status.setText(f"{count} {'resultado' if count == 1 else 'resultados'}" + (" · Hay más: acota la búsqueda" if response.truncated else "") if count else
                                   "Sin resultados · Prueba otra palabra o actualiza el índice")
        expansions = [f"{key} → {', '.join(values)}" for key, values in response.expanded.items()]
        self.expanded.setText("También se buscaron: " + " · ".join(expansions) if expansions else "")
        if count:
            self.table.selectRow(0)
        else:
            self.show_preview()

    def selected(self) -> SearchResult | None:
        row = self.table.currentRow()
        return self.results[row] if 0 <= row < len(self.results) else None

    def show_preview(self) -> None:
        self.preview_generation += 1
        if "preview" in self.jobs:
            self.jobs["preview"][2].set()
        self.pending_tasks.pop("preview", None)
        result = self.selected()
        self.thumbnail.clear()
        self.thumbnail.hide()
        self.open_button.setEnabled(result is not None)
        self.folder_button.setEnabled(result is not None)
        if result is None:
            self.preview_title.setText("Selecciona un resultado")
            self.preview_meta.setText("")
            self.preview_text.clear()
            self.preview_note.setText("")
            return
        self.preview_title.setText(result.name)
        stamp = datetime.fromtimestamp(result.modified).strftime("%d/%m/%Y %H:%M")
        self.preview_meta.setText(f"{result.path}\n\n{result.kind} · Modificado: {stamp}")
        self.preview_text.setPlainText("Cargando vista previa…")
        self.preview_note.setText(result.note + " Vista previa de hasta 60.000 caracteres.")
        self.open_button.setText("Abrir carpeta" if result.kind == "Carpeta" else "Abrir archivo")
        self.queue_task("preview", {"root": self.results_root, "path": result.path, "image": result.kind == "Imagen"}, self.preview_generation, 15)

    def open_selected(self, _checked: bool = False, *, folder: bool = False) -> None:
        result = self.selected()
        if not result:
            return
        path = Path(result.path)
        if folder:
            path = path if result.kind == "Carpeta" else path.parent
        if not path.exists():
            QMessageBox.information(self, "Ubicación no disponible", "El archivo pudo moverse o la unidad está desconectada. Actualiza el índice.")
            return
        if not folder and path.suffix.lower() in {".exe", ".com", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".msi", ".lnk", ".url", ".scr"}:
            if QMessageBox.question(self, "Abrir archivo ejecutable", "Este archivo puede ejecutar programas. ¿Quieres abrirlo?") != QMessageBox.StandardButton.Yes:
                return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            QMessageBox.warning(self, "No se pudo abrir", "Windows no pudo abrir esta ubicación con la aplicación predeterminada.")

    def clear_index(self) -> None:
        if "scan" in self.jobs:
            return
        if QMessageBox.question(self, "Borrar índice local", "Se borrará el índice de esta ubicación. Tus archivos originales no se modificarán. ¿Continuar?") == QMessageBox.StandardButton.Yes:
            self.index_button.setEnabled(False)
            self.clear_button.setEnabled(False)
            self.scan_status.setText("Borrando las entradas del índice local…")
            self.queue_task("clear", {"root": self.location.text()}, None, None)

    def closeEvent(self, event) -> None:
        self.timer.stop()
        self.settings.setValue("location", self.location.text())
        if self.jobs:
            self.closing = True
            for _thread, _worker, cancelled in self.jobs.values():
                cancelled.set()
            self.scan_status.setText("Deteniendo los trabajadores para cerrar…")
            event.ignore()
        else:
            event.accept()


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        from buscador.selftest import run
        sys.exit(run(Path(sys.argv[2])))
    app = QApplication(sys.argv)
    app.setApplicationName("BuscadorWindows")
    app.setOrganizationName("BuscadorWindows")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    folder = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
    try:
        index = Index(folder / "indice.sqlite3", initialize=False)
    except Exception as error:
        QMessageBox.critical(None, "No se pudo abrir el índice", f"No se pudo preparar el índice local en {folder}:\n{error}")
        return
    window = MainWindow(index)
    window.show()
    sys.exit(app.exec())
