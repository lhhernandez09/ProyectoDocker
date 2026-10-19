# Contenedor API-Ubuntu: FastAPI + scripts de obtención de datos
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# Python del sistema (3.12 en Ubuntu 24.04) y curl para la comprobación de salud
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# Entorno virtual: Ubuntu no permite instalar paquetes con pip en el Python del sistema
RUN python3 -m venv /opt/venv

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts

# Ubuntu 24.04 trae el usuario sin privilegios "ubuntu"
USER ubuntu
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
