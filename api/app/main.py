"""API REST del proyecto NBA Analytics.

- Expone los datos almacenados en PostgreSQL para el dashboard (Dash).
- Permite lanzar la obtención de datos desde la API de ESPN (ETL).
- Documentación interactiva en /docs (Swagger UI).
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import date

from fastapi import FastAPI, HTTPException, Query, status
from pydantic import BaseModel, Field, model_validator

from . import config, consultas, ingesta
from .db import consultar_uno, pool

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("api")


# ---------------------------------------------------------------------------
# Arranque y sincronización automática
# ---------------------------------------------------------------------------

async def sincronizacion_periodica():
    """Cada N minutos descarga los partidos de ayer y hoy."""
    while True:
        await asyncio.sleep(config.SINCRONIZACION_MINUTOS * 60)
        try:
            await asyncio.to_thread(
                ingesta.lanzar_en_segundo_plano, "automatica",
                {"dias": "ayer y hoy"}, ingesta.tarea_recientes(),
            )
        except ingesta.IngestaEnCurso:
            log.info("Sincronización automática omitida: hay otra ingesta en curso")
        except Exception:
            log.exception("Falló la sincronización automática")


@asynccontextmanager
async def ciclo_de_vida(_: FastAPI):
    pool.open(wait=True, timeout=60)
    ingesta.marcar_interrumpidas()
    # En el primer arranque se descarga el catálogo de equipos.
    if consultar_uno("SELECT COUNT(*) AS n FROM equipos WHERE es_nba")["n"] == 0:
        ingesta.lanzar_en_segundo_plano("equipos", {"origen": "arranque"},
                                        ingesta.tarea_equipos())
    tarea = None
    if config.SINCRONIZACION_MINUTOS > 0:
        tarea = asyncio.create_task(sincronizacion_periodica())
    yield
    if tarea:
        tarea.cancel()
    pool.close()


app = FastAPI(
    title="NBA Analytics API",
    description=(
        "Obtiene partidos y equipos de la NBA desde la API pública de ESPN, "
        "los guarda en PostgreSQL y los expone para el dashboard."
    ),
    version="1.0.0",
    lifespan=ciclo_de_vida,
)


# ---------------------------------------------------------------------------
# Salud
# ---------------------------------------------------------------------------

@app.get("/salud", tags=["Salud"], summary="Comprueba la API y la conexión a PostgreSQL")
def salud():
    fila = consultar_uno("SELECT version() AS version, now() AS hora")
    return {"estado": "ok", "postgres": fila["version"].split(",")[0], "hora_bd": fila["hora"]}


# ---------------------------------------------------------------------------
# Consulta de datos almacenados
# ---------------------------------------------------------------------------

@app.get("/equipos", tags=["Datos"], summary="Catálogo de equipos")
def listar_equipos(solo_nba: bool = True):
    return consultas.equipos(solo_nba)


@app.get("/temporadas", tags=["Datos"],
         summary="Temporadas y tipos de temporada con partidos almacenados")
def listar_temporadas():
    return consultas.temporadas()


@app.get("/partidos", tags=["Datos"], summary="Partidos almacenados (más recientes primero)")
def listar_partidos(
    temporada: int | None = Query(None, description="Año en que termina: 2026 = 2025-26"),
    tipo: int | None = Query(None, description="1 Pretemporada, 2 Regular, 3 Playoffs, 5 Play-In"),
    equipo_id: int | None = None,
    desde: date | None = None,
    hasta: date | None = None,
    limite: int = Query(50, ge=1, le=2000),
):
    return consultas.partidos(temporada, tipo, equipo_id, desde, hasta, limite)


@app.get("/partidos/{partido_id}", tags=["Datos"],
         summary="Detalle de un partido con box score y puntos por cuarto")
def detalle_partido(partido_id: int):
    detalle = consultas.partido(partido_id)
    if not detalle:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Partido no encontrado")
    return detalle


# ---------------------------------------------------------------------------
# Estadísticas (alimentan las gráficas del dashboard)
# ---------------------------------------------------------------------------

@app.get("/estadisticas/resumen", tags=["Estadísticas"], summary="Indicadores generales")
def resumen(temporada: int, tipo: int = 2):
    return consultas.resumen(temporada, tipo)


@app.get("/estadisticas/clasificacion", tags=["Estadísticas"],
         summary="Clasificación y promedios por equipo")
def clasificacion(temporada: int, tipo: int = 2):
    return consultas.clasificacion(temporada, tipo)


@app.get("/estadisticas/equipos/{equipo_id}/tendencia", tags=["Estadísticas"],
         summary="Puntos a favor y en contra partido a partido")
def tendencia(equipo_id: int, temporada: int, tipo: int = 2):
    return consultas.tendencia_equipo(equipo_id, temporada, tipo)


@app.get("/estadisticas/puntos-por-periodo", tags=["Estadísticas"],
         summary="Promedio de puntos por cuarto (equipo vs. liga)")
def puntos_por_periodo(temporada: int, tipo: int = 2, equipo_id: int | None = None):
    return consultas.puntos_por_periodo(temporada, tipo, equipo_id)


# ---------------------------------------------------------------------------
# Obtención de datos desde ESPN (ETL)
# ---------------------------------------------------------------------------

class RangoFechas(BaseModel):
    desde: date = Field(examples=["2026-01-01"])
    hasta: date = Field(examples=["2026-01-07"])

    @model_validator(mode="after")
    def validar(self):
        if self.hasta < self.desde:
            raise ValueError("'hasta' debe ser igual o posterior a 'desde'")
        if (self.hasta - self.desde).days > 366:
            raise ValueError("El rango no puede superar 366 días")
        return self


class Temporada(BaseModel):
    temporada: int = Field(ge=2002, le=2100, examples=[2026],
                           description="Año en que termina la temporada: 2026 = 2025-26")


def _lanzar(tipo: str, parametros: dict, tarea) -> dict:
    try:
        ingesta_id = ingesta.lanzar_en_segundo_plano(tipo, parametros, tarea)
    except ingesta.IngestaEnCurso:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Ya hay una ingesta en curso; espera a que termine.")
    return {"ingesta_id": ingesta_id, "estado": "en_proceso"}


@app.post("/ingestas/equipos", tags=["Ingesta (ETL)"], status_code=status.HTTP_202_ACCEPTED,
          summary="Descarga equipos, conferencias y divisiones")
def ingestar_equipos():
    return _lanzar("equipos", {}, ingesta.tarea_equipos())


@app.post("/ingestas/partidos", tags=["Ingesta (ETL)"], status_code=status.HTTP_202_ACCEPTED,
          summary="Descarga los partidos de un rango de fechas")
def ingestar_partidos(rango: RangoFechas):
    return _lanzar("partidos", rango.model_dump(mode="json"),
                   ingesta.tarea_rango(rango.desde, rango.hasta))


@app.post("/ingestas/temporada", tags=["Ingesta (ETL)"], status_code=status.HTTP_202_ACCEPTED,
          summary="Descarga todos los partidos jugados de una temporada")
def ingestar_temporada(datos: Temporada):
    return _lanzar("temporada", datos.model_dump(), ingesta.tarea_temporada(datos.temporada))


@app.get("/ingestas", tags=["Ingesta (ETL)"], summary="Historial de ingestas")
def listar_ingestas(limite: int = Query(10, ge=1, le=100)):
    return consultas.ingestas(limite)


@app.get("/ingestas/{ingesta_id}", tags=["Ingesta (ETL)"], summary="Estado de una ingesta")
def estado_ingesta(ingesta_id: int):
    fila = consultas.ingesta(ingesta_id)
    if not fila:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ingesta no encontrada")
    return fila
