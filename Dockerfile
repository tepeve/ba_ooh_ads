# Usamos una imagen base ligera de Python 3.11
FROM python:3.11-slim-bookworm

# 1. Instalar dependencias del sistema operativo necesarias
# (curl/git a veces son necesarios, libsqlite3 viene por defecto pero aseguramos)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    unrar-free \
    gdal-bin \
    && rm -rf /var/lib/apt/lists/*

# 2. Copiar el binario de uv desde la imagen oficial (Truco Pro)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# 3. Configurar entorno
WORKDIR /app
# Habilitar bytecode compilation para arranque más rápido
ENV UV_COMPILE_BYTECODE=1
# Usar el sistema de caché de uv en una ubicación controlada
ENV UV_CACHE_DIR=/opt/uv-cache/

# 4. Instalar dependencias de Python
# Copiamos solo los archivos de definición primero para aprovechar el caché de capas de Docker
COPY pyproject.toml uv.lock ./

# Instalamos las dependencias en el entorno del sistema (--system) o creando un venv.
# En Docker, usar --system suele ser más simple, pero uv recomienda sync.
# Usaremos 'uv sync' creando un venv en /app/.venv que añadiremos al PATH.
RUN uv sync --frozen --no-cache

# Agregar el entorno virtual al PATH para que 'python' sea el del venv
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src:/app"


# 5. Copiar el código fuente
COPY src/ ./src/
COPY app/ ./app/

RUN pip install -e .
# Nota: No copiamos 'data/' aquí porque lo montaremos como volumen en docker-compose

# 6. Exponer puerto de Shiny
EXPOSE 8000

# 8. Comando por defecto: Levantar la App
CMD ["shiny", "run", "--host", "0.0.0.0", "--port", "8000", "app/app.py"]