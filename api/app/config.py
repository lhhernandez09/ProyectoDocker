"""Configuración leída de variables de entorno (definidas en compose.yaml)."""
import os
from zoneinfo import ZoneInfo

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
DB_NAME = os.environ.get("DB_NAME", "nba")
DB_USER = os.environ.get("DB_USER", "nba_user")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")

# Cada cuántos minutos se sincronizan automáticamente los partidos de ayer y hoy.
# 0 desactiva la sincronización automática.
SINCRONIZACION_MINUTOS = int(os.environ.get("SINCRONIZACION_MINUTOS", "60"))

# Pausa entre solicitudes a ESPN para no saturar el servicio.
PAUSA_ENTRE_SOLICITUDES = float(os.environ.get("PAUSA_ENTRE_SOLICITUDES", "0.2"))

# La NBA organiza su calendario con la hora del Este de EE. UU.
ZONA_NBA = ZoneInfo("America/New_York")


def dsn() -> str:
    return (
        f"host={DB_HOST} port={DB_PORT} dbname={DB_NAME} "
        f"user={DB_USER} password={DB_PASSWORD} connect_timeout=5"
    )
