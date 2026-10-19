"""Carga de datos desde la terminal (usa el mismo ETL que la API).

Ejemplos (desde la carpeta del proyecto):
  docker compose exec api python -m scripts.cargar_datos equipos
  docker compose exec api python -m scripts.cargar_datos partidos --desde 2026-01-01 --hasta 2026-01-07
  docker compose exec api python -m scripts.cargar_datos temporada 2026
  docker compose exec api python -m scripts.cargar_datos recientes
"""
import argparse
import logging
import sys
from datetime import date

from app import ingesta
from app.db import pool


def main() -> int:
    parser = argparse.ArgumentParser(description="Obtiene datos de la NBA desde ESPN y los guarda en PostgreSQL")
    comandos = parser.add_subparsers(dest="comando", required=True)
    comandos.add_parser("equipos", help="Equipos, conferencias y divisiones")
    partidos = comandos.add_parser("partidos", help="Partidos de un rango de fechas")
    partidos.add_argument("--desde", type=date.fromisoformat, required=True, help="AAAA-MM-DD")
    partidos.add_argument("--hasta", type=date.fromisoformat, required=True, help="AAAA-MM-DD")
    temporada = comandos.add_parser("temporada", help="Todos los partidos jugados de una temporada")
    temporada.add_argument("anio", type=int, help="Año en que termina: 2026 = 2025-26")
    comandos.add_parser("recientes", help="Partidos de ayer y hoy")
    argumentos = parser.parse_args()

    if argumentos.comando == "equipos":
        tipo, parametros, tarea = "equipos", {}, ingesta.tarea_equipos()
    elif argumentos.comando == "partidos":
        if argumentos.hasta < argumentos.desde:
            parser.error("--hasta debe ser igual o posterior a --desde")
        tipo = "partidos"
        parametros = {"desde": str(argumentos.desde), "hasta": str(argumentos.hasta)}
        tarea = ingesta.tarea_rango(argumentos.desde, argumentos.hasta)
    elif argumentos.comando == "temporada":
        tipo, parametros = "temporada", {"temporada": argumentos.anio}
        tarea = ingesta.tarea_temporada(argumentos.anio)
    else:
        tipo, parametros, tarea = "automatica", {"dias": "ayer y hoy"}, ingesta.tarea_recientes()

    pool.open(wait=True, timeout=30)
    try:
        resultado = ingesta.ejecutar_sincrono(tipo, parametros, tarea)
    finally:
        pool.close()

    print(f"Ingesta #{resultado['ingesta_id']} ({tipo}): {resultado['estado']}")
    print(f"  Solicitudes a ESPN: {resultado['solicitudes_api']}")
    print(f"  Registros guardados: {resultado['registros_guardados']}")
    print(f"  Detalle: {resultado['mensaje']}")
    return 0 if resultado["estado"] == "completada" else 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sys.exit(main())
