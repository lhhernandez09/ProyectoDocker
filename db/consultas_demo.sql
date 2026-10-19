-- =====================================================================
-- Consultas para mostrar el almacenamiento durante la demostración.
-- Ejecutar desde la carpeta del proyecto:
--   docker compose exec -T db psql -U nba_user -d nba < db/consultas_demo.sql
-- (Este archivo NO está en db/init, así que no se ejecuta al crear la base.)
-- =====================================================================

\echo '1) Registros por tabla'
SELECT 'equipos' AS tabla, COUNT(*) AS registros FROM equipos
UNION ALL SELECT 'partidos', COUNT(*) FROM partidos
UNION ALL SELECT 'estadisticas_equipo_partido', COUNT(*) FROM estadisticas_equipo_partido
UNION ALL SELECT 'puntos_periodo', COUNT(*) FROM puntos_periodo
UNION ALL SELECT 'ingestas', COUNT(*) FROM ingestas;

\echo '2) Bitácora de las últimas ingestas (ETL)'
SELECT ingesta_id, tipo, estado, solicitudes_api, registros_guardados,
       to_char(iniciada_en, 'YYYY-MM-DD HH24:MI') AS inicio, mensaje
FROM ingestas ORDER BY ingesta_id DESC LIMIT 5;

\echo '3) Últimos 5 partidos guardados'
SELECT p.fecha, v.abreviatura AS visitante, p.puntos_visitante,
       l.abreviatura AS local, p.puntos_local, p.estado, p.nota
FROM partidos p
JOIN equipos l ON l.equipo_id = p.equipo_local_id
JOIN equipos v ON v.equipo_id = p.equipo_visitante_id
ORDER BY p.inicio DESC LIMIT 5;

\echo '4) Top 10 de la temporada regular 2025-26 (vista v_clasificacion)'
SELECT conferencia, abreviatura, ganados, perdidos, pct_victorias,
       puntos_favor_prom, puntos_contra_prom, diferencial_prom
FROM v_clasificacion
WHERE temporada = 2026 AND tipo_temporada = 2
ORDER BY pct_victorias DESC LIMIT 10;

\echo '5) Box score y puntos por cuarto del partido más reciente terminado'
WITH ultimo AS (
    SELECT partido_id FROM partidos WHERE completado ORDER BY inicio DESC LIMIT 1
)
SELECT e.abreviatura, s.rebotes, s.asistencias,
       s.tiros_campo_anotados || '/' || s.tiros_campo_intentados AS tiros_campo,
       s.triples_anotados || '/' || s.triples_intentados AS triples,
       (SELECT string_agg(pp.puntos::text, ' - ' ORDER BY pp.periodo)
        FROM puntos_periodo pp
        WHERE pp.partido_id = s.partido_id AND pp.equipo_id = s.equipo_id) AS por_cuarto
FROM estadisticas_equipo_partido s
JOIN ultimo u ON u.partido_id = s.partido_id
JOIN equipos e ON e.equipo_id = s.equipo_id;

\echo '6) Rachas: mayor número de victorias consecutivas en 2025-26 (funciones de ventana)'
WITH r AS (
    SELECT equipo_id, fecha, partido_id, gano,
           ROW_NUMBER() OVER (PARTITION BY equipo_id ORDER BY fecha, partido_id)
         - ROW_NUMBER() OVER (PARTITION BY equipo_id, gano ORDER BY fecha, partido_id) AS grupo
    FROM v_resultados_equipo
    WHERE temporada = 2026 AND tipo_temporada = 2
)
SELECT e.abreviatura, COUNT(*) AS victorias_seguidas, MIN(r.fecha) AS desde, MAX(r.fecha) AS hasta
FROM r JOIN equipos e ON e.equipo_id = r.equipo_id
WHERE r.gano AND e.es_nba
GROUP BY e.abreviatura, r.equipo_id, r.grupo
ORDER BY victorias_seguidas DESC LIMIT 5;
