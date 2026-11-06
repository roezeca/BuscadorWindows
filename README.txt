BUSCADOR WINDOWS 0.2.2

Corrige la ventana que quedaba en «No responde» al buscar: la vista previa ya no abre otro proceso ni espera a enumerar procesos hijos antes de mostrar el texto. Si la lectura falla, se muestra el error en lugar de quedarse en «Cargando vista previa…».

El ejecutable de esta carpeta sigue siendo el 0.2.1 hasta que se vuelva a compilar. El código corregido está en codigo-fuente-0.2.2.zip. Tras compilarlo, el título debe decir Buscador 0.2.2. No hace falta borrar el índice.

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
