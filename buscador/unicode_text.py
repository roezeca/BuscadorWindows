"""Texto Unicode válido para SQLite y Qt, sin alterar rutas de archivos."""

import re

_SURROGATE = re.compile(r"[\ud800-\udfff]")


def clean_text(value: str) -> str:
    """Une pares UTF-16 válidos y reemplaza unidades aisladas por U+FFFD.

    Un lector PDF puede devolver sustitutos UTF-16 dentro de un str de Python.
    No se aplica a identidades de archivos: dos rutas distintas no deben
    convertirse en la misma ruta por reemplazar caracteres.
    """
    if not _SURROGATE.search(value):
        return value
    return value.encode("utf-16-le", errors="surrogatepass").decode("utf-16-le", errors="replace")


def escaped_text(value: str) -> str:
    """Representa nombres ilegibles en el registro sin perder su diagnóstico."""
    return value.encode("utf-8", errors="backslashreplace").decode("utf-8")


_PREVIEW_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\u202a-\u202e\u2066-\u2069]")


def preview_document(value: str, *, limit: int = 60_000, width: int = 240) -> str:
    """Texto seguro para el cuadro de vista previa.

    Una línea de decenas de miles de caracteres, marcas bidireccionales o
    sustitutos UTF-16 sueltos bloquean el maquetado de Qt en el hilo de la
    interfaz. Se conservan los saltos de línea reales y se parten el resto.
    """
    text = _PREVIEW_CONTROL.sub(" ", clean_text(value))[:limit]
    lines = []
    for line in text.splitlines():
        if len(line) <= width:
            lines.append(line)
            continue
        lines.extend(line[offset:offset + width] for offset in range(0, len(line), width))
    return "\n".join(lines)


def require_valid_path(value: str) -> str:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError("La ruta contiene caracteres Unicode inválidos. Elige su carpeta contenedora o renombra esa ubicación.") from error
    return value
