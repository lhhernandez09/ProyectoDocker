-- =====================================================================
-- Vistas analíticas: la API las consulta para alimentar el dashboard.
-- =====================================================================

-- Un renglón por equipo y partido terminado (cada partido aparece dos
-- veces: desde la perspectiva del local y desde la del visitante).
CREATE VIEW v_resultados_equipo AS
WITH lados AS (
    SELECT partido_id, temporada, tipo_temporada, tipo_partido, fecha,
           equipo_local_id     AS equipo_id,
           equipo_visitante_id AS rival_id,
           TRUE                AS es_local,
           puntos_local        AS puntos_favor,
           puntos_visitante    AS puntos_contra
    FROM partidos
    WHERE completado
    UNION ALL
    SELECT partido_id, temporada, tipo_temporada, tipo_partido, fecha,
           equipo_visitante_id,
           equipo_local_id,
           FALSE,
           puntos_visitante,
           puntos_local
    FROM partidos
    WHERE completado
)
SELECT l.*,
       l.puntos_favor > l.puntos_contra AS gano,
       s.rebotes,
       s.asistencias,
       s.tiros_campo_anotados,
       s.tiros_campo_intentados,
       s.triples_anotados,
       s.triples_intentados,
       s.tiros_libres_anotados,
       s.tiros_libres_intentados
FROM lados l
LEFT JOIN estadisticas_equipo_partido s USING (partido_id, equipo_id);

-- Clasificación y promedios por temporada, tipo de temporada y equipo.
-- La final de la NBA Cup (tipo_partido = 'CC') no cuenta en la clasificación oficial.
CREATE VIEW v_clasificacion AS
SELECT r.temporada,
       r.tipo_temporada,
       r.equipo_id,
       e.abreviatura,
       e.nombre,
       e.logo_url,
       c.abreviatura AS conferencia,
       d.nombre      AS division,
       COUNT(*)                                     AS partidos,
       COUNT(*) FILTER (WHERE r.gano)               AS ganados,
       COUNT(*) FILTER (WHERE NOT r.gano)           AS perdidos,
       ROUND(AVG(r.gano::int), 3)::float8           AS pct_victorias,
       ROUND(AVG(r.puntos_favor), 1)::float8        AS puntos_favor_prom,
       ROUND(AVG(r.puntos_contra), 1)::float8       AS puntos_contra_prom,
       ROUND(AVG(r.puntos_favor - r.puntos_contra), 1)::float8 AS diferencial_prom,
       COUNT(*) FILTER (WHERE r.gano AND r.es_local)         AS ganados_local,
       COUNT(*) FILTER (WHERE NOT r.gano AND r.es_local)     AS perdidos_local,
       COUNT(*) FILTER (WHERE r.gano AND NOT r.es_local)     AS ganados_visita,
       COUNT(*) FILTER (WHERE NOT r.gano AND NOT r.es_local) AS perdidos_visita,
       ROUND(100.0 * SUM(r.tiros_campo_anotados)
             / NULLIF(SUM(r.tiros_campo_intentados), 0), 1)::float8  AS pct_tiros_campo,
       ROUND(100.0 * SUM(r.triples_anotados)
             / NULLIF(SUM(r.triples_intentados), 0), 1)::float8      AS pct_triples,
       ROUND(100.0 * SUM(r.tiros_libres_anotados)
             / NULLIF(SUM(r.tiros_libres_intentados), 0), 1)::float8 AS pct_tiros_libres,
       ROUND(AVG(r.rebotes), 1)::float8     AS rebotes_prom,
       ROUND(AVG(r.asistencias), 1)::float8 AS asistencias_prom
FROM v_resultados_equipo r
JOIN equipos e          ON e.equipo_id = r.equipo_id
LEFT JOIN divisiones d  ON d.division_id = e.division_id
LEFT JOIN conferencias c ON c.conferencia_id = d.conferencia_id
WHERE e.es_nba
  AND r.tipo_partido IS DISTINCT FROM 'CC'
GROUP BY r.temporada, r.tipo_temporada, r.equipo_id,
         e.abreviatura, e.nombre, e.logo_url, c.abreviatura, d.nombre;
