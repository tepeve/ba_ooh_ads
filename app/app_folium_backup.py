import logging
from pathlib import Path
from typing import Any

import duckdb
import folium
from folium.plugins import MarkerCluster
from shiny import App, reactive, ui, render
from htmltools import HTML as shiny_HTML

# --- Logging Configuration ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# --- Data Path Configuration ---
DATA_PATH = Path("data/processed/tablero_anuncios_consolidado.parquet")

# --- Helper Functions ---
def load_filter_options() -> dict[str, Any]:
    """Carga opciones de filtros desde el parquet de manera segura."""
    defaults = {
        "clase": [], "tipo": [], "caracteristica": [], 
        "needs_geocoding": [], "metros_min": 0, "metros_max": 100,
    }
    
    if not DATA_PATH.exists():
        return defaults
    
    try:
        con = duckdb.connect(database=":memory:")
        clase_values = [row[0] for row in con.execute(f"SELECT DISTINCT clase FROM '{DATA_PATH}' WHERE clase IS NOT NULL ORDER BY clase").fetchall()]
        tipo_values = [row[0] for row in con.execute(f"SELECT DISTINCT tipo FROM '{DATA_PATH}' WHERE tipo IS NOT NULL ORDER BY tipo").fetchall()]
        caract_values = [row[0] for row in con.execute(f"SELECT DISTINCT caracteristica FROM '{DATA_PATH}' WHERE caracteristica IS NOT NULL ORDER BY caracteristica").fetchall()]
        needs_geocoding_values = [str(row[0]) for row in con.execute(f"SELECT DISTINCT needs_geocoding FROM '{DATA_PATH}' WHERE needs_geocoding IS NOT NULL ORDER BY needs_geocoding").fetchall()]
        metros_range = con.execute(f"SELECT MIN(metros), MAX(metros) FROM '{DATA_PATH}' WHERE metros IS NOT NULL").fetchone()
        con.close()
        
        return {
            "clase": clase_values, "tipo": tipo_values, "caracteristica": caract_values,
            "needs_geocoding": needs_geocoding_values,
            "metros_min": int(metros_range[0]) if metros_range and metros_range[0] else 0,
            "metros_max": int(metros_range[1]) if metros_range and metros_range[1] else 100,
        }
    except Exception as e:
        logger.error(f"Error loading filter options: {e}")
        return defaults

FILTER_OPTIONS = load_filter_options()

# --- UI Definition ---
app_ui = ui.page_fillable(
    ui.h2("BA OOH Ads - Explorer"),
    ui.p("Visualización de anuncios en CABA"),
    
    ui.layout_sidebar(
        ui.sidebar(
            ui.h4("Filtros"),
            ui.input_checkbox_group("clase_filter", "Clase:", choices=FILTER_OPTIONS["clase"], selected=FILTER_OPTIONS["clase"]),
            ui.hr(),
            ui.input_checkbox_group("tipo_filter", "Tipo:", choices=FILTER_OPTIONS["tipo"], selected=FILTER_OPTIONS["tipo"]),
            ui.hr(),
            ui.input_selectize("caracteristica_filter", "Característica:", choices=FILTER_OPTIONS["caracteristica"], multiple=True, options={"placeholder": "Seleccionar..."}),
            ui.hr(),
            ui.input_checkbox_group("needs_geocoding_filter", "Geocodificación:", choices=FILTER_OPTIONS["needs_geocoding"], selected=FILTER_OPTIONS["needs_geocoding"]),
            ui.hr(),
            ui.input_slider("metros_filter", "Metros²:", min=FILTER_OPTIONS["metros_min"], max=FILTER_OPTIONS["metros_max"], value=[FILTER_OPTIONS["metros_min"], FILTER_OPTIONS["metros_max"]], step=1),
            width=280, open="desktop",
        ),
        ui.card(
            ui.card_header(ui.output_text("map_header")),
            ui.output_ui("map_output"),  # Cambio: output_ui en lugar de output_widget
            full_screen=True, fill=True,
        ),
    ),
)

# --- SERVER LOGIC ---
def server(input, output, session):
    
    # Lógica de Datos
    @reactive.calc
    def filtered_data() -> list[tuple]:
        if not DATA_PATH.exists(): return []
        
        s_clase = list(input.clase_filter())
        s_tipo = list(input.tipo_filter())
        s_caract = list(input.caracteristica_filter())
        s_geo = list(input.needs_geocoding_filter())
        r_metros = input.metros_filter()
        
        clauses = ["lat IS NOT NULL", "long IS NOT NULL"]

        if not s_clase or not s_tipo: return []
        
        if s_clase: clauses.append(f"clase IN ({', '.join([f'{chr(39)}{c}{chr(39)}' for c in s_clase])})")
        if s_tipo: clauses.append(f"tipo IN ({', '.join([f'{chr(39)}{t}{chr(39)}' for t in s_tipo])})")
        if s_caract: clauses.append(f"caracteristica IN ({', '.join([f'{chr(39)}{c}{chr(39)}' for c in s_caract])})")
        if r_metros: clauses.append(f"metros BETWEEN {r_metros[0]} AND {r_metros[1]}")
        
        if s_geo:
            conds = []
            for v in s_geo:
                v_s = str(v).lower()
                if v_s == 'true': conds.append("needs_geocoding = TRUE")
                elif v_s == 'false': conds.append("needs_geocoding = FALSE")
                else: conds.append(f"needs_geocoding = '{v}'")
            if conds: clauses.append(f"({' OR '.join(conds)})")
        else:
            return []

        query = f"""
            SELECT lat, long, clase, tipo, full_address, barrio_desc
            FROM '{DATA_PATH}'
            WHERE {" AND ".join(clauses)}
            -- LIMIT 200
        """
        
        try:
            con = duckdb.connect(database=":memory:")
            rows = con.execute(query).fetchall()
            con.close()
            return rows
        except Exception as e:
            logger.error(f"Query Error: {e}")
            return []

    # Renderizado del Mapa con Folium
    @output
    @render.ui
    def map_output():
        """Genera un mapa Folium con los datos filtrados."""
        data = filtered_data()
        
        # Crear mapa base centrado en CABA
        m = folium.Map(
            location=[-34.6037, -58.3816],
            zoom_start=12,
            tiles='CartoDB positron',
            width='100%',
            height='800px'
        )
        
        # Crear cluster de marcadores
        marker_cluster = MarkerCluster().add_to(m)
        
        # Agregar marcadores
        marker_count = 0
        for idx, row in enumerate(data):
            try:
                raw_lat, raw_lon, clase, tipo, addr, barrio = row[0], row[1], row[2], row[3], row[4], row[5]
                
                # Limpieza
                if isinstance(raw_lat, str): raw_lat = raw_lat.replace(',', '.')
                if isinstance(raw_lon, str): raw_lon = raw_lon.replace(',', '.')
                
                lat = float(raw_lat)
                lon = float(raw_lon)

                # Validación
                if lat == 0 or lon == 0: continue
                if not (-34.7 < lat < -34.5 and -58.5 < lon < -58.3): continue
                
                # Popup HTML
                popup_html = f"""
                <div style='min-width: 250px; font-family: Arial;'>
                    <h4 style='margin: 0 0 8px 0; color: #1e40af;'>{clase}</h4>
                    <p style='margin: 4px 0;'><b>Tipo:</b> {tipo}</p>
                    <p style='margin: 4px 0;'><b>Dirección:</b> {addr}</p>
                    <p style='margin: 4px 0;'><b>Barrio:</b> {barrio if barrio else 'S/D'}</p>
                </div>
                """
                
                # Agregar marcador circular
                folium.CircleMarker(
                    location=[lat, lon],
                    radius=6,
                    color='#dc2626',
                    fill=True,
                    fill_color='#ef4444',
                    fill_opacity=0.7,
                    weight=2,
                    popup=folium.Popup(popup_html, max_width=300)
                ).add_to(marker_cluster)
                
                marker_count += 1
                
            except (ValueError, TypeError, IndexError) as e:
                logger.warning(f"Error procesando fila {idx}: {e}")
                continue
        
        logger.info(f"✅ Mapa generado con {marker_count} marcadores")
        
        # Convertir el mapa a HTML
        map_html = m._repr_html_()
        
        # Retornar como objeto HTML de Shiny
        return shiny_HTML(map_html)

    @output
    @render.text 
    def map_header():
        return f"Mapa de Anuncios ({len(filtered_data())} resultados)"

app = App(app_ui, server)
