import logging
import json
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import geopandas as gpd
import folium
from folium.plugins import MarkerCluster
from shiny import App, reactive, ui, render
# from shinywidgets import output_widget, render_widget  # Removed to avoid anywidget runtime errors
import plotly.express as px
from htmltools import HTML as shiny_HTML, div, strong

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
    default_values = {
        "clase": [], "tipo": [], "caracteristica": [], 
        "needs_geocoding": [], "metros_min": 0, "metros_max": 100,
        "macro_category": [], "barrio": [], "comuna": []
    }
    
    if not DATA_PATH.exists():
        return default_values
    
    try:
        con = duckdb.connect(database=":memory:")
        clase_values = [row[0] for row in con.execute(f"SELECT DISTINCT clase FROM '{DATA_PATH}' WHERE clase IS NOT NULL ORDER BY clase").fetchall()]
        tipo_values = [row[0] for row in con.execute(f"SELECT DISTINCT tipo FROM '{DATA_PATH}' WHERE tipo IS NOT NULL ORDER BY tipo").fetchall()]
        caract_values = [row[0] for row in con.execute(f"SELECT DISTINCT caracteristica FROM '{DATA_PATH}' WHERE caracteristica IS NOT NULL ORDER BY caracteristica").fetchall()]
        needs_geocoding_values = [str(row[0]) for row in con.execute(f"SELECT DISTINCT needs_geocoding FROM '{DATA_PATH}' WHERE needs_geocoding IS NOT NULL ORDER BY needs_geocoding").fetchall()]
        metros_range = con.execute(f"SELECT MIN(metros), MAX(metros) FROM '{DATA_PATH}' WHERE metros IS NOT NULL").fetchone()
        
        # Check if column exists before querying (robustness)
        cols = [c[0] for c in con.execute(f"DESCRIBE SELECT * FROM '{DATA_PATH}' LIMIT 0").fetchall()]
        
        if 'macro_category' in cols:
            macro_values = [row[0] for row in con.execute(f"SELECT DISTINCT unnest(macro_category) FROM '{DATA_PATH}' WHERE macro_category IS NOT NULL ORDER BY 1").fetchall()]
        else:
            macro_values = []
            
        # New Location Filters
        barrio_values = [row[0] for row in con.execute(f"SELECT DISTINCT barrio_desc FROM '{DATA_PATH}' WHERE barrio_desc IS NOT NULL ORDER BY 1").fetchall()] if 'barrio_desc' in cols else []
        comuna_values = [row[0] for row in con.execute(f"SELECT DISTINCT comuna_desc FROM '{DATA_PATH}' WHERE comuna_desc IS NOT NULL ORDER BY 1").fetchall()] if 'comuna_desc' in cols else []
        
        con.close()
        
        return {
            "clase": clase_values, "tipo": tipo_values, "caracteristica": caract_values,
            "needs_geocoding": needs_geocoding_values,
            "metros_min": int(metros_range[0]) if metros_range and metros_range[0] else 0,
            "metros_max": int(metros_range[1]) if metros_range and metros_range[1] else 100,
            "macro_category": macro_values, 
            "barrio": barrio_values,
            "comuna": comuna_values
        }
    
    except Exception as e:
        logger.error(f"Error loading filter options: {e}")
        return default_values

FILTER_OPTIONS = load_filter_options()

# --- Load Geometries (Global Cache) ---
def load_geometry_layers():
    layers = {}
    base_path = Path("data")
    
    # Mapping: Key -> (Path, Name, Color)
    definitions = {
        'barrios': (base_path / "external/barrios.parquet", "Barrios", "#6b7280"),
        'comunas': (base_path / "external/comunas.parquet", "Comunas", "#374151"),
        'zonificacion': (base_path / "external/zonificacion.parquet", "Zonificación", "#10b981"),
        'clusters_global': (base_path / "outputs/pois_clusters_global.geojson", "Clusters Globales", "#8b5cf6"),
        'clusters_tematicos': (base_path / "outputs/pois_clusters_tematicos.geojson", "Clusters Temáticos", "#f59e0b")
    }

    for key, (path, name, color) in definitions.items():
        if path.exists():
            try:
                gdf = gpd.read_file(path) if path.suffix == '.geojson' else gpd.read_parquet(path)
                # Ensure CRS is web mercator compatible
                if gdf.crs and gdf.crs.to_string() != "EPSG:4326":
                    gdf = gdf.to_crs("EPSG:4326")
                
                # Simplify complex polygons for map performance if needed
                if 'zonificacion' in key or 'clusters' in key:
                     gdf['geometry'] = gdf.geometry.simplify(tolerance=0.0001, preserve_topology=True)
                
                layers[key] = {
                    "gdf": gdf,
                    "name": name,
                    "color": color
                }
                logger.info(f"Loaded geo layer: {name} ({len(gdf)} feats)")
            except Exception as e:
                logger.warning(f"Could not load {name}: {e}")
    return layers

GEO_LAYERS = load_geometry_layers()

# --- UI Definition ---
app_ui = ui.page_fillable(

#Cargar librerías JS globales ---
    ui.tags.head(
        # Cargamos Plotly manualmente al principio para evitar Race Conditions
        ui.tags.script(src="https://cdn.plot.ly/plotly-2.35.2.min.js")
    ),

    # Custom CSS for the absolute panel
    ui.tags.style("""
        #details_panel {
            transition: transform 0.3s ease-in-out;
            z-index: 1000;
            background-color: var(--bs-body-bg); 
            padding: 15px; 
            border-radius: 8px; 
            box-shadow: 0 4px 6px rgba(0,0,0,0.1); 
            display: none; 
            max-height: 90vh; 
            overflow-y: auto; 
            border: 1px solid var(--bs-border-color);
        }
        .folium_btn {
            background-color: #2563eb;
            color: white;
            padding: 5px 10px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            margin-top: 5px;
            font-size: 0.85em;
        }
        .folium_btn:hover {
            background-color: #1d4ed8;
        }
    """),
    
    # Custom JS to properly handle resizing and messaging from Folium popup
    ui.tags.script("""
        // Function to be called from the Folium Popup button
        window.selectAd = function(id) {
            Shiny.setInputValue('selected_ad_id', id, {priority: 'event'});
        };
    """),

    ui.layout_sidebar(
        ui.sidebar(
            ui.h4("Filtros"),
            ui.input_dark_mode(id="dark_mode"),
            ui.hr(),
            ui.input_selectize("barrio_filter", "Barrio:", choices=FILTER_OPTIONS.get("barrio", []), multiple=True, options={"placeholder": "Todos..."}),
            ui.input_selectize("comuna_filter", "Comuna:", choices=FILTER_OPTIONS.get("comuna", []), multiple=True, options={"placeholder": "Todas..."}),
            ui.hr(),
            ui.input_checkbox_group("clase_filter", "Clase:", choices=FILTER_OPTIONS["clase"], selected=FILTER_OPTIONS["clase"]),
            ui.hr(),
            ui.input_checkbox_group("tipo_filter", "Tipo:", choices=FILTER_OPTIONS["tipo"], selected=FILTER_OPTIONS["tipo"]),
            ui.input_action_button("btn_clear_tipo", "Limpiar Tipo", class_="btn-xs btn-light"),
            ui.hr(),
            ui.input_selectize("caracteristica_filter", "Característica:", choices=FILTER_OPTIONS["caracteristica"], multiple=True, options={"placeholder": "Seleccionar..."}),
            ui.hr(),
            ui.input_checkbox_group("needs_geocoding_filter", "Geocodificación:", choices=FILTER_OPTIONS["needs_geocoding"], selected=FILTER_OPTIONS["needs_geocoding"]),
            ui.hr(),
            ui.input_slider("metros_filter", "Metros²:", min=FILTER_OPTIONS["metros_min"], max=FILTER_OPTIONS["metros_max"], value=[FILTER_OPTIONS["metros_min"], FILTER_OPTIONS["metros_max"]], step=1),
            ui.hr(),
            ui.input_selectize("macro_filter", "Categoría (Cluster):", 
                               choices=FILTER_OPTIONS.get("macro_category", []), 
                               multiple=True, options={"placeholder": "Todas..."}),
            ui.hr(),
            width=300, 
            open="desktop",
        ),
        
        ui.card(
            ui.card_header(ui.output_text("map_header")),
            ui.output_ui("map_output"),
            full_screen=True, fill=True, style="padding: 0;"
        ),
    ),
    
    # Absolute panel for details (Analysis Drawer)
    ui.panel_absolute(
        ui.div(
            ui.div(
                ui.h4("Detalle del Anuncio", style="display: inline-block;"),
                ui.input_action_button("btn_close_panel", "✕", class_="btn-sm btn-light", style="float: right; border: none;"),
                style="margin-bottom: 10px;"
            ),
            ui.output_ui("ad_metadata"),
            ui.hr(),
            ui.h5("Estimación de Alcance (Reach)"),
            ui.output_ui("reach_chart"),
        ),
        id="details_panel",
        top="50px", right="20px", width="450px",
        draggable=True,
    ),
)

# --- SERVER LOGIC ---
def server(input, output, session):
    
    # Reactive value to store selected Ad ID
    selected_ad = reactive.Value(None)
    
    # --- Capture Selection from Folium Popup ---
    @reactive.effect
    @reactive.event(input.selected_ad_id)
    def _():
        val = input.selected_ad_id()
        if val:
            selected_ad.set(val)

    # --- Filter Logic ---
    @reactive.effect
    @reactive.event(input.btn_clear_tipo)
    def _():
        ui.update_checkbox_group("tipo_filter", selected=[])

    @reactive.effect
    @reactive.event(input.btn_close_panel)
    def _():
        selected_ad.set(None)

    # Observer to show/hide panel based on selection
    @reactive.effect
    def _():
        if selected_ad.get() is not None:
             ui.insert_ui(
                ui.tags.script("document.getElementById('details_panel').style.display = 'block';"),
                selector="body", where="beforeEnd", immediate=True
            )
        else:
            ui.insert_ui(
                ui.tags.script("document.getElementById('details_panel').style.display = 'none';"),
                selector="body", where="beforeEnd", immediate=True
            )

    @reactive.calc
    def filtered_data() -> list[tuple]:
        if not DATA_PATH.exists(): return []
        
        s_clase = list(input.clase_filter())
        s_tipo = list(input.tipo_filter())
        s_caract = list(input.caracteristica_filter())
        s_geo = list(input.needs_geocoding_filter())
        r_metros = input.metros_filter()
        s_macro = list(input.macro_filter()) 
        
        # New inputs
        s_barrio = list(input.barrio_filter())
        s_comuna = list(input.comuna_filter())

        clauses = ["lat IS NOT NULL", "long IS NOT NULL"]

        if not s_clase or not s_tipo: return []
        
        if s_clase: clauses.append(f"clase IN ({', '.join([f'{chr(39)}{c}{chr(39)}' for c in s_clase])})")
        if s_tipo: clauses.append(f"tipo IN ({', '.join([f'{chr(39)}{t}{chr(39)}' for t in s_tipo])})")
        if s_caract: clauses.append(f"caracteristica IN ({', '.join([f'{chr(39)}{c}{chr(39)}' for c in s_caract])})")
        if r_metros: clauses.append(f"metros BETWEEN {r_metros[0]} AND {r_metros[1]}")
        
        if s_barrio:
             clauses.append(f"barrio_desc IN ({', '.join([f'{chr(39)}{b}{chr(39)}' for b in s_barrio])})")
        
        if s_comuna:
             clauses.append(f"comuna_desc IN ({', '.join([f'{chr(39)}{c}{chr(39)}' for c in s_comuna])})")

        if s_macro:
            # Escapar comillas simples para SQL
            safe_macros = [m.replace("'", "''") for m in s_macro]
            # Construir literal de lista DuckDB: ['Cat A', 'Cat B']
            list_literal = "[" + ", ".join([f"'{m}'" for m in safe_macros]) + "]"
            # Función list_intersect devuelve lista compartida, comprobamos si longitud > 0
            clauses.append(f"len(list_intersect(macro_category, {list_literal})) > 0")        

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

        # Include nro_anuncio (ID)
        query = f"""
            SELECT lat, long, clase, tipo, full_address, barrio_desc, nro_anuncio, metros
            FROM '{DATA_PATH}'
            WHERE {" AND ".join(clauses)}
            LIMIT 1000
        """
        
        try:
            con = duckdb.connect(database=":memory:")
            rows = con.execute(query).fetchall()
            con.close()
            return rows
        except Exception as e:
            logger.error(f"Query Error: {e}")
            return []

    # --- Map Renderer (Folium) ---
    @output
    @render.ui
    def map_output():
        data = filtered_data()
        
        # Create map
        m = folium.Map(
            location=[-34.6037, -58.3816],
            zoom_start=12,
            tiles='CartoDB positron',
            width='100%',
            height='100%'
        )
        
        # 1. Add Administrative/Cluster Layers (from Global Cache)
        # Add them first so markers appear on top (Leaflet order mostly respects addition order for z-index, but MarkerClusters usually sit high)
        for key, layer_info in GEO_LAYERS.items():
            gdf = layer_info['gdf']
            name = layer_info['name']
            color = layer_info['color']
            
            # Determine style based on layer type
            is_cluster = 'clusters' in key
            fill_opacity = 0.4 if is_cluster else 0.0
            weight = 2 if is_cluster else 1
            
            fg = folium.FeatureGroup(name=name, show=False) # Start hidden to avoid clutter
            
            folium.GeoJson(
                gdf,
                style_function=lambda x, c=color, fo=fill_opacity, w=weight: {
                    'fillColor': c, 'color': c, 'weight': w, 'fillOpacity': fo
                },
                tooltip=folium.GeoJsonTooltip(fields=[gdf.columns[0]], aliases=["Nombre:"]) if not gdf.empty else None,
                name=name
            ).add_to(fg)
            
            fg.add_to(m)

        # 2. Add Ads Markers
        fg_ads = folium.FeatureGroup(name="Anuncios", show=True)
        marker_cluster = MarkerCluster().add_to(fg_ads)
        
        marker_count = 0
        for row in data:
            try:
                # Ensure float casting
                raw_lat, raw_lon = row[0], row[1]
                clase, tipo, addr, barrio, ad_id, metros = row[2], row[3], row[4], row[5], row[6], row[7]
                
                if isinstance(raw_lat, str): raw_lat = raw_lat.replace(',', '.')
                if isinstance(raw_lon, str): raw_lon = raw_lon.replace(',', '.')
                lat, lon = float(raw_lat), float(raw_lon)
                
                if lat == 0 or lon == 0: continue
                if not (-34.7 < lat < -34.5 and -58.5 < lon < -58.3): continue 
                
                # Hybrid Logic: Popup with HTML Button triggers JS function defined in UI
                popup_html = f"""
                <div style='min-width: 200px; font-family: sans-serif; font-size: 14px;'>
                    <strong style='color: #1e40af;'>{clase}</strong><br>
                    <span style='color: #666;'>{tipo}</span><br>
                    <div style='margin-top: 4px; font-size: 12px;'>
                        {addr}<br>
                        <em>{barrio}</em>
                    </div>
                    <button class="folium_btn" onclick="parent.selectAd('{ad_id}')">
                        📊 Ver Análisis
                    </button>
                </div>
                """
                
                color = '#dc2626' if clase == 'Cartelera' else '#2563eb'
                
                folium.CircleMarker(
                    location=[lat, lon],
                    radius=6,
                    color=color,
                    fill=True,
                    fill_color=color,
                    fill_opacity=0.7,
                    weight=1,
                    popup=folium.Popup(popup_html, max_width=300)
                ).add_to(marker_cluster)
                
                marker_count += 1
                
            except Exception as e:
                continue
        
        # Add Ads layer to map
        fg_ads.add_to(m)
        
        # Add Layer Control to toggle layers
        folium.LayerControl(collapsed=True).add_to(m)
        
        logger.info(f"Generated Folium map with {marker_count} markers")
        return shiny_HTML(m._repr_html_())

    @output
    @render.text 
    def map_header():
        count = len(filtered_data())
        sel = selected_ad.get()
        txt = f"Mapa de Anuncios ({count} visibles)"
        if sel:
            txt += f" - Seleccionado: {sel}"
        return txt

    # --- Detail Logic ---
    @reactive.calc
    def ad_details_data():
        ad_id = selected_ad.get()
        if not ad_id: return None
        
        try:
            con = duckdb.connect(database=":memory:")
            df = con.execute(f"SELECT * FROM '{DATA_PATH}' WHERE nro_anuncio = ?", [ad_id]).df()
            con.close()
            if df.empty: return None
            return df.iloc[0]
        except Exception as e:
            logger.error(f"Error fetching details: {e}")
            return None

    @output
    @render.ui
    def ad_metadata():
        row = ad_details_data()
        if row is None: return div("Seleccione un anuncio en el mapa")
        
        def item(label, val):
            return div(strong(f"{label}: "), str(val), style="margin-bottom: 4px;")
            
        return div(
            item("ID", row['nro_anuncio']),
            item("Dirección", row['full_address']),
            item("Barrio", row['barrio_desc']),
            item("Comuna", row['comuna_desc']),
            item("Zonificación", row.get('distrito_desc', 'N/A')),
            item("Clase", row['clase']),
            item("Tipo", row['tipo']),
            item("Característica", row['caracteristica']),
            item("Metros", f"{row['metros']} m²"),
            style="font_size: 0.9em;"
        )

    @output
    @render.ui
    def reach_chart():
        row = ad_details_data()
        if row is None: return None
        
        # Parse logic for Reach columns (same as before)
        keys = row.index.tolist()
        import re
        regex = re.compile(r"(hombres|mujeres)_(residentes|circulante)_age_(.*)_1ring")
        
        data_points = []
        for k in keys:
            match = regex.match(k)
            if match:
                sexo = match.group(1).capitalize()
                tipo_pob = match.group(2).capitalize()
                edad = match.group(3).replace('_', ' ')
                valor = row[k]
                
                if valor > 0:
                    data_points.append({
                        "Edad": edad,
                        "Población": valor,
                        "Grupo": f"{tipo_pob} ({sexo})"
                    })
        
        if not data_points:
            return div("No hay datos demográficos pormenorizados para este punto.")
            
        df_plot = pd.DataFrame(data_points)
        
        # Obtenemos el total para el título HTML
        total_reach = int(row.get('total_reach_1ring', 0))

        fig = px.bar(
            df_plot, 
            x="Edad", 
            y="Población", 
            color="Grupo", 
            # title=...  <-- ELIMINAMOS EL TÍTULO INTERNO DE PLOTLY
            labels={"Población": "Personas", "Edad": "Rango Etario"},
            category_orders={"Edad": sorted(df_plot["Edad"].unique()) if not df_plot.empty else []},
            template="plotly_dark" if input.dark_mode() == "dark" else "plotly"
        )
        
        fig.update_layout(
            barmode='stack', 
            # Ajustamos márgenes ya que no hay título ocupando espacio arriba
            margin=dict(l=10, r=10, t=30, b=10), 
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        
        # Retornamos un DIV con el Título HTML arriba y el Gráfico abajo
        return div(
            ui.h4(f"Total: {total_reach:,} personas", style="text-align: center; margin-bottom: 10px; margin-top: 5px;"),
            shiny_HTML(fig.to_html(include_plotlyjs=False, full_html=False, config={'displayModeBar': False}))
        )

app = App(app_ui, server)