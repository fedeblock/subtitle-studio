# Editor con autoguardado y deshacer

> Implementación inline con superpowers:executing-plans; requisito explícito del usuario, sin nueva ronda de aprobación.

**Objetivo:** tabla `# | mark-in | mark-out | sub original (o transcripción) | traducción`; guardar al salir del campo, sin botón por fila, con deshacer.

**Diseño:** conservar API PUT validada y serializar snapshots completos por proyecto desde un controlador de edición. Estado deseado separado del confirmado: respuestas lentas no cambian campos que se estén editando. Historial deshacer/rehacer durante la sesión del proyecto; no persiste al recargar. Campos inválidos permanecen visibles; errores de red conservan la cola y ofrecen reintento global. Indicador accesible del estado de guardado. Mantener reproductor y foco. Se descarta guardar por pulsación porque el usuario pidió cambio de campo; no se precisa migrar BD para un historial de sesión.

- [x] Pruebas de guardado serializado, undo/redo y fallos recuperables.
- [x] Controlador frontend independiente de DOM, integrado con blur y navegación/exportación segura.
- [x] Tabla de cinco columnas, encabezado fijo y controles globales de historial/guardado.
- [x] Suite, build Docker y prueba con proyecto sintético; documentar límites.
