"""Proceso ETL: extrae datos de ESPN, los transforma y los carga en PostgreSQL.

Cada ejecución queda registrada en la tabla `ingestas` con su avance, de modo
que el dashboard puede mostrar el progreso mientras se descargan los datos.
"""
import logging
import threading
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta

from psycopg.types.json import Jsonb

from . import config, espn
from .db import consultar_uno, pool

log = logging.getLogger(__name__)

CONFERENCIAS = {
    "East": ("Conferencia Este", "Este"),
    "West": ("Conferencia Oeste", "Oeste"),
}
DIVISIONES = {
    "Atlantic": "Atlántico",
    "Central": "Central",
    "Southeast": "Sureste",
    "Northwest": "Noroeste",
    "Pacific": "Pacífico",
    "Southwest": "Suroeste",
}
# Nombre de la estadística en ESPN → columna en estadisticas_equipo_partido
ESTADISTICAS = {
    "rebounds": "rebotes",
    "assists": "asistencias",
    "fieldGoalsMade": "tiros_campo_anotados",
    "fieldGoalsAttempted": "tiros_campo_intentados",
    "threePointFieldGoalsMade": "triples_anotados",
    "threePointFieldGoalsAttempted": "triples_intentados",
    "freeThrowsMade": "tiros_libres_anotados",
    "freeThrowsAttempted": "tiros_libres_intentados",
}


# ---------------------------------------------------------------------------
# Bitácora de ingestas
# ---------------------------------------------------------------------------

class Progreso:
    """Lleva la cuenta del avance de una ingesta y lo guarda en la base."""

    def __init__(self, ingesta_id: int):
        self.ingesta_id = ingesta_id
        self.dias_total = 0
        self.dias_procesados = 0
        self.solicitudes_api = 0
        self.registros_guardados = 0
        self.mensaje: str | None = None

    def guardar(self):
        with pool.connection() as conexion:
            conexion.execute(
                """UPDATE ingestas
                   SET dias_total = %s, dias_procesados = %s,
                       solicitudes_api = %s, registros_guardados = %s
                   WHERE ingesta_id = %s""",
                (self.dias_total, self.dias_procesados, self.solicitudes_api,
                 self.registros_guardados, self.ingesta_id),
            )

    def finalizar(self, estado: str, mensaje: str | None):
        self.guardar()
        with pool.connection() as conexion:
            conexion.execute(
                """UPDATE ingestas SET estado = %s, mensaje = %s, finalizada_en = now()
                   WHERE ingesta_id = %s""",
                (estado, mensaje, self.ingesta_id),
            )


def crear_ingesta(tipo: str, parametros: dict) -> int:
    with pool.connection() as conexion:
        fila = conexion.execute(
            "INSERT INTO ingestas (tipo, parametros) VALUES (%s, %s) RETURNING ingesta_id",
            (tipo, Jsonb(parametros)),
        ).fetchone()
    return fila["ingesta_id"]


def marcar_interrumpidas():
    """Al reiniciar la API, las ingestas que quedaron a medias se marcan como error."""
    with pool.connection() as conexion:
        conexion.execute(
            """UPDATE ingestas
               SET estado = 'error', mensaje = 'Interrumpida por reinicio de la API',
                   finalizada_en = now()
               WHERE estado = 'en_proceso'"""
        )


# ---------------------------------------------------------------------------
# Ejecución (en segundo plano para la API, síncrona para los scripts)
# ---------------------------------------------------------------------------

Tarea = Callable[[Progreso], None]
_candado = threading.Lock()


class IngestaEnCurso(Exception):
    """Ya hay otra ingesta ejecutándose."""


def _ejecutar(ingesta_id: int, tarea: Tarea):
    progreso = Progreso(ingesta_id)
    try:
        tarea(progreso)
        progreso.finalizar("completada", progreso.mensaje)
        log.info("Ingesta %s completada: %s", ingesta_id, progreso.mensaje)
    except Exception as error:
        log.exception("Ingesta %s falló", ingesta_id)
        progreso.finalizar("error", str(error))


def lanzar_en_segundo_plano(tipo: str, parametros: dict, tarea: Tarea) -> int:
    if not _candado.acquire(blocking=False):
        raise IngestaEnCurso()
    try:
        ingesta_id = crear_ingesta(tipo, parametros)
    except Exception:
        _candado.release()
        raise

    def trabajo():
        try:
            _ejecutar(ingesta_id, tarea)
        finally:
            _candado.release()

    threading.Thread(target=trabajo, name=f"ingesta-{ingesta_id}", daemon=True).start()
    return ingesta_id


def ejecutar_sincrono(tipo: str, parametros: dict, tarea: Tarea) -> dict:
    ingesta_id = crear_ingesta(tipo, parametros)
    _ejecutar(ingesta_id, tarea)
    return consultar_uno("SELECT * FROM ingestas WHERE ingesta_id = %s", (ingesta_id,))


# ---------------------------------------------------------------------------
# Equipos, conferencias y divisiones
# ---------------------------------------------------------------------------

def cargar_equipos(progreso: Progreso):
    # Extracción
    equipos = espn.obtener_equipos()
    estructura = espn.obtener_estructura_liga()
    progreso.solicitudes_api += 2

    # Transformación
    conferencias, divisiones, division_de_equipo = [], [], {}
    for conferencia in estructura.get("children", []):
        conferencia_id = int(conferencia["id"])
        abreviatura = conferencia.get("abbreviation", "")
        nombre, corto = CONFERENCIAS.get(abreviatura, (conferencia["name"], abreviatura))
        conferencias.append((conferencia_id, nombre, corto))
        for division in conferencia.get("children", []):
            division_id = int(division["id"])
            divisiones.append((division_id, conferencia_id,
                               DIVISIONES.get(division["name"], division["name"]),
                               division.get("abbreviation", "")))
            for entrada in division.get("standings", {}).get("entries", []):
                division_de_equipo[int(entrada["team"]["id"])] = division_id

    filas_equipos = []
    for equipo in equipos:
        equipo_id = int(equipo["id"])
        logos = equipo.get("logos") or [{}]
        filas_equipos.append((
            equipo_id, equipo["abbreviation"], equipo["displayName"],
            equipo.get("shortDisplayName"), equipo.get("location"),
            equipo.get("color"), equipo.get("alternateColor"), logos[0].get("href"),
            division_de_equipo.get(equipo_id),
        ))

    # Carga
    with pool.connection() as conexion, conexion.cursor() as cursor:
        cursor.executemany(
            """INSERT INTO conferencias (conferencia_id, nombre, abreviatura)
               VALUES (%s, %s, %s)
               ON CONFLICT (conferencia_id) DO UPDATE
               SET nombre = EXCLUDED.nombre, abreviatura = EXCLUDED.abreviatura""",
            conferencias,
        )
        cursor.executemany(
            """INSERT INTO divisiones (division_id, conferencia_id, nombre, abreviatura)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (division_id) DO UPDATE
               SET conferencia_id = EXCLUDED.conferencia_id, nombre = EXCLUDED.nombre,
                   abreviatura = EXCLUDED.abreviatura""",
            divisiones,
        )
        cursor.executemany(
            """INSERT INTO equipos (equipo_id, abreviatura, nombre, nombre_corto, ciudad,
                                    color_primario, color_secundario, logo_url,
                                    division_id, es_nba)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE)
               ON CONFLICT (equipo_id) DO UPDATE
               SET abreviatura = EXCLUDED.abreviatura, nombre = EXCLUDED.nombre,
                   nombre_corto = EXCLUDED.nombre_corto, ciudad = EXCLUDED.ciudad,
                   color_primario = EXCLUDED.color_primario,
                   color_secundario = EXCLUDED.color_secundario,
                   logo_url = EXCLUDED.logo_url, division_id = EXCLUDED.division_id,
                   es_nba = TRUE, actualizado_en = now()""",
            filas_equipos,
        )

    progreso.registros_guardados += len(filas_equipos)
    progreso.mensaje = (f"{len(filas_equipos)} equipos, {len(conferencias)} conferencias "
                        f"y {len(divisiones)} divisiones")


def _asegurar_equipos(progreso: Progreso):
    """Los partidos necesitan el catálogo de equipos; se carga si está vacío."""
    fila = consultar_uno("SELECT COUNT(*) AS n FROM equipos WHERE es_nba")
    if fila["n"] == 0:
        cargar_equipos(progreso)


# ---------------------------------------------------------------------------
# Partidos
# ---------------------------------------------------------------------------

def _entero(valor) -> int | None:
    try:
        return int(float(valor))
    except (TypeError, ValueError):
        return None


def _equipo_basico(equipo: dict) -> tuple:
    """Datos mínimos de un equipo tal como vienen dentro de un partido."""
    return (
        int(equipo["id"]), equipo.get("abbreviation") or "?",
        equipo.get("displayName") or equipo.get("name") or "Desconocido",
        equipo.get("shortDisplayName"), equipo.get("location"),
        equipo.get("color"), equipo.get("alternateColor"), equipo.get("logo"),
    )


def transformar_evento(evento: dict, dia: date) -> dict | None:
    """Convierte un evento del scoreboard de ESPN en filas para nuestras tablas."""
    competencia = evento["competitions"][0]
    competidores = {c.get("homeAway"): c for c in competencia["competitors"]}
    if "home" not in competidores or "away" not in competidores:
        return None
    local, visitante = competidores["home"], competidores["away"]

    estado = competencia.get("status") or evento["status"]
    tipo_estado = estado["type"]
    iniciado = tipo_estado.get("state") in ("in", "post")
    temporada = evento["season"]
    sede = competencia.get("venue") or {}
    partido_id = int(evento["id"])

    partido = {
        "partido_id": partido_id,
        "temporada": temporada["year"],
        "tipo_temporada": temporada["type"],
        "fecha": dia,
        "inicio": datetime.fromisoformat(evento["date"]),
        "tipo_partido": (competencia.get("type") or {}).get("abbreviation"),
        "nota": next((n.get("headline") for n in competencia.get("notes", [])
                      if n.get("headline")), None),
        "estado": tipo_estado["name"],
        "completado": bool(tipo_estado.get("completed")),
        "equipo_local_id": int(local["team"]["id"]),
        "equipo_visitante_id": int(visitante["team"]["id"]),
        "puntos_local": _entero(local.get("score")) if iniciado else None,
        "puntos_visitante": _entero(visitante.get("score")) if iniciado else None,
        "periodos": estado.get("period") or None,
        "sede": sede.get("fullName"),
        "ciudad": (sede.get("address") or {}).get("city"),
        "asistencia": competencia.get("attendance") or None,
        "sitio_neutral": bool(competencia.get("neutralSite")),
    }

    estadisticas, periodos = [], []
    if iniciado:
        for competidor in (local, visitante):
            equipo_id = int(competidor["team"]["id"])
            valores = {s.get("name"): s.get("displayValue")
                       for s in competidor.get("statistics", [])}
            estadisticas.append({
                "partido_id": partido_id, "equipo_id": equipo_id,
                **{columna: _entero(valores.get(nombre))
                   for nombre, columna in ESTADISTICAS.items()},
            })
            for numero, cuarto in enumerate(competidor.get("linescores", []), start=1):
                puntos = _entero(cuarto.get("value"))
                if puntos is not None:
                    periodos.append((partido_id, equipo_id,
                                     cuarto.get("period", numero), puntos))

    return {
        "partido": partido,
        "tipo_temporada": (temporada["type"], temporada.get("slug") or "Otro"),
        "equipos": [_equipo_basico(c["team"]) for c in (local, visitante)],
        "estadisticas": estadisticas,
        "periodos": periodos,
    }


def guardar_partidos(lote: list[dict]):
    """Inserta o actualiza (upsert) los partidos de un día en una sola transacción."""
    columnas_estadisticas = ", ".join(ESTADISTICAS.values())
    marcadores = ", ".join(f"%({c})s" for c in ESTADISTICAS.values())
    actualizacion = ", ".join(f"{c} = EXCLUDED.{c}" for c in ESTADISTICAS.values())

    with pool.connection() as conexion, conexion.cursor() as cursor:
        cursor.executemany(
            """INSERT INTO tipos_temporada (tipo_id, nombre) VALUES (%s, %s)
               ON CONFLICT (tipo_id) DO NOTHING""",
            list({item["tipo_temporada"] for item in lote}),
        )
        # Equipos que no están en el catálogo (p. ej. rivales internacionales de pretemporada)
        cursor.executemany(
            """INSERT INTO equipos (equipo_id, abreviatura, nombre, nombre_corto, ciudad,
                                    color_primario, color_secundario, logo_url)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (equipo_id) DO NOTHING""",
            [equipo for item in lote for equipo in item["equipos"]],
        )
        cursor.executemany(
            """INSERT INTO partidos (partido_id, temporada, tipo_temporada, fecha, inicio,
                                     tipo_partido, nota, estado, completado,
                                     equipo_local_id, equipo_visitante_id,
                                     puntos_local, puntos_visitante, periodos, sede, ciudad,
                                     asistencia, sitio_neutral)
               VALUES (%(partido_id)s, %(temporada)s, %(tipo_temporada)s, %(fecha)s,
                       %(inicio)s, %(tipo_partido)s, %(nota)s, %(estado)s, %(completado)s,
                       %(equipo_local_id)s,
                       %(equipo_visitante_id)s, %(puntos_local)s, %(puntos_visitante)s,
                       %(periodos)s, %(sede)s, %(ciudad)s, %(asistencia)s, %(sitio_neutral)s)
               ON CONFLICT (partido_id) DO UPDATE
               SET temporada = EXCLUDED.temporada, tipo_temporada = EXCLUDED.tipo_temporada,
                   fecha = EXCLUDED.fecha, inicio = EXCLUDED.inicio,
                   tipo_partido = EXCLUDED.tipo_partido, nota = EXCLUDED.nota,
                   estado = EXCLUDED.estado, completado = EXCLUDED.completado,
                   puntos_local = EXCLUDED.puntos_local,
                   puntos_visitante = EXCLUDED.puntos_visitante,
                   periodos = EXCLUDED.periodos, sede = EXCLUDED.sede,
                   ciudad = EXCLUDED.ciudad, asistencia = EXCLUDED.asistencia,
                   sitio_neutral = EXCLUDED.sitio_neutral, actualizado_en = now()""",
            [item["partido"] for item in lote],
        )
        estadisticas = [fila for item in lote for fila in item["estadisticas"]]
        if estadisticas:
            cursor.executemany(
                f"""INSERT INTO estadisticas_equipo_partido
                        (partido_id, equipo_id, {columnas_estadisticas})
                    VALUES (%(partido_id)s, %(equipo_id)s, {marcadores})
                    ON CONFLICT (partido_id, equipo_id) DO UPDATE SET {actualizacion}""",
                estadisticas,
            )
        periodos = [fila for item in lote for fila in item["periodos"]]
        if periodos:
            cursor.executemany(
                """INSERT INTO puntos_periodo (partido_id, equipo_id, periodo, puntos)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (partido_id, equipo_id, periodo) DO UPDATE
                   SET puntos = EXCLUDED.puntos""",
                periodos,
            )


def cargar_dias(dias: list[date], progreso: Progreso):
    """Descarga y guarda los partidos de cada día de la lista."""
    _asegurar_equipos(progreso)
    progreso.dias_total = len(dias)
    progreso.guardar()
    partidos = 0
    for dia in dias:
        datos = espn.obtener_marcador(dia)
        progreso.solicitudes_api += 1
        lote = []
        for evento in datos.get("events", []):
            try:
                transformado = transformar_evento(evento, dia)
            except (KeyError, TypeError, ValueError) as error:
                log.warning("Evento %s omitido: %r", evento.get("id"), error)
                continue
            if transformado:
                lote.append(transformado)
        if lote:
            guardar_partidos(lote)
        partidos += len(lote)
        progreso.registros_guardados += len(lote)
        progreso.dias_procesados += 1
        progreso.guardar()
        time.sleep(config.PAUSA_ENTRE_SOLICITUDES)
    progreso.mensaje = f"{partidos} partidos guardados de {len(dias)} días consultados"


# ---------------------------------------------------------------------------
# Tareas listas para ejecutarse
# ---------------------------------------------------------------------------

def hoy_nba() -> date:
    return datetime.now(config.ZONA_NBA).date()


def tarea_equipos() -> Tarea:
    return cargar_equipos


def tarea_rango(desde: date, hasta: date) -> Tarea:
    dias = [desde + timedelta(days=n) for n in range((hasta - desde).days + 1)]
    return lambda progreso: cargar_dias(dias, progreso)


def tarea_temporada(temporada: int) -> Tarea:
    def tarea(progreso: Progreso):
        calendario = espn.obtener_calendario(temporada)
        progreso.solicitudes_api += 1
        dias = [dia for dia in calendario if dia <= hoy_nba()]
        if not dias:
            raise RuntimeError(f"La temporada {temporada} no tiene días con partidos jugados")
        cargar_dias(dias, progreso)
    return tarea


def tarea_recientes() -> Tarea:
    """Ayer y hoy: suficiente para capturar resultados nuevos y partidos en vivo."""
    hoy = hoy_nba()
    return tarea_rango(hoy - timedelta(days=1), hoy)
