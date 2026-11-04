# Subtitle Studio

Aplicación local para transcribir, sincronizar, traducir y editar subtítulos de vídeo en Apple Silicon.

## Arquitectura prevista
- **Docker Compose**: frontend, FastAPI, worker, PostgreSQL y Redis.
- **macOS nativo**: inferencia MLX con GPU Metal (Qwen3-ASR y alineador) y Ollama para traducción al español.
- **Procesamiento bajo demanda**: la interfaz permanece disponible; los modelos se cargan al procesar. Ollama usa una retención objetivo de 10 minutos; el trabajador MLX libera recursos al finalizar.
- **Datos locales**: vídeos, resultados, bases de datos, modelos y credenciales no se versionan en Git.

## Estado

Repositorio inicializado. Pendiente de importar el código del MVP y validar ejecución real en Mac Studio M1 Ultra (64 GB).

## Primeros pasos

```bash
mkdir -p ~/Projects
cd ~/Projects
git clone https://github.com/fedeblock/subtitle-studio.git
cd subtitle-studio
```

Una vez importado el MVP, revisar los scripts de instalación y `.env.example` antes de arrancar Docker.

## Flujo de colaboración

1. Trabajar en ramas `feature/*` o `fix/*`.
2. Abrir pull requests para revisar cambios antes de integrar en `main`.
3. Mantener `.env`, material audiovisual y datos de modelos fuera del repositorio.
