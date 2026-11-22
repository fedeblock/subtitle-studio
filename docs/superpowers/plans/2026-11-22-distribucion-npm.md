# Distribución inicial en npm

**Objetivo:** ofrecer una copia instalable del MVP sin incluir datos del usuario. El paquete es un inicializador de archivos, no una aplicación alojada ni un servicio en la nube.

**Alcance:** `npx subtitle-studio init [directorio]` crea un directorio nuevo con los archivos necesarios; nunca sobreescribe uno existente. El usuario ejecuta después los pasos documentados para macOS, Docker, el gateway y los modelos. La instalación no inicia servicios ni descarga modelos automáticamente.

**Validación:** probar creación y protección de directorios, inspeccionar `npm pack`, ejecutar la instalación desde el tarball en una ubicación temporal y comprobar la configuración de Compose sin reutilizar datos. El paquete excluye `.env`, datos, medios, cachés, entornos virtuales y prototipos no auditados.

**Publicación:** comprobar identidad y permisos de npm, subir la rama sin forzar y conservar los antecedentes de Git. La versión inicial se presenta como MVP. La publicación pública en npm requiere autenticación y la verificación que corresponda a la cuenta.
