"""Dashboard NBA Analytics (Contenedor Python-Dash).

Consulta la API FastAPI (no se conecta directamente a PostgreSQL) y muestra la
información almacenada mediante gráficas interactivas. Desde aquí también se
puede lanzar la obtención de datos desde la API de ESPN.
"""
import logging
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import requests
from dash import Dash, Input, Output, State, ctx, dcc, html, no_update

API_URL = os.environ.get("API_URL", "http://localhost:8000").rstrip("/")
ZONA = ZoneInfo(os.environ.get("ZONA_HORARIA", "America/Mexico_City"))

app = Dash(__name__, title="NBA Analytics")
server = app.server
log = logging.getLogger("dash")

# Paleta: tinta y superficies neutras + colores de serie probados para daltonismo
SUPERFICIE = "#fcfcfb"
TINTA = "#0b0b0b"
TINTA_2 = "#52514e"
TENUE = "#898781"
REJILLA = "#e1e0d9"
BASE = "#c3c2b7"
AZUL = "#2a78d6"      # serie 1 / polo positivo
NARANJA = "#eb6834"   # serie 2
ROJO = "#e34948"      # polo negativo
GRIS = "#c3c2b7"      # contexto (promedio de la liga)
FUENTE = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif'

CONFIG_GRAFICA = {"displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d"]}
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
CUARTOS = {1: "1.er cuarto", 2: "2.º cuarto", 3: "3.er cuarto", 4: "4.º cuarto"}
ESTADOS_PARTIDO = {"STATUS_POSTPONED": "Pospuesto", "STATUS_CANCELED": "Cancelado",
                   "STATUS_SUSPENDED": "Suspendido"}
TIPOS_INGESTA = {"equipos": "Equipos", "partidos": "Rango de fechas",
                 "temporada": "Temporada", "automatica": "Automática"}

sesion = requests.Session()


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def api_get(ruta: str, **parametros):
    respuesta = sesion.get(f"{API_URL}{ruta}", timeout=15,
                           params={k: v for k, v in parametros.items() if v is not None})
    respuesta.raise_for_status()
    return respuesta.json()


def etiqueta_temporada(anio: int) -> str:
    return f"{anio - 1}-{str(anio)[-2:]}"


def fecha_corta(valor, con_anio: bool = True) -> str:
    dia = date.fromisoformat(str(valor)[:10])
    return f"{dia.day} {MESES[dia.month - 1]}" + (f" {dia.year}" if con_anio else "")


def fecha_hora(valor) -> str:
    if not valor:
        return "—"
    momento = datetime.fromisoformat(valor).astimezone(ZONA)
    return f"{momento.day} {MESES[momento.month - 1]}, {momento:%H:%M}"


def temporada_completa_mas_reciente(hoy: date) -> int:
    """Las temporadas terminan en junio: a partir de julio la del año en curso está completa."""
    return hoy.year if hoy.month >= 7 else hoy.year - 1


def estilo(fig: go.Figure, alto: int, **layout) -> go.Figure:
    base = dict(
        height=alto,
        margin=dict(l=56, r=24, t=40, b=48),
        template="none",
        paper_bgcolor=SUPERFICIE,
        plot_bgcolor=SUPERFICIE,
        font=dict(family=FUENTE, size=12, color=TINTA_2),
        hoverlabel=dict(bgcolor="white", bordercolor=REJILLA,
                        font=dict(family=FUENTE, size=12, color=TINTA)),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                    font=dict(color=TINTA_2)),
    )
    fig.update_layout(**(base | layout))
    ejes = dict(gridcolor=REJILLA, linecolor=BASE, zerolinecolor=BASE,
                tickfont=dict(color=TENUE), title_font=dict(color=TINTA_2))
    fig.update_xaxes(**ejes)
    fig.update_yaxes(**ejes)
    return fig


def figura_vacia(mensaje: str, alto: int = 320) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=mensaje, showarrow=False, xref="paper", yref="paper",
                       x=0.5, y=0.5, font=dict(size=14, color=TENUE))
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return estilo(fig, alto)


def aviso(texto: str):
    return html.P(texto, className="aviso")


def tarjeta(titulo: str, hijos: list, subtitulo: str | None = None, clase: str = ""):
    encabezado = [html.H3(titulo)]
    if subtitulo:
        encabezado.append(html.P(subtitulo))
    return html.Section([html.Header(encabezado, className="tarjeta-encabezado"), *hijos],
                        className=f"tarjeta {clase}".strip())


def logo(url: str | None, tamano: int = 20):
    if not url:
        return html.Span(className="logo-vacio", style={"width": tamano, "height": tamano})
    return html.Img(src=url, alt="", className="logo", style={"width": tamano, "height": tamano})


# ---------------------------------------------------------------------------
# Diseño de la página
# ---------------------------------------------------------------------------

def construir_layout():
    hoy = datetime.now(ZONA).date()
    completa = temporada_completa_mas_reciente(hoy)
    opciones_carga = [
        {"label": etiqueta_temporada(a) + (" (en curso)" if a > completa else ""), "value": a}
        for a in range(completa + 1, completa - 4, -1)
    ]
    flujo = ["API de ESPN", "FastAPI · Ubuntu", "PostgreSQL", "Dash"]
    pasos = []
    for i, paso in enumerate(flujo):
        if i:
            pasos.append(html.Span("→", className="flecha"))
        pasos.append(html.Span(paso, className="paso"))

    return html.Div([
        html.Header([
            html.Div([
                html.H1("NBA Analytics"),
                html.P("Rendimiento de los equipos de la NBA a partir de datos públicos de ESPN"),
            ]),
            html.Div(pasos, className="flujo"),
        ], className="cabecera"),

        html.Main([
            tarjeta("Obtención de datos", [
                html.Div([
                    html.Div([
                        html.Label("Partidos por rango de fechas", htmlFor="rango"),
                        html.Div([
                            dcc.DatePickerRange(
                                id="rango", start_date=hoy - timedelta(days=6), end_date=hoy,
                                max_date_allowed=hoy, display_format="DD/MM/YYYY",
                                first_day_of_week=1, minimum_nights=0,
                            ),
                            html.Button("Obtener partidos", id="btn-rango",
                                        className="boton primario"),
                        ], className="fila-control"),
                    ], className="control-grupo"),
                    html.Div([
                        html.Label("Temporada completa", htmlFor="temporada-carga"),
                        html.Div([
                            dcc.Dropdown(id="temporada-carga", options=opciones_carga,
                                         value=completa, clearable=False, searchable=False,
                                         className="selector-corto"),
                            html.Button("Cargar temporada", id="btn-temporada", className="boton"),
                        ], className="fila-control"),
                    ], className="control-grupo"),
                    html.Div([
                        html.Label("Catálogo"),
                        html.Div(html.Button("Actualizar equipos", id="btn-equipos",
                                             className="boton"), className="fila-control"),
                    ], className="control-grupo"),
                ], className="controles-ingesta"),
                html.Div(id="mensaje-ingesta"),
                html.Div(id="progreso-ingesta"),
                html.Div(id="historial-ingestas"),
            ], subtitulo="La API (FastAPI) consulta ESPN, transforma la respuesta y la guarda "
                         "en PostgreSQL. Cada ejecución queda registrada en la tabla «ingestas»."),

            html.Div([
                html.Div([html.Label("Temporada", htmlFor="filtro-temporada"),
                          dcc.Dropdown(id="filtro-temporada", clearable=False,
                                       placeholder="Sin datos")], className="filtro"),
                html.Div([html.Label("Fase", htmlFor="filtro-tipo"),
                          dcc.Dropdown(id="filtro-tipo", clearable=False,
                                       placeholder="Sin datos")], className="filtro"),
                html.Div([html.Label("Equipo", htmlFor="filtro-equipo"),
                          dcc.Dropdown(id="filtro-equipo", clearable=False,
                                       placeholder="Sin equipos")], className="filtro ancho"),
            ], className="filtros"),

            dcc.Loading(html.Div(id="kpis", className="kpis"), type="dot", color=AZUL,
                        delay_show=400),

            html.Div([
                tarjeta("Ofensiva vs. defensiva",
                        [dcc.Graph(id="graf-ofensiva", config=CONFIG_GRAFICA)],
                        subtitulo="Promedio de puntos anotados y permitidos por partido. "
                                  "El eje vertical está invertido: arriba, mejor defensa."),
                tarjeta("Diferencial de puntos",
                        [dcc.Graph(id="graf-diferencial", config=CONFIG_GRAFICA)],
                        subtitulo="Puntos anotados menos permitidos, promedio por partido."),
            ], className="rejilla-2 rejilla-3-2"),

            tarjeta("Clasificación", [
                html.Div([html.Div(id="tabla-este"), html.Div(id="tabla-oeste")],
                         className="rejilla-2 tablas"),
                html.P([html.Span(className="marca playoff"), "Playoffs directos (1-6)",
                        html.Span(className="marca playin"), "Play-In (7-10)"],
                       className="leyenda-tabla"),
            ], subtitulo="Calculada en PostgreSQL (vista v_clasificacion) con los partidos almacenados."),

            html.Div(id="encabezado-equipo", className="encabezado-equipo"),

            tarjeta("Puntos por partido", [dcc.Graph(id="graf-tendencia", config=CONFIG_GRAFICA)],
                    subtitulo="Cada punto es un partido; las líneas son la media móvil de "
                              "10 partidos calculada en SQL con funciones de ventana."),

            html.Div([
                tarjeta("Puntos por cuarto", [dcc.Graph(id="graf-cuartos", config=CONFIG_GRAFICA)],
                        subtitulo="Promedio del equipo frente al promedio de la liga."),
                tarjeta("Últimos partidos", [html.Div(id="tabla-partidos")]),
            ], className="rejilla-2"),
        ]),

        html.Footer("Prototipo académico · Datos: API pública de ESPN · "
                    "Docker Compose: db (PostgreSQL) + api (FastAPI/Ubuntu) + dash (Python-Dash)"),

        dcc.Store(id="datos-temporadas"),
        dcc.Store(id="datos-equipos"),
        dcc.Store(id="version-datos"),
        dcc.Interval(id="reloj-ingesta", interval=3_000),
    ], className="pagina")


app.layout = construir_layout


# ---------------------------------------------------------------------------
# Obtención de datos: lanzar ingestas y seguir su avance
# ---------------------------------------------------------------------------

@app.callback(
    Output("mensaje-ingesta", "children"),
    Input("btn-rango", "n_clicks"), Input("btn-temporada", "n_clicks"),
    Input("btn-equipos", "n_clicks"),
    State("rango", "start_date"), State("rango", "end_date"), State("temporada-carga", "value"),
    prevent_initial_call=True,
)
def lanzar_ingesta(_, __, ___, desde, hasta, temporada):
    if ctx.triggered_id == "btn-rango":
        ruta, datos = "/ingestas/partidos", {"desde": desde, "hasta": hasta}
    elif ctx.triggered_id == "btn-temporada":
        ruta, datos = "/ingestas/temporada", {"temporada": temporada}
    else:
        ruta, datos = "/ingestas/equipos", {}
    try:
        respuesta = sesion.post(f"{API_URL}{ruta}", json=datos, timeout=15)
    except requests.RequestException:
        return html.P("No se pudo contactar a la API.", className="mensaje error")
    if respuesta.status_code == 202:
        return html.P(f"Ingesta #{respuesta.json()['ingesta_id']} iniciada: "
                      f"POST {ruta}", className="mensaje ok")
    detalle = respuesta.json().get("detail", respuesta.text)
    if isinstance(detalle, list):  # errores de validación de FastAPI
        detalle = "; ".join(d.get("msg", "") for d in detalle)
    return html.P(f"La API respondió {respuesta.status_code}: {detalle}", className="mensaje error")


def chip_estado(estado: str):
    textos = {"completada": ("✓", "Completada"), "en_proceso": ("●", "En proceso"),
              "error": ("✕", "Error")}
    icono, texto = textos.get(estado, ("•", estado))
    return html.Span([html.Span(icono, className="icono"), texto], className=f"chip {estado}")


def describir_parametros(parametros: dict) -> str:
    if "desde" in parametros:
        return f"{fecha_corta(parametros['desde'])} → {fecha_corta(parametros['hasta'])}"
    if "temporada" in parametros:
        return etiqueta_temporada(int(parametros["temporada"]))
    return ", ".join(f"{k}: {v}" for k, v in parametros.items()) or "—"


def tabla_ingestas(filas: list[dict]):
    encabezado = html.Thead(html.Tr([
        html.Th(t, className="num" if t in ("#", "Solicitudes", "Registros") else None)
        for t in ("#", "Tipo", "Parámetros", "Estado", "Solicitudes", "Registros",
                  "Inicio", "Detalle")]))
    cuerpo = []
    for fila in filas:
        cuerpo.append(html.Tr([
            html.Td(fila["ingesta_id"], className="num"),
            html.Td(TIPOS_INGESTA.get(fila["tipo"], fila["tipo"])),
            html.Td(describir_parametros(fila["parametros"] or {}), className="secundario"),
            html.Td(chip_estado(fila["estado"])),
            html.Td(fila["solicitudes_api"], className="num"),
            html.Td(fila["registros_guardados"], className="num"),
            html.Td(fecha_hora(fila["iniciada_en"]), className="secundario"),
            html.Td(fila["mensaje"] or "—", className="secundario detalle"),
        ]))
    return html.Div(html.Table([encabezado, html.Tbody(cuerpo)], className="tabla compacta"),
                    className="tabla-contenedor")


@app.callback(
    Output("progreso-ingesta", "children"), Output("historial-ingestas", "children"),
    Output("version-datos", "data"),
    Output("btn-rango", "disabled"), Output("btn-temporada", "disabled"),
    Output("btn-equipos", "disabled"),
    Input("reloj-ingesta", "n_intervals"), State("version-datos", "data"),
)
def monitorear_ingestas(_, version):
    try:
        filas = api_get("/ingestas", limite=6)
    except requests.RequestException:
        return aviso("Esperando a la API…"), no_update, no_update, True, True, True

    en_curso = next((f for f in filas if f["estado"] == "en_proceso"), None)
    progreso = None
    if en_curso:
        total = en_curso["dias_total"] or 0
        hechos = en_curso["dias_procesados"]
        porcentaje = round(100 * hechos / total) if total else 5
        progreso = html.Div([
            html.Div([
                html.Strong(f"Ingesta #{en_curso['ingesta_id']} en proceso"),
                html.Span(f"Día {hechos} de {total} · {en_curso['registros_guardados']} "
                          f"registros guardados · {en_curso['solicitudes_api']} solicitudes a ESPN"
                          if total else "Preparando…"),
            ], className="progreso-texto"),
            html.Div(html.Div(className="progreso-relleno", style={"width": f"{porcentaje}%"}),
                     className="progreso-barra", role="progressbar",
                     **{"aria-valuenow": porcentaje, "aria-valuemin": 0, "aria-valuemax": 100}),
        ], className="progreso")

    historial = tabla_ingestas(filas) if filas else aviso("Todavía no se ha ejecutado ninguna ingesta.")

    # La "versión" de los datos es el id de la última ingesta completada. Al cambiar
    # (o en la primera consulta, cuando aún es None) se recargan filtros y gráficas.
    ultima = max((f["ingesta_id"] for f in filas if f["estado"] == "completada"), default=0)
    nueva_version = ultima if ultima != version else no_update
    ocupado = en_curso is not None
    return progreso, historial, nueva_version, ocupado, ocupado, ocupado


# ---------------------------------------------------------------------------
# Filtros
# ---------------------------------------------------------------------------

@app.callback(
    Output("datos-temporadas", "data"), Output("filtro-temporada", "options"),
    Output("filtro-temporada", "value"),
    Input("version-datos", "data"), State("filtro-temporada", "value"),
)
def cargar_temporadas(_, actual):
    try:
        filas = api_get("/temporadas")
    except requests.RequestException:
        return no_update, no_update, no_update
    anios = sorted({f["temporada"] for f in filas}, reverse=True)
    opciones = [{"label": etiqueta_temporada(a), "value": a} for a in anios]
    if actual in anios:
        return filas, opciones, no_update
    # Por defecto: la temporada más reciente con partidos de temporada regular terminados
    regulares = [f["temporada"] for f in filas
                 if f["tipo_temporada"] == 2 and f["completados"] > 0]
    valor = max(regulares) if regulares else (anios[0] if anios else None)
    return filas, opciones, valor


@app.callback(
    Output("filtro-tipo", "options"), Output("filtro-tipo", "value"),
    Input("datos-temporadas", "data"), Input("filtro-temporada", "value"),
    State("filtro-tipo", "value"),
)
def cargar_tipos(filas, temporada, actual):
    filas = [f for f in (filas or []) if f["temporada"] == temporada and f["completados"] > 0]
    opciones = [{"label": f"{f['tipo_nombre']} ({f['completados']} partidos)",
                 "value": f["tipo_temporada"]} for f in filas]
    tipos = [f["tipo_temporada"] for f in filas]
    if actual in tipos:
        return opciones, no_update
    return opciones, (2 if 2 in tipos else (tipos[0] if tipos else None))


@app.callback(
    Output("datos-equipos", "data"), Output("filtro-equipo", "options"),
    Output("filtro-equipo", "value"),
    Input("version-datos", "data"), State("filtro-equipo", "value"),
)
def cargar_equipos(_, actual):
    try:
        equipos = api_get("/equipos")
    except requests.RequestException:
        return no_update, no_update, no_update
    opciones = [{"label": e["nombre"], "value": e["equipo_id"]} for e in equipos]
    ids = [e["equipo_id"] for e in equipos]
    valor = no_update if actual in ids else (ids[0] if ids else None)
    return {str(e["equipo_id"]): e for e in equipos}, opciones, valor


# ---------------------------------------------------------------------------
# Vista de liga: indicadores, gráficas y clasificación
# ---------------------------------------------------------------------------

def kpi(etiqueta: str, valor, detalle: str | None = None):
    return html.Div([
        html.Span(etiqueta, className="kpi-etiqueta"),
        html.Span(valor, className="kpi-valor"),
        html.Span(detalle or "", className="kpi-detalle"),
    ], className="kpi")


def construir_kpis(resumen: dict, clasificacion: pd.DataFrame):
    mejor = clasificacion.iloc[0] if not clasificacion.empty else None
    juego = resumen.get("partido_mas_anotado")
    ultima = resumen.get("ultima_ingesta")
    puntos = resumen.get("puntos_por_equipo")
    return [
        kpi("Partidos jugados", f"{resumen['partidos_jugados']:,}",
            f"{resumen['partidos_en_base']:,} partidos en la base de datos"),
        kpi("Puntos por equipo y partido", f"{puntos:.1f}" if puntos else "—",
            f"{resumen['partidos_con_prorroga']} partidos con prórroga"),
        kpi("Mejor récord",
            f"{mejor['ganados']}-{mejor['perdidos']}" if mejor is not None else "—",
            mejor["nombre"] if mejor is not None else None),
        kpi("Partido con más puntos", str(juego["total"]) if juego else "—",
            f"{juego['visitante']} {juego['puntos_visitante']} @ {juego['local']} "
            f"{juego['puntos_local']} · {fecha_corta(juego['fecha'])}" if juego else None),
        kpi("Última actualización", fecha_hora(ultima["finalizada_en"]) if ultima else "—",
            f"Ingesta #{ultima['ingesta_id']} · {TIPOS_INGESTA.get(ultima['tipo'], ultima['tipo'])}"
            if ultima else None),
    ]


def figura_ofensiva_defensiva(df: pd.DataFrame, equipo_id) -> go.Figure:
    fig = go.Figure()
    for conferencia, color in (("Este", AZUL), ("Oeste", NARANJA)):
        datos = df[df["conferencia"] == conferencia]
        if datos.empty:
            continue
        fig.add_trace(go.Scatter(
            x=datos["puntos_favor_prom"], y=datos["puntos_contra_prom"],
            mode="markers+text", name=f"Conferencia {conferencia}",
            text=datos["abreviatura"], textposition="top center",
            textfont=dict(size=10, color=TINTA_2),
            marker=dict(size=11, color=color, line=dict(color=SUPERFICIE, width=2)),
            customdata=datos[["nombre", "ganados", "perdidos", "diferencial_prom"]],
            hovertemplate=("<b>%{customdata[0]}</b><br>Récord: %{customdata[1]}-%{customdata[2]}"
                           "<br>Anotados: %{x:.1f} · Permitidos: %{y:.1f}"
                           "<br>Diferencial: %{customdata[3]:+.1f}<extra></extra>"),
        ))
    seleccionado = df[df["equipo_id"] == equipo_id]
    if not seleccionado.empty:
        fig.add_trace(go.Scatter(
            x=seleccionado["puntos_favor_prom"], y=seleccionado["puntos_contra_prom"],
            mode="markers", showlegend=False, hoverinfo="skip",
            marker=dict(size=24, color="rgba(0,0,0,0)", line=dict(color=TINTA, width=2)),
        ))
    promedio = df["puntos_favor_prom"].mean()
    fig.add_vline(x=promedio, line=dict(color=BASE, width=1))
    fig.add_hline(y=df["puntos_contra_prom"].mean(), line=dict(color=BASE, width=1))
    for x, y, alineacion, texto in ((1, 1, "right", "Anotan más y permiten menos"),
                                    (0, 0, "left", "Anotan menos y permiten más")):
        fig.add_annotation(text=texto, xref="paper", yref="paper", x=x, y=y, showarrow=False,
                           xanchor=alineacion, yanchor="top" if y else "bottom",
                           font=dict(size=11, color=TENUE))
    fig.update_xaxes(title="Puntos anotados por partido")
    fig.update_yaxes(title="Puntos permitidos por partido", autorange="reversed")
    return estilo(fig, 520, hovermode="closest")


def figura_diferencial(df: pd.DataFrame, equipo_id) -> go.Figure:
    datos = df.sort_values("diferencial_prom")
    etiquetas = [f"<b>{a}</b>" if i == equipo_id else a
                 for a, i in zip(datos["abreviatura"], datos["equipo_id"])]
    fig = go.Figure(go.Bar(
        x=datos["diferencial_prom"], y=datos["abreviatura"], orientation="h",
        marker=dict(color=[AZUL if v >= 0 else ROJO for v in datos["diferencial_prom"]],
                    cornerradius=4),
        text=[f"{v:+.1f}" for v in datos["diferencial_prom"]], textposition="outside",
        textfont=dict(size=10, color=TINTA_2), cliponaxis=False,
        customdata=datos[["nombre"]],
        hovertemplate="<b>%{customdata[0]}</b><br>Diferencial: %{x:+.1f}<extra></extra>",
    ))
    fig.update_yaxes(tickvals=list(datos["abreviatura"]), ticktext=etiquetas,
                     tickfont=dict(size=10, color=TINTA_2), showgrid=False)
    fig.update_xaxes(title="Puntos por partido", zeroline=True, zerolinewidth=1)
    return estilo(fig, 520, bargap=0.3, showlegend=False,
                  margin=dict(l=56, r=40, t=16, b=48))


def tabla_clasificacion(df: pd.DataFrame, conferencia: str, equipo_id, tipo: int):
    datos = df[df["conferencia"] == conferencia]
    if datos.empty:
        return aviso(f"Sin datos de la Conferencia {conferencia}.")
    columnas = ("#", "Equipo", "G", "P", "%", "JD", "PF", "PC", "DIF", "Local", "Visita")
    filas = []
    for posicion, fila in enumerate(datos.itertuples(), start=1):
        clases = []
        if tipo == 2 and posicion <= 6:
            clases.append("playoff")
        elif tipo == 2 and posicion <= 10:
            clases.append("playin")
        if fila.equipo_id == equipo_id:
            clases.append("seleccionado")
        filas.append(html.Tr([
            html.Td(posicion, className="num secundario"),
            html.Td(html.Span([logo(fila.logo_url), fila.nombre], className="equipo")),
            html.Td(fila.ganados, className="num"),
            html.Td(fila.perdidos, className="num"),
            html.Td(f"{fila.pct_victorias:.3f}".lstrip("0"), className="num"),
            html.Td("—" if fila.juegos_detras == 0 else f"{fila.juegos_detras:g}",
                    className="num secundario"),
            html.Td(f"{fila.puntos_favor_prom:.1f}", className="num"),
            html.Td(f"{fila.puntos_contra_prom:.1f}", className="num"),
            html.Td(f"{fila.diferencial_prom:+.1f}",
                    className="num " + ("positivo" if fila.diferencial_prom >= 0 else "negativo")),
            html.Td(f"{fila.ganados_local}-{fila.perdidos_local}", className="num secundario"),
            html.Td(f"{fila.ganados_visita}-{fila.perdidos_visita}", className="num secundario"),
        ], className=" ".join(clases)))
    return html.Div([
        html.H4(f"Conferencia {conferencia}"),
        html.Div(html.Table([html.Thead(html.Tr([
                                 html.Th(c, className=None if c == "Equipo" else "num")
                                 for c in columnas])),
                             html.Tbody(filas)], className="tabla"),
                 className="tabla-contenedor"),
    ])


@app.callback(
    Output("kpis", "children"), Output("graf-ofensiva", "figure"),
    Output("graf-diferencial", "figure"), Output("tabla-este", "children"),
    Output("tabla-oeste", "children"),
    Input("filtro-temporada", "value"), Input("filtro-tipo", "value"),
    Input("filtro-equipo", "value"), Input("version-datos", "data"),
)
def actualizar_liga(temporada, tipo, equipo_id, _):
    if temporada is None or tipo is None:
        mensaje = "Aún no hay partidos almacenados. Usa «Obtener datos» para descargarlos."
        return ([kpi("Partidos jugados", "0", "La base de datos está vacía")],
                figura_vacia(mensaje, 520), figura_vacia("Sin datos", 520),
                aviso(mensaje), None)
    try:
        resumen = api_get("/estadisticas/resumen", temporada=temporada, tipo=tipo)
        clasificacion = pd.DataFrame(
            api_get("/estadisticas/clasificacion", temporada=temporada, tipo=tipo))
    except requests.RequestException:
        log.exception("Error al consultar la API")
        error = figura_vacia("No se pudo consultar la API. Se reintentará automáticamente.", 520)
        return no_update, error, error, aviso("API no disponible."), None
    if clasificacion.empty:
        vacio = figura_vacia("Sin partidos terminados en esta selección", 520)
        return construir_kpis(resumen, clasificacion), vacio, vacio, aviso("Sin datos."), None
    return (
        construir_kpis(resumen, clasificacion),
        figura_ofensiva_defensiva(clasificacion, equipo_id),
        figura_diferencial(clasificacion, equipo_id),
        tabla_clasificacion(clasificacion, "Este", equipo_id, tipo),
        tabla_clasificacion(clasificacion, "Oeste", equipo_id, tipo),
    )


# ---------------------------------------------------------------------------
# Vista de equipo
# ---------------------------------------------------------------------------

def encabezado_equipo(equipo: dict, tendencia: pd.DataFrame, temporada: int):
    if tendencia.empty:
        registro = "Sin partidos terminados en esta selección"
    else:
        locales = tendencia[tendencia["es_local"]]
        visitas = tendencia[~tendencia["es_local"]]
        ultimo = tendencia.iloc[-1]
        registro = (f"Récord {ultimo['ganados_acum']}-{ultimo['perdidos_acum']} · "
                    f"Local {locales['gano'].sum()}-{(~locales['gano']).sum()} · "
                    f"Visita {visitas['gano'].sum()}-{(~visitas['gano']).sum()}")
    ubicacion = " · ".join(x for x in (
        f"Conferencia {equipo['conferencia']}" if equipo.get("conferencia") else None,
        f"División {equipo['division']}" if equipo.get("division") else None) if x)
    return [
        logo(equipo.get("logo_url"), 56),
        html.Div([
            html.H2(equipo["nombre"]),
            html.P(f"{ubicacion} · Temporada {etiqueta_temporada(temporada)}"),
            html.P(registro, className="registro"),
        ]),
    ]


def figura_tendencia(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fechas = pd.to_datetime(df["fecha"])
    resultado = df["gano"].map({True: "Ganó", False: "Perdió"})
    sede = df["es_local"].map({True: "vs", False: "@"})
    detalle = pd.DataFrame({"sede": sede, "rival": df["rival"], "resultado": resultado,
                            "favor": df["puntos_favor"], "contra": df["puntos_contra"]})
    for columna, media, nombre, color, verbo in (
        ("puntos_favor", "favor_media_movil", "Anotados", AZUL, "Anotó"),
        ("puntos_contra", "contra_media_movil", "Permitidos", NARANJA, "Permitió"),
    ):
        fig.add_trace(go.Scatter(
            x=fechas, y=df[columna], mode="markers", legendgroup=nombre, showlegend=False,
            marker=dict(size=7, color=color, opacity=0.35),
            customdata=detalle,
            hovertemplate=(f"{verbo} %{{y}} · %{{customdata[0]}} %{{customdata[1]}} "
                           "(%{customdata[2]} %{customdata[3]}-%{customdata[4]})<extra></extra>"),
        ))
        fig.add_trace(go.Scatter(
            x=fechas, y=df[media], mode="lines", legendgroup=nombre,
            name=f"{nombre} · media de 10 partidos",
            line=dict(color=color, width=2),
            hovertemplate=f"Media {nombre.lower()}: %{{y:.1f}}<extra></extra>",
        ))
    fig.update_yaxes(title="Puntos")
    fig.update_xaxes(tickformat="%d %b")
    return estilo(fig, 380, hovermode="x unified")


def figura_cuartos(filas: list[dict], abreviatura: str) -> go.Figure:
    df = pd.DataFrame(filas)
    df = df[df["periodo"].isin(CUARTOS)]
    etiquetas = df["periodo"].map(CUARTOS)
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=etiquetas, y=df["equipo"], name=abreviatura, marker=dict(color=AZUL, cornerradius=4),
        text=df["equipo"].map(lambda v: f"{v:.1f}" if pd.notna(v) else ""),
        textposition="outside", textfont=dict(size=11, color=TINTA_2), cliponaxis=False,
        hovertemplate=f"{abreviatura}: %{{y:.1f}} puntos<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        x=etiquetas, y=df["liga"], name="Promedio de la liga",
        marker=dict(color=GRIS, cornerradius=4),
        text=df["liga"].map(lambda v: f"{v:.1f}"), textposition="outside",
        textfont=dict(size=11, color=TINTA_2), cliponaxis=False,
        hovertemplate="Liga: %{y:.1f} puntos<extra></extra>",
    ))
    fig.update_yaxes(title="Puntos promedio", rangemode="tozero")
    return estilo(fig, 340, barmode="group", bargap=0.45, bargroupgap=0.12)


def tabla_partidos(filas: list[dict], equipo_id: int):
    if not filas:
        return aviso("Sin partidos en esta selección.")
    cuerpo = []
    for p in filas:
        es_local = p["equipo_local_id"] == equipo_id
        rival = p["visitante"] if es_local else p["local"]
        rival_logo = p["visitante_logo"] if es_local else p["local_logo"]
        propios = p["puntos_local"] if es_local else p["puntos_visitante"]
        ajenos = p["puntos_visitante"] if es_local else p["puntos_local"]
        if p["completado"]:
            gano = propios > ajenos
            resultado = html.Span([
                html.Span("G" if gano else "P", className=f"chip {'gano' if gano else 'perdio'}"),
                f" {propios}-{ajenos}" + (" (prórroga)" if (p["periodos"] or 4) > 4 else ""),
            ])
        elif propios is not None:
            resultado = html.Span([chip_estado("en_proceso"), f" {propios}-{ajenos}"])
        else:
            resultado = html.Span(ESTADOS_PARTIDO.get(p["estado"], "Programado"),
                                  className="secundario")
        cuerpo.append(html.Tr([
            html.Td(fecha_corta(p["fecha"], con_anio=False), className="secundario"),
            html.Td(html.Span([html.Span("vs" if es_local else "@", className="sede"),
                               logo(rival_logo), rival], className="equipo")),
            html.Td(resultado),
            html.Td(p["nota"] or "—", className="secundario"),
        ]))
    encabezado = html.Thead(html.Tr([html.Th(t) for t in ("Fecha", "Rival", "Resultado", "Nota")]))
    return html.Div(html.Table([encabezado, html.Tbody(cuerpo)], className="tabla"),
                    className="tabla-contenedor")


@app.callback(
    Output("encabezado-equipo", "children"), Output("graf-tendencia", "figure"),
    Output("graf-cuartos", "figure"), Output("tabla-partidos", "children"),
    Input("filtro-temporada", "value"), Input("filtro-tipo", "value"),
    Input("filtro-equipo", "value"), Input("version-datos", "data"),
    State("datos-equipos", "data"),
)
def actualizar_equipo(temporada, tipo, equipo_id, _, equipos):
    equipo = (equipos or {}).get(str(equipo_id))
    if temporada is None or tipo is None or equipo is None:
        vacio = figura_vacia("Selecciona una temporada y un equipo")
        return None, vacio, vacio, None
    try:
        tendencia = pd.DataFrame(api_get(f"/estadisticas/equipos/{equipo_id}/tendencia",
                                         temporada=temporada, tipo=tipo))
        cuartos = api_get("/estadisticas/puntos-por-periodo", temporada=temporada, tipo=tipo,
                          equipo_id=equipo_id)
        partidos = api_get("/partidos", temporada=temporada, tipo=tipo, equipo_id=equipo_id,
                           limite=10)
    except requests.RequestException:
        log.exception("Error al consultar la API")
        error = figura_vacia("No se pudo consultar la API.")
        return no_update, error, error, aviso("API no disponible.")
    encabezado = encabezado_equipo(equipo, tendencia, temporada)
    if tendencia.empty:
        vacio = figura_vacia("Este equipo no tiene partidos terminados en esta selección")
        return encabezado, vacio, vacio, tabla_partidos(partidos, equipo_id)
    return (encabezado, figura_tendencia(tendencia),
            figura_cuartos(cuartos, equipo["abreviatura"]),
            tabla_partidos(partidos, equipo_id))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8050, debug=True)
