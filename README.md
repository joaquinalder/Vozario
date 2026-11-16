# Vozario

Prototipo web para transcribir videos y audios en la nube. El navegador envía el archivo directo a **Amazon S3** y **Amazon Transcribe** hace el procesamiento. Después podés buscar en el texto, saltar a un momento del video y descargar la transcripción como TXT o SRT.

## Cómo funciona

1. El backend en **FastAPI** crea un registro de trabajo en **SQLite** y devuelve una URL firmada para subir el archivo.
2. El navegador sube el archivo a S3 y muestra el progreso. El backend inicia un trabajo de Amazon Transcribe y consulta su estado.
3. Cuando termina, la interfaz usa los tiempos del resultado para sincronizar el texto con el reproductor. Admite idioma fijo o detección automática y, opcionalmente, separación de hablantes.

## Ejecutar en local

Necesitás Python 3.12. Para transcribir archivos, también necesitás un bucket privado de S3, credenciales de AWS configuradas en tu equipo y permisos para ejecutar Amazon Transcribe. La interfaz y `/health` se pueden abrir sin configurar el bucket.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --env-file .env
```

Abrí [localhost:8000](http://localhost:8000/). Completá `VOZARIO_S3_BUCKET` y `AWS_REGION` en `.env` antes de intentar una transcripción.

### Configurar AWS

- Ajustá el nombre del bucket y los prefijos en [la política IAM de ejemplo](infra/iam-policy.json) para que correspondan a tu entorno.
- Ajustá los orígenes permitidos en [la configuración CORS de ejemplo](infra/s3-cors.json) al origen real de la interfaz y aplicala al bucket.
- Conservá el bucket privado y configurá las credenciales mediante el perfil local de AWS o el rol del servicio. El archivo `.env` se usa para configuración local.

| Variable | Uso |
| --- | --- |
| `AWS_REGION` | Región de S3 y Amazon Transcribe. |
| `VOZARIO_S3_BUCKET` | Bucket para archivos y resultados. |
| `VOZARIO_S3_INPUT_PREFIX` | Prefijo de los archivos subidos. |
| `VOZARIO_S3_OUTPUT_PREFIX` | Prefijo de los resultados de Transcribe. |
| `VOZARIO_SQLITE_PATH` | Ruta al historial local de trabajos. |
| `VOZARIO_MAX_UPLOAD_MB` | Límite de tamaño de la carga. |
| `VOZARIO_PRESIGN_TTL_SECONDS` | Vigencia de las URLs firmadas. |
| `VOZARIO_PUBLIC_BASE_URL` | URL base configurada para el servicio. |

## Pruebas y contenedor

`python -m unittest discover -s tests -v` comprueba el parser de resultados de Transcribe, el formato SRT y la validación de formatos. Estas pruebas se ejecutan sin llamar a AWS.

El [Dockerfile](Dockerfile) empaqueta la aplicación en el puerto 8000. Para conservar el historial entre reemplazos del contenedor, montá almacenamiento persistente y configurá `VOZARIO_SQLITE_PATH` dentro de ese volumen.

El prototipo está pensado para un entorno personal o privado. Antes de exponerlo a varios usuarios, agregá autenticación, aislamiento de trabajos y límites de uso.
