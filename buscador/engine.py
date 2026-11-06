"""Índice incremental SQLite FTS5 y búsqueda por palabras aproximadas."""

from __future__ import annotations

import os
import re
import sqlite3
import threading
import time
import unicodedata
import uuid
import logging
from logging.handlers import RotatingFileHandler
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from rapidfuzz import fuzz, process

from buscador.extract import EXTRACTOR_VERSION, Extraction, IMAGE_EXTENSIONS, file_kind, ocr_languages, tesseract_path
from buscador.processes import SafeExtractor
from buscador.unicode_text import clean_text, escaped_text, require_valid_path

TECHNICAL_FOLDERS = {".android", "appdata", ".git", ".cache", "node_modules", ".venv", "venv",
                     "__pycache__", ".gradle", ".npm", ".nuget", ".m2", "$recycle.bin", "system volume information"}


def normalize(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", clean_text(text).casefold()) if not unicodedata.combining(c))


def root_key(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(os.path.expanduser(str(path))))


def words(text: str) -> list[str]:
    return re.findall(r"[^\W_]+", normalize(text), re.UNICODE)


@dataclass
class ScanReport:
    seen: int = 0
    updated: int = 0
    unchanged: int = 0
    removed: int = 0
    errors: int = 0
    partial: int = 0
    name_only: int = 0
    excluded: int = 0
    elapsed: float = 0
    current_seconds: float = 0
    cancelled: bool = False
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SearchResult:
    path: str
    name: str
    kind: str
    size: int
    modified: float
    excerpt: str
    status: str
    note: str
    score: float
    match: str


@dataclass(frozen=True)
class SearchResponse:
    results: list[SearchResult]
    expanded: dict[str, list[str]]
    truncated: bool = False


class Index:
    def __init__(self, database: Path, *, initialize: bool = True):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        if not initialize:
            return
        with closing(self.connect()) as connection, connection:
            if connection.execute("SELECT 1 FROM sqlite_master WHERE name='entries'").fetchone():
                return
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS entries (
                    id INTEGER PRIMARY KEY, root TEXT NOT NULL, path TEXT NOT NULL,
                    name TEXT NOT NULL, name_search TEXT NOT NULL, kind TEXT NOT NULL,
                    size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL,
                    content TEXT NOT NULL, content_search TEXT NOT NULL,
                    status TEXT NOT NULL, note TEXT NOT NULL, signature TEXT NOT NULL,
                    generation TEXT NOT NULL, UNIQUE(root, path)
                );
                CREATE INDEX IF NOT EXISTS entries_root ON entries(root);
                CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(
                    name_search, content_search, content='entries', content_rowid='id',
                    tokenize='unicode61 remove_diacritics 2', prefix='2 3 4'
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS vocabulary USING fts5vocab(search, 'col');
                CREATE TRIGGER IF NOT EXISTS entries_insert AFTER INSERT ON entries BEGIN
                    INSERT INTO search(rowid, name_search, content_search)
                    VALUES (new.id, new.name_search, new.content_search);
                END;
                CREATE TRIGGER IF NOT EXISTS entries_delete AFTER DELETE ON entries BEGIN
                    INSERT INTO search(search, rowid, name_search, content_search)
                    VALUES ('delete', old.id, old.name_search, old.content_search);
                END;
                CREATE TRIGGER IF NOT EXISTS entries_update AFTER UPDATE OF name_search, content_search ON entries BEGIN
                    INSERT INTO search(search, rowid, name_search, content_search)
                    VALUES ('delete', old.id, old.name_search, old.content_search);
                    INSERT INTO search(rowid, name_search, content_search)
                    VALUES (new.id, new.name_search, new.content_search);
                END;
            """)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=15000")
        return connection

    def count(self, root: str | Path) -> int:
        with closing(self.connect()) as connection, connection:
            return connection.execute("SELECT count(*) FROM entries WHERE root=?", (require_valid_path(root_key(root)),)).fetchone()[0]

    def content(self, root: str, path: str, *, wait_seconds: float = 15) -> str:
        connection = sqlite3.connect(self.database, timeout=wait_seconds)
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout={int(wait_seconds * 1000)}")
        try:
            with connection:
                row = connection.execute(
                    "SELECT substr(content,1,60000) FROM entries WHERE root=? AND path=?",
                    (require_valid_path(root_key(root)), require_valid_path(path)),
                ).fetchone()
                return row[0] if row else ""
        finally:
            connection.close()

    def clear(self, root: str) -> None:
        with closing(self.connect()) as connection, connection:
            connection.execute("DELETE FROM entries WHERE root=?", (require_valid_path(root_key(root)),))

    def scan(self, root: str | Path, *, ocr: bool = False, force: bool = False, skip_technical: bool = True,
             cancelled: threading.Event | None = None,
             progress: Callable[[ScanReport, str], None] | None = None) -> ScanReport:
        cancelled = cancelled if cancelled is not None else threading.Event()
        scope = require_valid_path(root_key(root))
        if not Path(scope).is_dir():
            raise ValueError("La ubicación no existe, no es una carpeta o no está disponible.")
        executable = tesseract_path() if ocr else None
        if ocr and not executable:
            raise ValueError("Instala Tesseract OCR y agrégalo al PATH para habilitar el reconocimiento de texto.")
        languages = ocr_languages(executable) if executable else ""
        signature = f"{EXTRACTOR_VERSION}:ocr={bool(executable)}:{languages}"
        generation = uuid.uuid4().hex
        report = ScanReport()
        pending = [Path(scope)]
        inaccessible = False
        last_progress = 0.0
        last_commit = time.monotonic()
        started = time.monotonic()
        current_started = started
        pending_writes = 0
        skipped_folders = set()
        database = root_key(self.database)
        excluded = {database, database + "-wal", database + "-shm", database + "-journal"}
        excluded.update(root_key(self.database.parent / name) for name in ("actividad.log", "actividad.log.1", "actividad.log.2"))

        def warning(message: str) -> None:
            message = escaped_text(message)
            report.errors += 1
            logger.warning(message)
            if len(report.warnings) < 50:
                report.warnings.append(message)

        logger = logging.getLogger(f"buscador.scan.{id(report)}")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        handler = RotatingFileHandler(self.database.parent / "actividad.log", maxBytes=2_000_000, backupCount=2, encoding="utf-8", errors="backslashreplace")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        logger.info("Inicio de actualización: %s; OCR=%s; omitir técnicas=%s", scope, ocr, skip_technical)
        connection = self.connect()
        reader = SafeExtractor()

        def emit(path: str, always=False):
            nonlocal last_progress, last_commit, pending_writes
            now = time.monotonic()
            if pending_writes and (pending_writes >= 100 or now - last_commit >= 0.75):
                connection.commit()
                pending_writes = 0
                last_commit = now
            report.elapsed = now - started
            report.current_seconds = now - current_started
            if progress and (always or now - last_progress >= 0.5):
                progress(report, clean_text(path))
                last_progress = now

        try:
            while pending and not cancelled.is_set():
                folder = pending.pop()
                try:
                    with os.scandir(folder) as entries:
                        for entry in entries:
                            if cancelled.is_set():
                                break
                            path = Path(entry.path)
                            if root_key(path) in excluded:
                                continue
                            try:
                                # Skip an unrepresentable identity; never silently rename it
                                # or alias it to a different filename in the database.
                                try:
                                    str(path).encode("utf-8")
                                except UnicodeEncodeError:
                                    inaccessible = True
                                    report.seen += 1
                                    warning(f"{path}: ruta omitida por caracteres Unicode inválidos; no se modificó el archivo.")
                                    continue
                                # Do not follow links or Windows junctions, avoiding cycles/out-of-scope traversal.
                                if entry.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
                                    continue
                                is_directory = entry.is_dir(follow_symlinks=False)
                                if not is_directory and not entry.is_file(follow_symlinks=False):
                                    continue
                                stat = entry.stat(follow_symlinks=False)
                                skip = is_directory and skip_technical and entry.name.casefold() in TECHNICAL_FOLDERS
                                if skip:
                                    report.excluded += 1
                                    # Preserve previously indexed entries in omitted subtrees. Omitting
                                    # a directory is not evidence that the user's files disappeared.
                                    skipped_folders.add(root_key(path))
                                if is_directory and not skip:
                                    pending.append(path)
                                report.seen += 1
                                current_started = time.monotonic()
                                old = connection.execute(
                                    "SELECT size, mtime_ns, signature, kind, status FROM entries WHERE root=? AND path=?",
                                    (scope, str(path)),
                                ).fetchone()
                                kind = "Carpeta" if is_directory else file_kind(path)
                                relevant_ocr = path.suffix.lower() in IMAGE_EXTENSIONS | {".pdf"}
                                compatible = old and (old[2] == signature or (
                                    old[2].split(":", 1)[0] == str(EXTRACTOR_VERSION)
                                    and (not relevant_ocr or not ocr)))
                                if (not force and old and old[0] == stat.st_size and old[1] == stat.st_mtime_ns
                                        and compatible and old[3] == kind):
                                    connection.execute("UPDATE entries SET generation=? WHERE root=? AND path=?", (generation, scope, str(path)))
                                    report.unchanged += 1
                                else:
                                    emit(str(path))
                                    extraction = Extraction(note="Carpeta; búsqueda por nombre.") if is_directory else reader.read(
                                        path, cancelled, executable, languages, heartbeat=lambda: emit(str(path)))
                                    if cancelled.is_set():
                                        break
                                    connection.execute("""
                                        INSERT INTO entries(root,path,name,name_search,kind,size,mtime_ns,content,content_search,status,note,signature,generation)
                                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                                        ON CONFLICT(root,path) DO UPDATE SET
                                            name=excluded.name, name_search=excluded.name_search, kind=excluded.kind,
                                            size=excluded.size, mtime_ns=excluded.mtime_ns, content=excluded.content,
                                            content_search=excluded.content_search, status=excluded.status,
                                            note=excluded.note, signature=excluded.signature, generation=excluded.generation
                                    """, (scope, str(path), path.name, normalize(path.name), kind, stat.st_size,
                                          stat.st_mtime_ns, extraction.text, normalize(extraction.text), extraction.status,
                                          extraction.note, signature, generation))
                                    report.updated += 1
                                    if extraction.status in {"error", "tiempo", "memoria"}:
                                        warning(f"{path}: {extraction.note}")
                                    elif extraction.status in {"parcial", "limite", "protegido"}:
                                        report.partial += 1
                                        if extraction.status == "parcial":
                                            logger.info("%s: %s", path, extraction.note)
                                    elif extraction.status in {"solo_nombre", "metadatos"} and not is_directory:
                                        report.name_only += 1
                                pending_writes += 1
                                emit(str(path))
                            except (OSError, UnicodeError) as error:
                                inaccessible = True
                                warning(f"{path}: {type(error).__name__}")
                except (OSError, UnicodeError) as error:
                    inaccessible = True
                    warning(f"{folder}: {type(error).__name__}")
            report.cancelled = cancelled.is_set()
            # Only a complete traversal can prove that missing files were deleted.
            if not report.cancelled and not inaccessible:
                # Bounded deletion batches keep cancellation and saved progress available.
                after = 0
                emit("Comprobando entradas antiguas…", always=True)
                while not cancelled.is_set():
                    emit("Comprobando entradas antiguas…")
                    rows = connection.execute("SELECT id,path FROM entries WHERE root=? AND generation<>? AND id>? ORDER BY id LIMIT 500",
                                              (scope, generation, after)).fetchall()
                    if not rows:
                        break
                    after = rows[-1][0]
                    def was_omitted(path):
                        parent = root_key(os.path.dirname(path))
                        while parent != scope:
                            if parent in skipped_folders:
                                return True
                            ancestor = os.path.dirname(parent)
                            if ancestor == parent:
                                break
                            parent = ancestor
                        return False
                    ids = [row[0] for row in rows if not was_omitted(row[1])]
                    if ids:
                        cursor = connection.execute("DELETE FROM entries WHERE id IN (" + ",".join("?" for _ in ids) + ")", ids)
                        report.removed += cursor.rowcount
                    connection.commit()
            if inaccessible:
                report.warnings.append("No se quitaron entradas antiguas: hubo ubicaciones inaccesibles.")
            connection.commit()
            report.cancelled = cancelled.is_set()
            report.elapsed = time.monotonic() - started
            logger.info("Fin: revisadas=%s actualizadas=%s sin cambios=%s errores=%s cancelado=%s", report.seen, report.updated, report.unchanged, report.errors, report.cancelled)
            return report
        finally:
            reader.close()
            connection.close()
            handler.close()
            logger.removeHandler(handler)

    def search(self, root: str | Path, query: str, *, mode: str = "both", kind: str = "Todos",
               extensions: str = "", fuzzy: bool = True, limit: int = 300,
               cancelled: threading.Event | None = None) -> SearchResponse:
        if mode not in {"both", "name", "content"}:
            raise ValueError("Modo de búsqueda desconocido.")
        tokens = list(dict.fromkeys(words(query)))
        if not tokens:
            return SearchResponse([], {})
        if len(tokens) > 12:
            raise ValueError("Usa como máximo 12 palabras por búsqueda.")
        cancelled = cancelled if cancelled is not None else threading.Event()
        scope = require_valid_path(root_key(root))
        column = {"both": "{name_search content_search}", "name": "name_search", "content": "content_search"}[mode]
        expansions: dict[str, list[str]] = {}
        clauses = []
        connection = self.connect()
        connection.set_progress_handler(lambda: int(cancelled.is_set()), 2000)
        try:
            for token in tokens:
                if cancelled.is_set():
                    return SearchResponse([], {})
                alternatives = []
                if fuzzy and len(token) >= 3:
                    # Bound vocabulary work. Names take priority when searching both fields.
                    fields = ["name_search", "content_search"] if mode == "both" else [column]
                    candidates = set()
                    for field_name in fields:
                        cursor = connection.execute(
                            "SELECT term FROM vocabulary WHERE col=? AND length(term) BETWEEN ? AND ? LIMIT 60000",
                            (field_name, max(1, len(token) - 2), len(token) + 2),
                        )
                        candidates.update(row[0] for row in cursor)
                    cutoff = 65 if len(token) <= 4 else 75
                    alternatives = [term for term, _, _ in process.extract(
                        token, sorted(candidates), scorer=fuzz.ratio, score_cutoff=cutoff, limit=7,
                    ) if term != token][:6]
                expansions[token] = alternatives
                exact = '"' + token + '"' + ("*" if len(token) >= 3 else "")
                clauses.append(column + " : (" + " OR ".join([exact] + ['"' + term.replace('"', '""') + '"' for term in alternatives]) + ")")
            expression = " AND ".join(clauses)
            conditions = ["search MATCH ?", "e.root=?"]
            params: list = [expression, scope]
            if kind != "Todos":
                conditions.append("e.kind=?")
                params.append(kind)
            suffixes = [part.lower().lstrip("*.") for part in re.split(r"[,;\s]+", clean_text(extensions).strip()) if part.lstrip("*.")]
            if suffixes:
                conditions.append("(" + " OR ".join("lower(substr(e.name, -?))=?" for _ in suffixes) + ")")
                for suffix in suffixes:
                    params.extend([len(suffix) + 1, "." + suffix])
            params.append(limit + 1)
            rows = connection.execute("""
                SELECT e.path,e.name,e.kind,e.size,e.mtime_ns,e.status,e.note,
                    bm25(search, 8.0, 1.0) AS rank,
                    snippet(search, 1, char(1), char(2), ' … ', 24) AS excerpt
                FROM search JOIN entries e ON e.id=search.rowid
                WHERE """ + " AND ".join(conditions) + " ORDER BY rank, e.name LIMIT ?", params).fetchall()
            results = []
            for row in rows:
                name_words = words(row["name"])
                name_score = sum(max((fuzz.ratio(token, word) for word in name_words), default=0) for token in tokens) / len(tokens)
                name_hit = any(any(word.startswith(token) or word in expansions[token] for word in name_words) for token in tokens)
                content_hit = "\x01" in row["excerpt"]
                match = "Nombre y contenido" if name_hit and content_hit else "Nombre" if name_hit else "Contenido"
                if mode == "content":
                    match = "Contenido"
                elif mode == "name":
                    match = "Nombre"
                results.append(SearchResult(
                    row["path"], row["name"], row["kind"], row["size"], row["mtime_ns"] / 1e9,
                    row["excerpt"].replace("\x01", "[").replace("\x02", "]"),
                    row["status"], row["note"], name_score - row["rank"], match,
                ))
            results.sort(key=lambda item: (-item.score, item.name.casefold(), item.path))
            return SearchResponse(results[:limit], {key: value for key, value in expansions.items() if value}, len(rows) > limit)
        except sqlite3.OperationalError:
            if cancelled.is_set():
                return SearchResponse([], {})
            raise
        finally:
            connection.close()
