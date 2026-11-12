# Buscador para Windows

Aplicación de escritorio en español para encontrar archivos, imágenes, documentos y carpetas por su nombre o por el texto que contienen. Elige una carpeta, una unidad o una ubicación de red accesible desde Windows. Todo el procesamiento se hace en tu equipo.

## Actualización 0.2.4: ordenar los resultados

Un clic en **Nombre**, **Tipo**, **Tamaño** o **Coincidencia** ordena la lista. Otro clic en la misma columna invierte el orden. El tamaño se ordena por el valor real, no por el texto (2 KB queda antes que 1 MB). La fila elegida sigue siendo el mismo archivo después de ordenar.

## Actualización 0.2.3: barra de progreso al buscar

Mientras la búsqueda corre, debajo del cuadro de texto aparece una barra animada y el estado dice «Buscando…». Al llegar los resultados, o si la búsqueda falla, la barra se oculta. Sigue siendo posible buscar mientras se actualiza el índice: cada tarea tiene su propia barra.

## Actualización 0.2.2: la búsqueda ya no deja la ventana en «No responde»

Al elegir un resultado, la vista previa leía el texto ya guardado en un proceso nuevo y, al terminar, enumeraba todos los procesos hijos antes de cerrarlo. En Windows esa enumeración puede no volver. La interfaz se quedaba en «Cargando vista previa…» y el sistema marcaba la ventana como no responde. La vista previa ahora se lee en el hilo de trabajo, sin arrancar otro proceso, y el cierre de un trabajador lo detiene aunque esa lista no responda. El texto que se muestra parte las líneas enormes y descarta caracteres de control para que Qt no se bloquee al dibujarlo. Si la lectura falla, el mensaje de carga se reemplaza por el error.

Cierra la versión anterior, abre la 0.2.2 y busca de nuevo. No hace falta borrar el índice.

## Actualización 0.2.1: caracteres Unicode defectuosos

Corrige la interrupción `UnicodeEncodeError: surrogates not allowed` al guardar texto que algunos PDF entregan con unidades UTF-16 aisladas. El texto legible se conserva; únicamente las unidades inválidas se reemplazan por `�`, y la vista previa y el registro indican que la lectura fue parcial. Los pares válidos, emojis, acentos y otros alfabetos se conservan.

Los nombres de archivo que no se pueden representar en el índice se omiten con un aviso, sin renombrar ni modificar los archivos ni confundirlos con otra ruta. Si se omite una ruta ilegible, no se purgan entradas antiguas durante ese recorrido incompleto.

Cierra la versión anterior, abre la 0.2.1 y pulsa **Actualizar índice** sobre la misma ubicación. No borres el índice ni marques **Volver a leer todo**: los archivos ya guardados se reutilizan y el documento que antes interrumpía la actualización puede procesarse de nuevo. El formato y la ubicación del índice no cambian.

## Actualización 0.2: recorridos grandes e interrupción

Esta versión conserva la ubicación y el formato del índice de la versión 0.1. Para actualizar, cierra el ejecutable anterior y abre el nuevo, sin borrar el índice. Si la versión anterior quedó bloqueada, finaliza ese proceso desde el Administrador de tareas antes de abrir la actualización. Los lotes ya confirmados por SQLite se conservan; la transacción que estuviera en curso puede deshacerse.

- La indexación, las búsquedas y las vistas previas trabajan en procesos separados de la interfaz. Detener y cerrar solicitan la cancelación y finalizan trabajadores que no respondan.
- Cada documento se lee en un proceso reutilizable, con límites de tiempo y memoria. Una lectura atascada no obliga a detener todo el recorrido: se conserva el nombre, se registra el problema y se continúa.
- **Omitir carpetas técnicas** viene activado. Evita recorrer `AppData`, `.android`, `.git`, `.cache`, `node_modules`, `.venv`, `venv`, `__pycache__`, `.gradle`, `.npm`, `.nuget`, `.m2`, `$Recycle.Bin` y `System Volume Information`. Se registran los nombres de esas carpetas, pero no se entra en ellas. Si seleccionas directamente una de ellas como ubicación, sí se recorre. Puedes desactivar la opción para incluirlas todas.
- Las entradas que ya existían dentro de carpetas omitidas se conservan y siguen siendo buscables; no se consideran archivos eliminados. Actualiza esa carpeta directamente si necesitas refrescarlas.
- Las actualizaciones agrupan escrituras del índice. El estado muestra el archivo actual, el tiempo transcurrido y las carpetas omitidas. **Ver registro de actividad** abre `actividad.log`, junto al índice, con errores y resultados de las actualizaciones. El registro rota para limitar su tamaño.
- Desactivar OCR conserva el texto que ya se había reconocido. Activarlo solo obliga a releer imágenes y PDF que lo necesiten, no archivos de texto ni formatos sin OCR. La opción se recuerda al cerrar.
- Los archivos que agotaron un límite o fallaron no se reintentan si no cambiaron. Marca **Volver a leer todo** para reintentarlos expresamente.

Para un primer recorrido, conviene elegir Documentos, Escritorio, Descargas o la colección que te interesa. El OCR de miles de imágenes puede tardar mucho incluso con una interfaz disponible; no hay una estimación universal de duración.

## Qué puedes hacer

- Buscar nombres incompletos y palabras parecidas: `factrua` encuentra `factura`.
- Buscar sin distinguir mayúsculas ni acentos: `cordoba` encuentra `Córdoba`.
- Combinar palabras en cualquier orden. Todas deben aparecer en el nombre o el contenido, según el modo elegido.
- Buscar por nombre, por contenido o por ambos; filtrar documentos, imágenes, carpetas, audio, video y extensiones.
- Leer una vista previa del texto y de las imágenes; abrir el resultado o su ubicación.
- Actualizar un índice local incremental: relee archivos modificados y retira las entradas de archivos eliminados.
- Detener la actualización y seguir buscando mientras se indexan archivos.
- Activar OCR para encontrar texto visible en imágenes y PDF escaneados.

La similitud es **ortográfica**, no semántica: tolera errores de escritura, pero no interpreta sinónimos, el significado de una fotografía ni descripciones como «foto de un perro». Los nombres de todos los tipos de archivos sí se indexan.

## Usar el ejecutable en Windows

Abre **`BuscadorWindows.exe`** con doble clic en Windows 10/11 de 64 bits. Es un único archivo portable: incluye Python y las bibliotecas necesarias, y no requiere instalar Python ni Microsoft Office. Al iniciar puede tardar unos segundos en preparar sus componentes en una carpeta temporal.

El índice se conserva en los datos locales de tu usuario, aunque muevas el ejecutable. El reconocimiento OCR sigue siendo opcional y requiere instalar Tesseract por separado.

## Ejecutar desde el código fuente en Windows

Requisitos: **Windows 10/11 de 64 bits y Python 3.12 de 64 bits**. Descarga Python desde [python.org](https://www.python.org/downloads/windows/), incluyendo el lanzador `py`.

Abre PowerShell en la carpeta de este proyecto y ejecuta:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m buscador
```

También puedes usar `scripts\ejecutar.ps1`, que realiza esos pasos. La primera instalación necesita Internet para descargar dependencias; después la aplicación funciona sin conexión, salvo para acceder a tus propias carpetas de red.

1. Pulsa **Elegir carpeta…** o escribe una ruta, por ejemplo `D:\Documentos` o `\\servidor\carpeta`.
2. Si necesitas leer imágenes o escaneos, activa **Reconocer texto (OCR)** antes de actualizar.
3. Pulsa **Actualizar índice** y espera a que aparezca el resumen. La primera lectura puede tardar; OCR es bastante más lento.
4. Escribe lo que recuerdas. La búsqueda comienza automáticamente o al pulsar **Buscar**.
5. Selecciona un resultado para ver el texto; usa **Abrir archivo** o **Abrir ubicación**.

Cada ubicación elegida mantiene su propio índice. Si eliges una subcarpeta que no indexaste por separado, primero actualiza su índice. No se vigilan cambios del disco automáticamente: vuelve a pulsar **Actualizar índice** cuando cambien los archivos. **Volver a leer todo** fuerza la extracción, incluso si el tamaño y la fecha no cambiaron.

## Contenido compatible

| Formato | Qué se busca |
| --- | --- |
| TXT, Markdown, CSV, JSON, XML, HTML, código y otros formatos de texto | Texto; UTF-8, UTF-16 con BOM y Windows-1252 |
| PDF | Texto extraíble; OCR opcional en páginas sin texto |
| DOCX | Texto del documento, encabezados, pies y notas |
| XLSX | Cadenas compartidas, celdas y valores almacenados |
| PPTX | Texto de diapositivas y notas |
| ODT, ODS, ODP | Texto almacenado en el documento |
| JPG, PNG, TIFF, BMP, WebP, GIF, ICO | Nombre, metadatos de texto y OCR opcional de la primera imagen/página |
| Carpetas y otros formatos | Nombre |

Los formatos antiguos **DOC, XLS, PPT y RTF** se encuentran por nombre, pero su contenido no se extrae. Puedes convertirlos a DOCX/XLSX/PPTX o texto con tu editor. No se leen documentos protegidos con contraseña, archivos internos de ZIP/RAR ni archivos de nube que no estén disponibles localmente. Los formatos Office se leen sin ejecutar macros y sin necesitar Microsoft Office instalado. El texto de celdas se busca como contenido, no se conserva el diseño de la hoja.

## OCR opcional

Instala Tesseract siguiendo la [documentación de Tesseract para Windows](https://tesseract-ocr.github.io/tessdoc/Installation.html). Instala los datos de idioma **español (`spa`)** y/o **inglés (`eng`)**.

La aplicación busca `tesseract.exe` en `PATH`, `%ProgramFiles%\Tesseract-OCR` y `%LOCALAPPDATA%\Tesseract-OCR`. Para comprobar una instalación en `PATH`:

```powershell
tesseract --list-langs
```

Después activa OCR y actualiza el índice. Se releen los PDF y las imágenes que todavía necesiten OCR; no hace falta borrar el índice. Desactivarlo no borra texto ya reconocido. Tesseract se instala por separado y no se incluye en el ejecutable. La calidad de los resultados depende de la nitidez, orientación e idioma del documento. El OCR no reconoce objetos de las fotografías.

## Crear el programa `.exe`

El ejecutable se genera con **Python y PyInstaller para Windows**, ya sea en Windows o usando esos binarios dentro de Wine. Ejecutar el PyInstaller de Linux directamente produce un programa Linux, no un `.exe`. No hace falta instalar Python en los equipos que reciban la aplicación empaquetada.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.lock
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --onefile --name BuscadorWindows --collect-all pypdfium2 --collect-all pypdfium2_raw launcher.py
```

O ejecuta `scripts\compilar.ps1`, que además abre el ejecutable en modo de comprobación y verifica la interfaz, el índice, la búsqueda aproximada, documentos Word/PDF y miniaturas. El resultado es:

```text
dist\BuscadorWindows.exe
```

Distribuye **este único `.exe`**. No necesita una carpeta `_internal` al lado. El programa no está firmado digitalmente.

El flujo `.github/workflows/windows.yml` instala las dependencias fijadas, ejecuta pruebas, genera el `.exe` y comprueba ese mismo ejecutable antes de publicar un artefacto `BuscadorWindows-x64` en GitHub Actions. Se ejecutará cuando el código esté subido a GitHub o mediante **Run workflow**. Ese artefacto contiene el ejecutable y su informe de verificación; el OCR requiere Tesseract instalado por separado.

La comprobación del paquete también puede iniciarse con `BuscadorWindows.exe --self-test ruta\informe.json`. Utiliza documentos temporales, no lee tus archivos y escribe un informe JSON y una captura. La interfaz de uso normal no requiere parámetros. Se fija Qt/PySide 6.8.3 para mantener una base compatible con Windows 10 y el entorno de compilación Wine.

## Índice local y límites

- El índice se guarda en la ubicación de datos locales del usuario que asigna Qt: normalmente `%LOCALAPPDATA%\BuscadorWindows\BuscadorWindows\indice.sqlite3` en Windows. Contiene rutas, nombres y texto extraído, sin cifrado adicional. No se envían documentos ni búsquedas a servicios externos.
- **Borrar este índice** elimina las entradas de la ubicación seleccionada y conserva los archivos originales. SQLite puede conservar páginas libres en disco hasta compactar la base: esta función no es un borrado seguro.
- No se siguen enlaces simbólicos ni uniones de directorio (junctions), para evitar ciclos y recorrer ubicaciones no elegidas. En Python 3.12 se detectan las junctions de Windows.
- Los permisos siguen siendo los de tu usuario. Las carpetas inaccesibles se informan y no se purgan entradas antiguas si el recorrido quedó incompleto. Una búsqueda puede mostrar entradas anteriores hasta que esa ubicación vuelva a estar disponible.
- Se omite la extracción de contenido para archivos de más de **40 MiB**. Se leen como máximo **1.000.000 de caracteres por archivo**, **300 páginas por PDF**, **20 páginas sin texto por PDF para OCR** y **30 segundos por operación OCR**. Además, el documento completo tiene un límite de **30 segundos sin OCR o 90 segundos con OCR**, y el lector y su OCR se supervisan con un límite conjunto de **768 MiB de memoria residente**. Si se supera un límite, se interrumpe el lector, se registra el problema y se conserva el nombre; no se guarda texto incompleto de esa lectura. La vista previa muestra como máximo 60.000 caracteres; el índice puede contener más.
- Las búsquedas aceptan hasta **12 palabras** y muestran hasta **300 resultados**. Las palabras de al menos tres caracteres también coinciden con prefijos. La búsqueda aproximada añade hasta seis variantes por palabra, sobre un vocabulario limitado a 60.000 términos candidatos por campo; índices muy grandes pueden requerir un término más preciso.
- Detener o cerrar interrumpe lectores atascados. Se da un breve plazo para confirmar las escrituras y, si el trabajador no responde, se termina junto a sus lectores/OCR. Los lotes confirmados se conservan; el lote en curso puede deshacerse. No se modifican archivos originales.
- No es una herramienta forense: no recupera archivos eliminados ni inspecciona el contenido de todos los formatos binarios.

## Desarrollo y validación

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.lock
.venv/bin/python -m pytest -q
.venv/bin/python -m buscador
```

Las pruebas de interfaz usan Qt en modo `offscreen` y no necesitan pantalla. La prueba del OCR real se omite únicamente si Tesseract no está instalado. Las pruebas cubren nombres, errores de escritura, acentos, contenido PDF/Office, filtros, aislamiento de ubicaciones, actualización y eliminación, cancelación, permisos, documentos dañados, límites, vista previa y cierre de los trabajadores.

Las pruebas en Linux validan el motor y la interfaz; las pruebas del `.exe` bajo Wine validan los componentes Windows empaquetados. Ninguna sustituye una comprobación final en un equipo Windows real. Para compilar desde Linux es necesario ejecutar el Python y PyInstaller **de Windows** dentro de Wine.

Estructura principal: `buscador/engine.py` administra el índice y las búsquedas; `buscador/extract.py` extrae texto; `buscador/app.py` contiene la interfaz. Los archivos `requirements*.lock` fijan las versiones y los marcadores de plataforma; se regeneran con `uv pip compile pyproject.toml --universal` y la variante `--extra dev`.
