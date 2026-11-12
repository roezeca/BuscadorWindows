import threading
import time
from pathlib import Path

import psutil

from buscador.extract import Extraction
from buscador.processes import SafeExtractor, run_task
from buscador.engine import Index


def hanging_reader(pipe):
    pipe.send("ready")
    pipe.recv()
    time.sleep(60)


def crash_reader(pipe):
    pipe.send("ready")
    pipe.recv()
    pipe.close()


def healthy_reader(pipe):
    pipe.send("ready")
    while True:
        try:
            pipe.recv()
            pipe.send(Extraction("texto recuperado", "contenido", "ok"))
        except EOFError:
            return


def controlled_scan_task(pipe, event, database, operation, arguments):
    # Slow the reads in this test worker so cancellation happens during work,
    # rather than racing a fully completed 50 ms metadata scan.
    from buscador.processes import _task_main, SafeExtractor
    original = SafeExtractor.read
    def delayed(self, *args, **kwargs):
        time.sleep(0.005)
        return original(self, *args, **kwargs)
    SafeExtractor.read = delayed
    _task_main(pipe, event, database, operation, arguments)


def test_stop_kills_the_worker_even_if_listing_children_hangs(monkeypatch):
    """psutil puede tardar indefinidamente en Windows al enumerar hijos.

    El cierre tiene que matar al trabajador antes de esa consulta. Si no,
    la vista previa se queda en «Cargando» y la interfaz deja de responder.
    """
    from buscador.processes import CONTEXT, stop_process

    def listing_hangs(self, recursive=False):
        time.sleep(8)
        return []

    monkeypatch.setattr(psutil.Process, "children", listing_hangs)
    parent, child = CONTEXT.Pipe()
    process = CONTEXT.Process(target=hanging_reader, args=(child,))
    process.start()
    child.close()
    assert parent.recv() == "ready"
    seen = {}
    original_close = process.close
    def remember_close():
        seen["code"] = process.exitcode
        original_close()
    process.close = remember_close
    started = time.monotonic()
    stop_process(process)
    parent.close()
    assert time.monotonic() - started < 2
    assert seen["code"] is not None


def test_stuck_reader_is_killed_and_next_document_can_be_read(tmp_path):
    path = tmp_path / "documento.pdf"
    path.write_bytes(b"fixture")
    with SafeExtractor(seconds=0.2, target=hanging_reader) as reader:
        start = time.monotonic()
        result = reader.read(path, threading.Event())
        assert result.status == "tiempo"
        assert time.monotonic() - start < 10
        assert reader.process is None
        reader.target = healthy_reader
        assert reader.read(path, threading.Event()).text == "texto recuperado"


def test_cancel_interrupts_a_reader_without_waiting_for_timeout(tmp_path):
    path = tmp_path / "documento.pdf"
    path.write_bytes(b"fixture")
    event = threading.Event()
    timer = threading.Timer(0.8, event.set)
    timer.start()
    try:
        with SafeExtractor(seconds=60, target=hanging_reader) as reader:
            start = time.monotonic()
            assert reader.read(path, event).status == "cancelado"
            assert time.monotonic() - start < 5
    finally:
        timer.cancel()


def test_crashed_reader_becomes_a_file_error(tmp_path):
    path = tmp_path / "documento.pdf"
    path.write_bytes(b"fixture")
    with SafeExtractor(target=crash_reader) as reader:
        assert reader.read(path, threading.Event()).status == "error"


def test_reader_memory_limit(tmp_path):
    path = tmp_path / "documento.pdf"
    path.write_bytes(b"fixture")
    with SafeExtractor(seconds=60, memory=1, target=hanging_reader) as reader:
        assert reader.read(path, threading.Event()).status == "memoria"
        assert reader.process is None


def test_scan_worker_preserves_saved_progress_on_cancel_and_resume(tmp_path, monkeypatch):
    root = tmp_path / "docs"
    root.mkdir()
    for number in range(600):
        (root / f"archivo-{number}.bin").write_bytes(b"binario")
    index = Index(tmp_path / "index.db")
    event = threading.Event()
    seen = []
    def on_progress(report, _path):
        seen.append(report["seen"])
        if report["seen"] >= 100:
            event.set()
    before = {p.pid for p in psutil.Process().children(recursive=True)}
    monkeypatch.setattr("buscador.processes._task_main", controlled_scan_task)
    report = run_task(index.database, "scan", {"root": str(root)}, event, progress=on_progress)
    assert report.cancelled
    assert report.seen < 600
    assert index.count(root) > 0
    saved = index.count(root)
    monkeypatch.undo()
    resumed = run_task(index.database, "scan", {"root": str(root)}, threading.Event())
    assert resumed.unchanged >= saved
    assert index.count(root) == 600
    # multiprocessing's shared resource tracker may stay alive; document readers must not.
    extra = [p for p in psutil.Process().children(recursive=True) if p.pid not in before]
    assert all("resource_tracker" in " ".join(p.cmdline()) for p in extra)
