# Vozario Web

Vozario Web es la version en la nube para transcribir videos viejos en computadoras con pocos recursos. El navegador sube el archivo directo a Amazon S3 con progreso visible, el backend inicia Amazon Transcribe y la interfaz muestra el texto con tiempos para buscar y saltar al video.

## Que incluye

- Subida directa a S3 con porcentaje real.
- Procesamiento batch con Amazon Transcribe.
- Deteccion automatica de idioma o idioma fijo.
- Opcion para separar voces.
- Biblioteca local de trabajos en SQLite.
- Reproductor web con transcripcion sincronizada.
- Busqueda dentro de la transcripcion.
- Descarga en TXT y SRT.
- Dockerfile listo para subir a AWS App Runner, ECS o Elastic Beanstalk con Docker.

## Configuracion local

1. Crea un bucket S3.
2. Copia `.env.example` a `.env`.
3. Completa `VOZARIO_S3_BUCKET` y `AWS_REGION`.
4. Instala dependencias:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

5. Ejecuta:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

La web queda en `http://localhost:8000`.

## CORS del bucket

Para que el navegador pueda subir directo a S3, aplica `infra/s3-cors.json` al bucket. Cambia `AllowedOrigins` por tu dominio real cuando lo subas.

```powershell
aws s3api put-bucket-cors --bucket TU_BUCKET --cors-configuration file://infra/s3-cors.json
```

## Permisos IAM

El backend necesita permisos de S3 y Amazon Transcribe. Usa `infra/iam-policy.json` como base y reemplaza `REEMPLAZAR_BUCKET` por el nombre real del bucket.

En produccion conviene usar un rol IAM del servicio donde corra la app. Para pruebas locales tambien sirven credenciales configuradas con `aws configure`.

## Subir a AWS

Camino recomendado: AWS App Runner con Docker.

1. Sube este repositorio a GitHub o a ECR.
2. Crea un servicio de App Runner desde el `Dockerfile`.
3. Agrega estas variables de entorno:

```text
AWS_REGION=us-east-1
VOZARIO_S3_BUCKET=tu-bucket-vozario
VOZARIO_S3_INPUT_PREFIX=uploads
VOZARIO_S3_OUTPUT_PREFIX=transcripts
VOZARIO_PUBLIC_BASE_URL=https://tu-dominio
VOZARIO_SQLITE_PATH=/app/data/vozario_web.sqlite3
```

4. Asigna al servicio un rol con la politica de `infra/iam-policy.json`.
5. Actualiza el CORS del bucket para permitir el dominio de App Runner.

Nota: SQLite alcanza para empezar. Si muchas personas van a usarlo a la vez o queres no perder historial al redeployar, el siguiente paso es cambiar SQLite por RDS/PostgreSQL.

## Variables

| Variable | Uso |
| --- | --- |
| `AWS_REGION` | Region de S3 y Amazon Transcribe. |
| `VOZARIO_S3_BUCKET` | Bucket donde se guardan videos y transcripciones. |
| `VOZARIO_S3_INPUT_PREFIX` | Carpeta S3 para archivos subidos. |
| `VOZARIO_S3_OUTPUT_PREFIX` | Carpeta S3 para JSON/SRT/VTT generados. |
| `VOZARIO_SQLITE_PATH` | Base local de trabajos. |
| `VOZARIO_MAX_UPLOAD_MB` | Limite de tamano aceptado por la web. |
| `VOZARIO_PRESIGN_TTL_SECONDS` | Duracion de URLs firmadas. |

## Seguridad

No subas `.env` a Git. El bucket debe ser privado. La web usa URLs firmadas para subir y reproducir archivos sin hacerlos publicos.

