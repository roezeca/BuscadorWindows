BUSCADOR WINDOWS 0.2.2

Corrige la ventana que quedaba en «No responde» al buscar: la vista previa ya no abre otro proceso ni espera a enumerar procesos hijos antes de mostrar el texto. Si la lectura falla, se muestra el error en lugar de quedarse en «Cargando vista previa…».

ACTUALIZAR
1. Cierra la versión anterior. Si no responde, finalízala desde el Administrador de tareas.
2. Abre BuscadorWindows.exe. El título debe decir Buscador 0.2.2.
3. Busca de nuevo sobre el mismo índice. No hace falta borrarlo.

Windows 10/11 de 64 bits. No necesita instalar Python. El ejecutable no está firmado digitalmente.
Verificado bajo Wine: índice, Unicode defectuoso, búsqueda, vista previa, Word/PDF, miniatura y cierre.

BUSCADOR WINDOWS 0.2.1

Corrige UnicodeEncodeError: surrogates not allowed al guardar texto de documentos con codificación defectuosa. Conserva el texto legible y los emojis válidos; reemplaza únicamente las unidades Unicode inválidas por �. Los nombres de archivo ilegibles se omiten con un aviso, sin renombrarlos ni modificar los archivos.

ACTUALIZAR
1. Cierra la versión anterior del buscador.
2. Abre este ejecutable: el título debe decir Buscador 0.2.1.
3. Selecciona la misma ubicación y pulsa Actualizar índice.
4. No borres el índice ni marques Volver a leer todo; se reutilizará lo que ya quedó guardado.

No requiere reinstalar Tesseract ni Python. Windows 10/11 de 64 bits.

Validación: 59 pruebas en Linux; 29 pruebas de extracción y Unicode con Python para Windows bajo Wine. El ejecutable pasó una comprobación que indexa un PDF que antes provocaba exactamente el error Unicode informado. No probado en un equipo Windows físico.

El ejecutable no está firmado digitalmente.
