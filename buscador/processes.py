"""Procesos cancelables: la interfaz nunca comparte un lector de documentos."""

from __future__ import annotations

import multiprocessing as mp
import os
import threading
import time
from dataclasses import asdict
from pathlib import Path

import psutil

from buscador.extract import Extraction, MAX_FILE_BYTES, TEXT_EXTENSIONS, OFFICE_EXTENSIONS, IMAGE_EXTENSIONS
from buscador.unicode_text import escaped_text, preview_document

CONTEXT = mp.get_context("spawn")
DOCUMENT_SECONDS = 30
OCR_SECONDS = 90
DOCUMENT_MEMORY = 768 * 1024 * 1024


def _collect_children(pid: int, found: list, done: threading.Event) -> None:
    try:
        found.extend(psutil.Process(pid).children(recursive=True))
    except psutil.Error:
        pass
    finally:
        done.set()


def stop_process(process) -> None:
    """Finaliza únicamente este trabajador y sus lectores/OCR descendientes.

    En Windows, enumerar los procesos hijos puede no volver. La consulta corre
    aparte y, si no responde enseguida, el trabajador se termina igual.
    """
    if process is None:
        return
    if not process.is_alive():
        process.join(timeout=0.2)
        process.close()
        return
    pid = process.pid
    descendants: list = []
    listed = threading.Event()
    threading.Thread(target=_collect_children, args=(pid, descendants, listed), daemon=True).start()
    listed.wait(0.25)
    process.terminate()
    process.join(timeout=0.4)
    if process.is_alive():
        process.kill()
        process.join(timeout=0.4)
    listed.wait(0.05)
    for child in reversed(descendants):
        try:
            child.kill()
        except psutil.Error:
            pass
    process.join(timeout=0.2)
    process.close()


def _reader_main(pipe) -> None:
    # Tesseract normally starts many OpenMP threads; leave CPU for the desktop.
    os.environ["OMP_THREAD_LIMIT"] = "1"
    from buscador.extract import extract
    try:
        pipe.send("ready")
        while True:
            path, executable, languages = pipe.recv()
            result = extract(Path(path), threading.Event(), executable, languages)
            pipe.send(result)
    except (EOFError, BrokenPipeError):
        pass
    finally:
        pipe.close()


class SafeExtractor:
    """Reutiliza un lector; lo reemplaza si se atasca, crece o termina mal."""

    def __init__(self, *, seconds=DOCUMENT_SECONDS, ocr_seconds=OCR_SECONDS,
                 memory=DOCUMENT_MEMORY, target=_reader_main):
        self.seconds = seconds
        self.ocr_seconds = ocr_seconds
        self.memory = memory
        self.target = target
        self.process = None
        self.pipe = None
        self.completed = 0

    def close(self):
        if self.process is not None:
            stop_process(self.process)
            self.process = None
        if self.pipe is not None:
            self.pipe.close()
            self.pipe = None
        self.completed = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def _receive(self, seconds, cancelled, heartbeat):
        end = time.monotonic() + seconds
        last_heartbeat = 0.0
        while True:
            if cancelled.is_set():
                self.close()
                return Extraction(status="cancelado", note="Lectura cancelada.")
            if time.monotonic() >= end:
                self.close()
                return Extraction(status="tiempo", note=f"Lectura interrumpida al alcanzar {seconds:g} segundos. Se conserva el nombre; usa Volver a leer todo para reintentar.")
            if self.pipe.poll(0.05):
                return self.pipe.recv()
            if not self.process.is_alive():
                raise EOFError("El lector terminó inesperadamente")
            try:
                process = psutil.Process(self.process.pid)
                used = process.memory_info().rss
                used += sum(child.memory_info().rss for child in process.children(recursive=True))
                if used > self.memory:
                    self.close()
                    return Extraction(status="memoria", note="Se detuvo la lectura al superar el límite de memoria; se conserva el nombre.")
            except psutil.Error:
                pass
            if heartbeat and time.monotonic() - last_heartbeat >= 0.5:
                heartbeat()
                last_heartbeat = time.monotonic()

    def read(self, path, cancelled, executable=None, languages="eng", heartbeat=None):
        supported = TEXT_EXTENSIONS | OFFICE_EXTENSIONS | IMAGE_EXTENSIONS | {".pdf"}
        if path.suffix.lower() not in supported:
            return Extraction()
        if path.stat().st_size > MAX_FILE_BYTES:
            return Extraction(status="limite", note="Supera 40 MiB; se indexó únicamente el nombre.")
        try:
            if self.process is None:
                self.pipe, child = CONTEXT.Pipe()
                self.process = CONTEXT.Process(target=self.target, args=(child,))
                self.process.start()
                child.close()
                ready = self._receive(20, cancelled, heartbeat)
                if ready != "ready":
                    return ready
            self.pipe.send((str(path), executable, languages))
            seconds = self.ocr_seconds if executable and path.suffix.lower() in IMAGE_EXTENSIONS | {".pdf"} else self.seconds
            result = self._receive(seconds, cancelled, heartbeat)
            self.completed += 1
            # Release native decoder caches periodically, including on very long scans.
            if self.completed >= 100:
                self.close()
            return result
        except (EOFError, BrokenPipeError, OSError) as error:
            self.close()
            return Extraction(status="error", note=f"El lector no pudo completar el archivo ({type(error).__name__}).")


def load_preview(database, root, path, image, cancelled):
    """Lee la vista previa en el hilo de trabajo, sin crear otro proceso.

    Abrir un proceso nuevo por cada resultado vuelve a arrancar el ejecutable.
    En Windows ese arranque, y el cierre que enumera procesos, deja la interfaz
    en «Cargando vista previa…» y puede marcar la ventana como no responde.
    """
    if cancelled.is_set():
        return None
    from buscador.engine import Index
    content = preview_document(Index(Path(database), initialize=False).content(root, path, wait_seconds=3))
    if cancelled.is_set():
        return None
    thumbnail = None
    if image:
        import io
        from PIL import Image
        try:
            with Image.open(path) as picture:
                picture.thumbnail((280, 170))
                output = io.BytesIO()
                picture.convert("RGB").save(output, format="PNG")
                thumbnail = output.getvalue()
        except Exception:
            thumbnail = None
    return content, thumbnail


def _task_main(pipe, event, database, operation, arguments):
    from buscador.engine import Index
    try:
        index = Index(Path(database))
        if operation == "scan":
            result = index.scan(**arguments, cancelled=event,
                                progress=lambda report, path: pipe.send(("progress", asdict(report), path)))
        elif operation == "search":
            result = index.search(**arguments, cancelled=event)
        elif operation == "preview":
            result = load_preview(database, arguments["root"], arguments["path"], arguments.get("image", False), event)
        else:
            result = getattr(index, operation)(**arguments)
        pipe.send(("result", result))
    except Exception as error:
        try:
            pipe.send(("error", escaped_text(f"{type(error).__name__}: {error}")))
        except (EOFError, BrokenPipeError):
            pass
    finally:
        pipe.close()


def run_task(database, operation, arguments, cancelled, progress=None, *, timeout=None):
    """Llamado desde un QThread; IPC acotado y cancelación con plazo máximo."""
    from buscador.engine import ScanReport
    if cancelled.is_set():
        return None
    pipe, child = CONTEXT.Pipe()
    event = CONTEXT.Event()
    process = CONTEXT.Process(target=_task_main, args=(child, event, str(database), operation, arguments))
    latest = ScanReport()
    started = time.monotonic()
    requested_stop = None
    process.start()
    child.close()
    try:
        while True:
            now = time.monotonic()
            if cancelled.is_set():
                event.set()
                requested_stop = requested_stop or now
                if now - requested_stop >= 2:
                    latest.cancelled = True
                    return latest if operation == "scan" else None
            if timeout and now - started >= timeout:
                raise TimeoutError("La operación tardó demasiado. Acota la búsqueda o comprueba que la unidad esté disponible.")
            if pipe.poll(0.05):
                try:
                    message = pipe.recv()
                except EOFError:
                    if cancelled.is_set():
                        latest.cancelled = True
                        return latest if operation == "scan" else None
                    raise RuntimeError("El trabajador se cerró inesperadamente. Los lotes guardados del índice se conservan.")
                if message[0] == "progress":
                    latest = ScanReport(**message[1])
                    if progress:
                        progress(message[1], message[2])
                elif message[0] == "error":
                    raise RuntimeError(message[1])
                else:
                    return message[1]
            elif not process.is_alive():
                raise RuntimeError("El trabajador terminó sin devolver un resultado.")
    finally:
        event.set()
        stop_process(process)
        pipe.close()
