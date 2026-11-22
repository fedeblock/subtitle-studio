# Rediseño del flujo — plan de implementación

**Objetivo:** implementar el recorrido completo especificado en `docs/design_handoff_rediseno_flujo/README.md`, conservando datos y funciones actuales.

**Arquitectura:** frontend vanilla existente y API FastAPI; las capacidades nuevas persisten en PostgreSQL o en archivos del proyecto con actualización segura. El gateway macOS mantiene el acceso a medios y modelos nativos. Los cambios de esquema deben ser aditivos y preservar los datos existentes.

**Restricciones:** no introducir React ni bundler; no fabricar señales de audio, progreso ni estimaciones; no copiar vídeos ni borrar datos sin revisión; mantener autosave, deshacer, pausa y recuperación.

1. Auditar prototipo, estado Git, modelos y rutas actuales; definir migraciones aditivas y verificar los flujos existentes.
2. Añadir clasificación de fuentes, metadatos de episodio, exportación bilingüe y recuentos reales, con pruebas de preservación y compatibilidad.
3. Añadir propuestas de mejora y revisión de segmentos, comprobando aceptación, rechazo, conflictos, reversión anterior y pausas.
4. Añadir envolvente de audio, detección fundada de dudosos y progreso por tramos; manejar ausencia de metadatos sin inventar datos.
5. Implementar selección múltiple, lotes, recetas y cola sin copiar medios, con comprobaciones de rutas y recuperación segura.
6. Implementar comparación por rango, aplicación explícita de resultados y comprobaciones de exportación.
7. Construir biblioteca, navegación por etapas, paneles, mapa de voz, lista y filtros; conservar estado y foco al actualizar.
8. Completar foco, comparación, exportación, cola y ajustes; verificar prototipo en tamaños ancho y estrecho.
9. Actualizar documentación, ejecutar pruebas unitarias y de integración factibles y comprobar servicios sin interrumpir trabajos.

**Puntos de revisión:** fuentes de episodios adyacentes; vídeos sin duración; silencios y subtítulos importados; actualizaciones concurrentes y trabajos pausados; rutas, instantáneas y exportaciones existentes.
