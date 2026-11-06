import time
import threading

from PySide6.QtCore import QSettings, QTimer

from buscador.app import MainWindow, STYLE
from buscador.engine import Index


def wait_until(app, predicate, timeout=30):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("La tarea de la interfaz no terminó a tiempo")


def test_desktop_indexes_searches_and_previews(tmp_path, qt_app):
    app = qt_app
    app.setStyleSheet(STYLE)
    root = tmp_path / "archivos"
    root.mkdir()
    (root / "Contrato de vivienda.txt").write_text("Alquiler de casa con jardín.", encoding="utf-8")
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("location", str(root))
    window = MainWindow(Index(tmp_path / "index.db"), settings)
    window.show()
    try:
        window.start_scan()
        wait_until(app, lambda: "scan" not in window.jobs)
        assert "1 revisadas" in window.scan_status.text()
        window.query.setText("alquler")
        window.request_search()
        wait_until(app, lambda: not window.jobs)
        assert window.table.rowCount() == 1
        assert window.preview_title.text() == "Contrato de vivienda.txt"
        assert "jardín" in window.preview_text.toPlainText()
        assert window.open_button.isEnabled()
        window.mode.setCurrentIndex(1)
        window.request_search()
        wait_until(app, lambda: not window.jobs)
        assert window.table.rowCount() == 0
        assert not window.open_button.isEnabled()
    finally:
        window.close()
        wait_until(app, lambda: not window.jobs)
        app.processEvents()


def test_preview_stays_responsive_and_wraps_long_lines(tmp_path, qt_app):
    root = tmp_path / "archivos"
    root.mkdir()
    (root / "figuras.txt").write_text("figuras\n" + ("patron" * 8000), encoding="utf-8")
    index = Index(tmp_path / "index.db")
    index.scan(root)
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("location", str(root))
    window = MainWindow(index, settings)
    ticks = []
    heartbeat = QTimer()
    heartbeat.timeout.connect(lambda: ticks.append(time.monotonic()))
    heartbeat.start(20)
    try:
        window.query.setText("figuras")
        window.request_search()
        wait_until(qt_app, lambda: "TEXTO DEL ARCHIVO" in window.preview_text.toPlainText())
        assert "Cargando" not in window.preview_text.toPlainText()
        assert max(len(line) for line in window.preview_text.toPlainText().splitlines()) <= 240
        assert ticks and max(b - a for a, b in zip(ticks, ticks[1:])) < 0.5
    finally:
        heartbeat.stop()
        window.close()
        wait_until(qt_app, lambda: not window.jobs)


def test_preview_failure_replaces_the_loading_message(tmp_path, qt_app, monkeypatch):
    root = tmp_path / "archivos"
    root.mkdir()
    (root / "nota.txt").write_text("casa", encoding="utf-8")
    index = Index(tmp_path / "index.db")
    index.scan(root)
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("location", str(root))

    def broken(*_args, **_kwargs):
        raise RuntimeError("disco ocupado")

    monkeypatch.setattr("buscador.app.load_preview", broken)
    window = MainWindow(index, settings)
    try:
        window.query.setText("casa")
        window.request_search()
        wait_until(qt_app, lambda: "disco ocupado" in window.preview_note.text())
        assert "Cargando" not in window.preview_text.toPlainText()
    finally:
        window.close()
        wait_until(qt_app, lambda: not window.jobs)


def test_changing_query_discards_stale_results(tmp_path, qt_app):
    app = qt_app
    root = tmp_path / "archivos"
    root.mkdir()
    (root / "primero.txt").write_text("uno")
    (root / "segundo.txt").write_text("dos")
    index = Index(tmp_path / "index.db")
    index.scan(root)
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("location", str(root))
    window = MainWindow(index, settings)
    try:
        window.query.setText("primero")
        window.request_search()
        window.query.setText("segundo")
        window.request_search()
        wait_until(app, lambda: not window.jobs)
        assert window.table.rowCount() == 1
        assert window.table.item(0, 0).text() == "segundo.txt"
    finally:
        window.close()
        wait_until(app, lambda: not window.jobs)


def test_closing_waits_for_worker_cancellation(tmp_path, qt_app):
    app = qt_app
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("location", str(tmp_path))
    window = MainWindow(Index(tmp_path / "index.db"), settings)
    window.show()
    cancelled = threading.Event()
    def operation(_worker):
        assert cancelled.wait(3), "Cerrar debe pedir la cancelación"
        return None
    window.start_job("search", operation, cancelled)
    window.close()
    wait_until(app, lambda: not window.jobs)
    assert cancelled.is_set()


def test_interface_heartbeat_and_stop_during_scan(tmp_path, qt_app):
    root = tmp_path / "muchos archivos"
    root.mkdir()
    for number in range(500):
        (root / f"nota-{number}.txt").write_text("documentación " * 100)
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("location", str(root))
    window = MainWindow(Index(tmp_path / "index.db"), settings)
    window.show()
    ticks = []
    heartbeat = QTimer()
    heartbeat.timeout.connect(lambda: ticks.append(time.monotonic()))
    heartbeat.start(20)
    try:
        window.start_scan()
        wait_until(qt_app, lambda: len(ticks) >= 15)
        assert "scan" in window.jobs
        assert max(b - a for a, b in zip(ticks, ticks[1:])) < 0.5
        started = time.monotonic()
        window.cancel_scan()
        wait_until(qt_app, lambda: "scan" not in window.jobs, timeout=8)
        assert time.monotonic() - started < 8
        assert window.index_button.isEnabled()
    finally:
        heartbeat.stop()
        window.close()
        wait_until(qt_app, lambda: not window.jobs)
