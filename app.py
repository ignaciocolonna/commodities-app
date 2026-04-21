"""
Shiny app: look up the 'Último' (close) price for a MATba-Rofex futures
contract by choosing Cultivo + Mes + Año.

Run with:
    shiny run --reload app.py
Then open http://127.0.0.1:8000 in a browser.
"""

from __future__ import annotations

import requests
from datetime import date, timedelta

from shiny import App, reactive, render, ui

# ---------------------------------------------------------------------------
# Data-fetching layer (same logic as price_commodities.py, inlined for clarity)
# ---------------------------------------------------------------------------

API_URL = "https://apicem.matbarofex.com.ar/api/v2/closing-prices"

# symbol prefix -> the exact `product` query-string value expected by the API
PRODUCT_BY_PREFIX = {
    "TRI.ROS": "TRI Dolar MATba",
    "SOJ.ROS": "Soja Rosario",
    "MAI.ROS": "Maiz Rosario",
}

# Which months trade for each cultivo. VERIFY THESE against the site and edit
# as needed — they're my best guess at typical Rofex contract months.
TRADED_MONTHS = {
    "TRI": ["ENE", "MAR", "JUL", "SEP", "DIC"],
    "SOJ": ["ENE", "MAR", "MAY", "JUL", "AGO", "SEP", "NOV"],
    "MAI": ["ABR", "JUL", "SEP", "DIC"],
}

# Human-friendly cultivo names for the dropdown
CULTIVO_LABELS = {
    "TRI": "TRI — Trigo",
    "SOJ": "SOJ — Soja",
    "MAI": "MAI — Maíz",
}

YEARS = [f"{y:02d}" for y in range(24, 31)]  # '24' … '30'


def fetch_contract(
    symbol: str,
    *,
    on: date | None = None,
    lookback_days: int = 7,
    timeout: float = 15.0,
) -> dict:
    """Fetch the most recent row for `symbol`, walking back over non-trading days."""
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
    ui.panel_title("Precios MATba-Rofex"),
    ui.layout_sidebar(
        ui.sidebar(
            ui.input_select(
                "cultivo",
                "Cultivo",
                choices=CULTIVO_LABELS,
                selected="TRI",
            ),
            # Month choices are filled dynamically based on cultivo
            ui.input_select("mes", "Mes", choices=TRADED_MONTHS["TRI"]),
            ui.input_select("anio", "Año", choices=YEARS, selected="26"),
            ui.input_action_button("buscar", "Buscar", class_="btn-primary"),
            width=260,
        ),
        ui.output_ui("resultado"),
    ),
)


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

def server(input, output, session):
    # Keep the Mes dropdown in sync with the selected Cultivo
    @reactive.effect
    @reactive.event(input.cultivo)
    def _sync_months():
        meses = TRADED_MONTHS[input.cultivo()]
        current = input.mes()
        ui.update_select(
            "mes",
            choices=meses,
            # Preserve the current month if it's still valid for the new cultivo
            selected=current if current in meses else meses[0],
        )

    # Fetch only when the user clicks Buscar (not on every dropdown change)
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
    def resultado():
        # Before any click, show a gentle hint rather than an error
        if input.buscar() == 0:
            return ui.div(
                ui.p(
                    "Elegí Cultivo, Mes y Año, y tocá ",
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
        fecha = row["dateTime"][:10]  # 'YYYY-MM-DD'

        # Stash the last value where the copy button's JS can grab it
        ultimo_str = f"{ultimo:g}"

        return ui.div(
            ui.h3(data["symbol"]),
            ui.p(ui.tags.small(f"Datos del {fecha}", class_="text-muted")),
            ui.tags.table(
                ui.tags.tbody(
                    ui.tags.tr(
                        ui.tags.th("Último", scope="row"),
                        ui.tags.td(
                            ui.tags.span(ultimo_str, id="valor-ultimo"),
                            style="font-size: 1.5em; font-weight: bold;",
                        ),
                    ),
                    ui.tags.tr(
                        ui.tags.th("Ajuste", scope="row"),
                        ui.tags.td(f"{ajuste:g}"),
                    ),
                    ui.tags.tr(
                        ui.tags.th("Volumen", scope="row"),
                        ui.tags.td(f"{int(volumen)}"),
                    ),
                ),
                class_="table table-sm",
                style="max-width: 320px;",
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
        )

    @render.download(filename=lambda: f"{resultado_data()['symbol'].replace('/', '_')}.csv")
    def descargar_csv():
        data = resultado_data()
        if not data["ok"]:
            yield "error,mensaje\n"
            yield f"true,{data['error']}\n"
            return
        row = data["row"]
        # Emit all fields so you have everything the API returned
        headers = list(row.keys())
        yield ",".join(headers) + "\n"
        yield ",".join("" if row[h] is None else str(row[h]) for h in headers) + "\n"


app = App(app_ui, server)
