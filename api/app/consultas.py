"""Consultas SQL de lectura que alimentan los endpoints de la API."""
from datetime import date

from .db import consultar, consultar_uno


def equipos(solo_nba: bool = True) -> list[dict]:
    return consultar(
        """SELECT e.equipo_id, e.abreviatura, e.nombre, e.nombre_corto, e.ciudad,
                  e.color_primario, e.color_secundario, e.logo_url, e.es_nba,
                  d.nombre AS division, c.abreviatura AS conferencia
           FROM equipos e
           LEFT JOIN divisiones d   ON d.division_id = e.division_id
           LEFT JOIN conferencias c ON c.conferencia_id = d.conferencia_id
           WHERE e.es_nba OR NOT %s
           ORDER BY e.nombre""",
        (solo_nba,),
    )


def temporadas() -> list[dict]:
    return consultar(
        """SELECT p.temporada, p.tipo_temporada, t.nombre AS tipo_nombre,
                  COUNT(*) AS partidos,
                  COUNT(*) FILTER (WHERE p.completado) AS completados,
                  MIN(p.fecha) AS primera_fecha, MAX(p.fecha) AS ultima_fecha
           FROM partidos p
           JOIN tipos_temporada t ON t.tipo_id = p.tipo_temporada
           GROUP BY p.temporada, p.tipo_temporada, t.nombre
           ORDER BY p.temporada DESC, p.tipo_temporada"""
    )


def partidos(temporada: int | None, tipo: int | None, equipo_id: int | None,
             desde: date | None, hasta: date | None, limite: int) -> list[dict]:
    return consultar(
        """SELECT p.partido_id, p.temporada, p.tipo_temporada, t.nombre AS tipo_nombre,
                  p.fecha, p.inicio, p.tipo_partido, p.nota, p.estado, p.completado,
                  p.periodos,
                  p.equipo_local_id, l.abreviatura AS local, l.logo_url AS local_logo,
                  p.equipo_visitante_id, v.abreviatura AS visitante,
                  v.logo_url AS visitante_logo,
                  p.puntos_local, p.puntos_visitante, p.sede, p.ciudad, p.asistencia
           FROM partidos p
           JOIN equipos l         ON l.equipo_id = p.equipo_local_id
           JOIN equipos v         ON v.equipo_id = p.equipo_visitante_id
           JOIN tipos_temporada t ON t.tipo_id = p.tipo_temporada
           WHERE (%(temporada)s::int IS NULL OR p.temporada = %(temporada)s)
             AND (%(tipo)s::int IS NULL OR p.tipo_temporada = %(tipo)s)
             AND (%(equipo)s::int IS NULL
                  OR %(equipo)s IN (p.equipo_local_id, p.equipo_visitante_id))
             AND (%(desde)s::date IS NULL OR p.fecha >= %(desde)s)
             AND (%(hasta)s::date IS NULL OR p.fecha <= %(hasta)s)
           ORDER BY p.inicio DESC
           LIMIT %(limite)s""",
        {"temporada": temporada, "tipo": tipo, "equipo": equipo_id,
         "desde": desde, "hasta": hasta, "limite": limite},
    )


def partido(partido_id: int) -> dict | None:
    detalle = consultar_uno(
        """SELECT p.*, l.nombre AS local, v.nombre AS visitante
           FROM partidos p
           JOIN equipos l ON l.equipo_id = p.equipo_local_id
           JOIN equipos v ON v.equipo_id = p.equipo_visitante_id
           WHERE p.partido_id = %s""",
        (partido_id,),
    )
    if detalle:
        detalle["estadisticas"] = consultar(
            "SELECT * FROM estadisticas_equipo_partido WHERE partido_id = %s", (partido_id,))
        detalle["puntos_por_periodo"] = consultar(
            """SELECT equipo_id, periodo, puntos FROM puntos_periodo
               WHERE partido_id = %s ORDER BY equipo_id, periodo""",
            (partido_id,),
        )
    return detalle


def clasificacion(temporada: int, tipo: int) -> list[dict]:
    filas = consultar(
        """SELECT * FROM v_clasificacion
           WHERE temporada = %s AND tipo_temporada = %s
           ORDER BY pct_victorias DESC, diferencial_prom DESC""",
        (temporada, tipo),
    )
    # Juegos detrás del líder de cada conferencia
    lideres = {}
    for fila in filas:
        lider = lideres.setdefault(fila["conferencia"], fila)
        fila["juegos_detras"] = ((lider["ganados"] - fila["ganados"])
                                 + (fila["perdidos"] - lider["perdidos"])) / 2
    return filas


def resumen(temporada: int, tipo: int) -> dict:
    totales = consultar_uno(
        """SELECT COUNT(*) FILTER (WHERE completado) AS partidos_jugados,
                  COUNT(*) FILTER (WHERE NOT completado) AS partidos_pendientes,
                  ROUND(AVG((puntos_local + puntos_visitante) / 2.0)
                        FILTER (WHERE completado), 1)::float8 AS puntos_por_equipo,
                  COUNT(*) FILTER (WHERE completado AND periodos > 4) AS partidos_con_prorroga
           FROM partidos WHERE temporada = %s AND tipo_temporada = %s""",
        (temporada, tipo),
    )
    totales["partido_mas_anotado"] = consultar_uno(
        """SELECT p.partido_id, p.fecha, l.abreviatura AS local, v.abreviatura AS visitante,
                  p.puntos_local, p.puntos_visitante,
                  p.puntos_local + p.puntos_visitante AS total
           FROM partidos p
           JOIN equipos l ON l.equipo_id = p.equipo_local_id
           JOIN equipos v ON v.equipo_id = p.equipo_visitante_id
           WHERE p.completado AND p.temporada = %s AND p.tipo_temporada = %s
           ORDER BY total DESC LIMIT 1""",
        (temporada, tipo),
    )
    totales["partidos_en_base"] = consultar_uno("SELECT COUNT(*) AS n FROM partidos")["n"]
    totales["ultima_ingesta"] = consultar_uno(
        """SELECT ingesta_id, tipo, finalizada_en FROM ingestas
           WHERE estado = 'completada' ORDER BY finalizada_en DESC LIMIT 1"""
    )
    return totales


def tendencia_equipo(equipo_id: int, temporada: int, tipo: int) -> list[dict]:
    """Partido a partido, con promedio móvil de 10 juegos y récord acumulado."""
    return consultar(
        """SELECT r.partido_id, r.fecha, r.es_local, r.gano,
                  r.puntos_favor, r.puntos_contra,
                  e.abreviatura AS rival,
                  ROUND(AVG(r.puntos_favor) OVER ventana, 1)::float8  AS favor_media_movil,
                  ROUND(AVG(r.puntos_contra) OVER ventana, 1)::float8 AS contra_media_movil,
                  SUM(r.gano::int) OVER acumulado     AS ganados_acum,
                  SUM((NOT r.gano)::int) OVER acumulado AS perdidos_acum
           FROM v_resultados_equipo r
           JOIN equipos e ON e.equipo_id = r.rival_id
           WHERE r.equipo_id = %s AND r.temporada = %s AND r.tipo_temporada = %s
           WINDOW ventana   AS (ORDER BY r.fecha, r.partido_id
                                ROWS BETWEEN 9 PRECEDING AND CURRENT ROW),
                  acumulado AS (ORDER BY r.fecha, r.partido_id)
           ORDER BY r.fecha, r.partido_id""",
        (equipo_id, temporada, tipo),
    )


def puntos_por_periodo(temporada: int, tipo: int, equipo_id: int | None) -> list[dict]:
    """Promedio de puntos por cuarto del equipo y de toda la liga."""
    return consultar(
        """SELECT pp.periodo,
                  ROUND(AVG(pp.puntos) FILTER (WHERE pp.equipo_id = %(equipo)s), 1)::float8
                      AS equipo,
                  ROUND(AVG(pp.puntos), 1)::float8 AS liga
           FROM puntos_periodo pp
           JOIN partidos p ON p.partido_id = pp.partido_id
           WHERE p.completado AND p.temporada = %(temporada)s
             AND p.tipo_temporada = %(tipo)s AND pp.periodo <= 4
           GROUP BY pp.periodo
           ORDER BY pp.periodo""",
        {"temporada": temporada, "tipo": tipo, "equipo": equipo_id},
    )


def ingestas(limite: int) -> list[dict]:
    return consultar(
        "SELECT * FROM ingestas ORDER BY ingesta_id DESC LIMIT %s", (limite,))


def ingesta(ingesta_id: int) -> dict | None:
    return consultar_uno("SELECT * FROM ingestas WHERE ingesta_id = %s", (ingesta_id,))
