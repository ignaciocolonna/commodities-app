"""
Shiny app: look up the 'Último' (close) price for a MATba-Rofex futures
contract by choosing Cultivo + Mes + Año, and compute Ingreso Bruto at
three yield (Rendimiento) levels.

Ingreso Bruto = close (USD/tonne) * Rendimiento (tonnes/hectare)
             => USD per hectare

Run with:
    shiny run --reload app.py
"""

from __future__ import annotations

import requests
from datetime import date, timedelta

from shiny import App, reactive, render, ui

# ---------------------------------------------------------------------------
# Data-fetching layer
# ---------------------------------------------------------------------------

API_URL = "https://apicem.matbarofex.com.ar/api/v2/closing-prices"

PRODUCT_BY_PREFIX = {
    "TRI.ROS": "TRI Dolar MATba",
    "SOJ.ROS": "Soja Rosario",
    "MAI.ROS": "Maiz Rosario",
}

TRADED_MONTHS = {
    "TRI": ["ENE", "MAR", "JUL", "SEP", "DIC"],
    "SOJ": ["ENE", "MAR", "MAY", "JUL", "AGO", "SEP", "NOV"],
    "MAI": ["ABR", "JUL", "SEP", "DIC"],
}

CULTIVO_LABELS = {
    "TRI": "TRI — Trigo",
    "SOJ": "SOJ — Soja",
    "MAI": "MAI — Maíz",
}

YEARS = [f"{y:02d}" for y in range(24, 31)]

# Default yields (t/ha) per cultivo. User can override in the UI.
DEFAULT_RENDIMIENTO_BY_CULTIVO = {
    "TRI": {"alto": 5.0, "medio": 3.5, "bajo": 2.5},
    "SOJ": {"alto": 5.0, "medio": 3.5, "bajo": 2.5},
    "MAI": {"alto": 12.0, "medio": 9.0, "bajo": 6.0},
}

def _defaults_for(cultivo: str) -> dict:
    return DEFAULT_RENDIMIENTO_BY_CULTIVO[cultivo]


def fetch_contract(
    symbol: str,
    *,
    on: date | None = None,
    lookback_days: int = 7,
    timeout: float = 15.0,
) -> dict:
    prefix = symbol.split("/", 1)[0]
    if prefix not in PRODUCT_BY_PREFIX:
        raise ValueError(f"Unknown symbol prefix {prefix!r}.")

    day = on or date.today()
    last_error: Exception | None = None

    for offset in range(lookback_days + 1):
        probe = day - timedelta(days=offset)
        params = {
            "product": PRODUCT_BY_PREFIX[prefix],
            "segment": "Agropecuario",
            "type": "FUT",
            "excludeEmptyVol": "true",
            "from": probe.isoformat(),
            "to": probe.isoformat(),
            "page": 1,
            "pageSize": 50,
            "sortDir": "ASC",
            "market": "ROFX",
        }
        try:
            resp = requests.get(API_URL, params=params, timeout=timeout)
            resp.raise_for_status()
        except requests.RequestException as e:
            last_error = e
            continue

        for row in resp.json().get("data", []):
            if row.get("symbol") == symbol:
                return row

    if last_error is not None:
        raise LookupError(
            f"No data for {symbol} in the last {lookback_days} day(s); "
            f"last error: {last_error}"
        )
    raise LookupError(f"No data for {symbol} in the last {lookback_days} day(s).")


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

app_ui = ui.page_fluid(
    ui.panel_title("Precios MATba-Rofex & Ingreso Bruto"),
    ui.layout_sidebar(
        ui.sidebar(
            ui.h5("Contrato"),
            ui.input_select("cultivo", "Cultivo", choices=CULTIVO_LABELS, selected="TRI"),
            ui.input_select("mes", "Mes", choices=TRADED_MONTHS["TRI"]),
            ui.input_select("anio", "Año", choices=YEARS, selected="26"),
            ui.hr(),
            ui.h5("Rendimiento (t/ha)"),
            ui.input_numeric("rend_alto", "Alto", value=DEFAULT_RENDIMIENTO_BY_CULTIVO["TRI"]["alto"], min=0, step=0.1),
            ui.input_numeric("rend_medio", "Medio", value=DEFAULT_RENDIMIENTO_BY_CULTIVO["TRI"]["medio"], min=0, step=0.1),
            ui.input_numeric("rend_bajo", "Bajo", value=DEFAULT_RENDIMIENTO_BY_CULTIVO["TRI"]["bajo"], min=0, step=0.1),
            ui.hr(),
            ui.input_action_button("buscar", "Buscar", class_="btn-primary"),
            width=280,
        ),
        ui.output_ui("panel_precio"),
        ui.output_ui("panel_ingreso"),
    ),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_usd(x: float) -> str:
    """Format as e.g. 'USD 1.085' with thousands dots, no decimals (es-AR style)."""
    return f"USD {x:,.0f}".replace(",", ".")


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

def server(input, output, session):
    @reactive.effect
    @reactive.event(input.cultivo)
    def _sync_months():
        meses = TRADED_MONTHS[input.cultivo()]
        current = input.mes()
        ui.update_select(
            "mes",
            choices=meses,
            selected=current if current in meses else meses[0],
        )

    # Also refresh Rendimiento defaults when cultivo changes
    @reactive.effect
    @reactive.event(input.cultivo)
    def _sync_rendimiento():
        d = _defaults_for(input.cultivo())
        ui.update_numeric("rend_alto", value=d["alto"])
        ui.update_numeric("rend_medio", value=d["medio"])
        ui.update_numeric("rend_bajo", value=d["bajo"])

    @reactive.calc
    @reactive.event(input.buscar)
    def resultado_data():
        cultivo = input.cultivo()
        mes = input.mes()
        anio = input.anio()
        symbol = f"{cultivo}.ROS/{mes}{anio}"
        try:
            return {"ok": True, "symbol": symbol, "row": fetch_contract(symbol)}
        except (LookupError, ValueError) as e:
            return {"ok": False, "symbol": symbol, "error": str(e)}

    @render.ui
    def panel_precio():
        if input.buscar() == 0:
            return ui.div(
                ui.p(
                    "Elegí Cultivo, Mes, Año y Rendimientos, y tocá ",
                    ui.tags.b("Buscar"),
                    ".",
                ),
                class_="text-muted",
            )

        data = resultado_data()
        if not data["ok"]:
            return ui.div(
                ui.h4(data["symbol"]),
                ui.tags.div(
                    f"No se pudo obtener el precio: {data['error']}",
                    class_="alert alert-warning",
                ),
            )

        row = data["row"]
        ultimo = row["close"]
        ajuste = row["settlement"]
        volumen = row["volume"]
        fecha = row["dateTime"][:10]
        ultimo_str = f"{ultimo:g}"

        return ui.div(
            ui.h3(data["symbol"]),
            ui.p(ui.tags.small(f"Datos del {fecha}", class_="text-muted")),
            ui.tags.table(
                ui.tags.tbody(
                    ui.tags.tr(
                        ui.tags.th("Último (USD/t)", scope="row"),
                        ui.tags.td(
                            ui.tags.span(ultimo_str, id="valor-ultimo"),
                            style="font-size: 1.5em; font-weight: bold;",
                        ),
                    ),
                    ui.tags.tr(
                        ui.tags.th("Ajuste (USD/t)", scope="row"),
                        ui.tags.td(f"{ajuste:g}"),
                    ),
                    ui.tags.tr(
                        ui.tags.th("Volumen", scope="row"),
                        ui.tags.td(f"{int(volumen)}"),
                    ),
                ),
                class_="table table-sm",
                style="max-width: 360px;",
            ),
            ui.tags.button(
                "Copiar Último",
                class_="btn btn-outline-secondary btn-sm",
                onclick=(
                    f"navigator.clipboard.writeText('{ultimo_str}');"
                    "this.innerText='¡Copiado!';"
                    "setTimeout(()=>this.innerText='Copiar Último',1500);"
                ),
            ),
            " ",
            ui.download_button("descargar_csv", "Descargar CSV", class_="btn-sm"),
            ui.tags.hr(),
        )

    @render.ui
    def panel_ingreso():
        if input.buscar() == 0:
            return ui.div()
        data = resultado_data()
        if not data["ok"]:
            return ui.div()

        ultimo = data["row"]["close"]

        def _safe(x, default):
            try:
                return float(x) if x is not None else default
            except (TypeError, ValueError):
                return default

        d = _defaults_for(input.cultivo())
        alto = _safe(input.rend_alto(), d["alto"])
        medio = _safe(input.rend_medio(), d["medio"])
        bajo = _safe(input.rend_bajo(), d["bajo"])

        ing_alto = ultimo * alto
        ing_medio = ultimo * medio
        ing_bajo = ultimo * bajo

        return ui.div(
            ui.h4("Ingreso Bruto (USD/ha)"),
            ui.p(
                ui.tags.small(
                    "Calculado como Último × Rendimiento.",
                    class_="text-muted",
                ),
            ),
            ui.layout_column_wrap(
                ui.value_box(
                    "Alto",
                    _fmt_usd(ing_alto),
                    f"{alto:g} t/ha × USD {ultimo:g}",
                    theme="bg-gradient-green-teal",
                ),
                ui.value_box(
                    "Medio",
                    _fmt_usd(ing_medio),
                    f"{medio:g} t/ha × USD {ultimo:g}",
                    theme="bg-gradient-blue-indigo",
                ),
                ui.value_box(
                    "Bajo",
                    _fmt_usd(ing_bajo),
                    f"{bajo:g} t/ha × USD {ultimo:g}",
                    theme="bg-gradient-orange-red",
                ),
                width=1 / 3,
                fill=False,
            ),
        )

    @render.download(filename=lambda: f"{resultado_data()['symbol'].replace('/', '_')}.csv")
    def descargar_csv():
        data = resultado_data()
        if not data["ok"]:
            yield "error,mensaje\n"
            yield f"true,{data['error']}\n"
            return
        row = data["row"]
        headers = list(row.keys())
        yield ",".join(headers) + "\n"
        yield ",".join("" if row[h] is None else str(row[h]) for h in headers) + "\n"


app = App(app_ui, server)
