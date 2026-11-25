# Sincronización global y ubicaciones de modelos

**Objetivo:** ajustar los tiempos de todas las entradas mediante un desplazamiento constante y/o una conversión entre velocidades conocidas, con propuesta reversible; mostrar dónde están los modelos STT descargados.

**Diseño:** la acción global abre una configuración compacta. Los tiempos se transforman como `tiempo × FPS de origen / FPS de destino + desplazamiento`, con las tasas 24000/1001, 30000/1001 y 60000/1001 interpretadas exactamente cuando se eligen los valores habituales. No se infiere la velocidad del SRT ni se supone que toda diferencia de FPS implique cambiar tiempos. La propuesta reutiliza la API transaccional existente; se rechazan tiempos negativos o inválidos, no se modifica el archivo original y se mantiene la recuperación existente de la sesión. La previsualización ocupa el panel de subtítulos para mantener visible el reproductor.

El catálogo nativo publica únicamente las rutas efectivamente reconocidas en la caché de modelos y las muestra en Audio y modelos, con la advertencia de que es compartida. Ollama gestiona los LLM por separado y se indicará claramente en el mismo lugar.

**Pruebas:** cubrir conversión en ambas direcciones, desplazamiento combinado, prevención de tiempos inválidos, previsualización no destructiva, aplicación y recuperación; cubrir la ruta real del catálogo y su presentación. Ejecutar pruebas del frontend y Python y verificar la interfaz en el navegador si el entorno está disponible.

**Resultado y límites:** la interfaz se verificó con un proyecto existente: se previsualizó un desplazamiento y se descartó, y se consultaron las rutas reales de los modelos. Las pruebas automatizadas cubren la fórmula, las tasas fraccionarias, valores inválidos, propuesta, aplicación y deshacer, y el catálogo. Queda pendiente la comprobación integral de conversión y aplicación con medios reales; la reversión de sincronización no persiste entre sesiones.
