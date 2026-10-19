"""Cliente de la API pública de ESPN (fuente externa de datos).

Endpoints utilizados (no requieren API key):
  - /site/v2/sports/basketball/nba/teams                → equipos
  - /v2/sports/basketball/nba/standings?level=3         → conferencias y divisiones
  - /site/v2/sports/basketball/nba/scoreboard?dates=... → partidos de un día / calendario
"""
import logging
import time
from datetime import date

import httpx

from . import config

log = logging.getLogger(__name__)

URL_BASE = "https://site.api.espn.com/apis"
LIGA = "sports/basketball/nba"

_cliente = httpx.Client(
    timeout=httpx.Timeout(20.0),
    headers={"User-Agent": "nba-analytics-escolar/1.0"},
    follow_redirects=True,
)


def _get(ruta: str, parametros: dict | None = None, intentos: int = 3) -> dict:
    """GET con reintentos ante errores de red o respuestas 5xx."""
    url = f"{URL_BASE}/{ruta}"
    for intento in range(1, intentos + 1):
        try:
            respuesta = _cliente.get(url, params=parametros)
            if respuesta.status_code < 500:
                respuesta.raise_for_status()
                return respuesta.json()
            log.warning("ESPN respondió %s en %s", respuesta.status_code, url)
        except httpx.TransportError as error:
            log.warning("Error de red con ESPN (%s/%s): %s", intento, intentos, error)
        time.sleep(intento * 1.5)
    raise RuntimeError(f"No se pudo obtener {url} después de {intentos} intentos")


def obtener_equipos() -> list[dict]:
    datos = _get(f"site/v2/{LIGA}/teams")
    return [item["team"] for item in datos["sports"][0]["leagues"][0]["teams"]]


def obtener_estructura_liga() -> dict:
    """Árbol liga → conferencias → divisiones → equipos."""
    return _get(f"v2/{LIGA}/standings", {"level": 3})


def obtener_marcador(dia: date) -> dict:
    """Todos los partidos de un día (fecha del calendario de EE. UU.)."""
    return _get(f"site/v2/{LIGA}/scoreboard", {"dates": dia.strftime("%Y%m%d")})


def obtener_calendario(temporada: int) -> list[date]:
    """Días con partidos de una temporada (2026 = temporada 2025-26)."""
    datos = _get(f"site/v2/{LIGA}/scoreboard", {"dates": temporada})
    calendario = datos["leagues"][0].get("calendar", [])
    # Formato: "2025-10-21T07:00Z"; los primeros 10 caracteres son la fecha.
    return sorted({date.fromisoformat(dia[:10]) for dia in calendario if isinstance(dia, str)})
