from pathlib import Path
from shiny import App, ui
from shinywidgets import output_widget, render_widget
import ipyleaflet as L
import duckdb

# Ruta al archivo consolidado (asumiendo que se ejecuta desde la raíz del proyecto o workdir configurado en Docker)
# En Docker, workdir es /app, y data está en /app/data.
DATA_PATH = Path("data/processed/tablero_anuncios_consolidado.parquet")

app_ui = ui.page_fluid(
    ui.h2("BA OOH Ads - Explorer"),
    ui.p("Visualización de anuncios publicitarios y alcance poblacional."),
    
    ui.layout_sidebar(
        ui.sidebar(
            ui.h4("Filtros"),
            ui.markdown("_Cargando datos via DuckDB..._"),
            ui.p("Mostrando muestra de 100 registros")
        ),
        ui.card(
            output_widget("map_output"),
            full_screen=True
        )
    )
)

def server(input, output, session):
    
    @render_widget
    def map_output():
        # 1. Inicializar mapa centrado en Buenos Aires
        center = (-34.6037, -58.3816)
        m = L.Map(center=center, zoom=12, scroll_wheel_zoom=True)
        
        # Capa base limpia (CartoDB Positron)
        carto_layer = L.TileLayer(
            url='https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png',
            attribution='&copy; OpenStreetMap &copy; CARTO'
        )
        m.clear_layers()
        m.add_layer(carto_layer)

        # 2. Cargar datos usando DuckDB
        if not DATA_PATH.exists():
            print(f"Advertencia: No se encontró el archivo {DATA_PATH}. Asegúrate de ejecutar el ETL primero.")
            # Retornar mapa vacío pero funcional
            return m

        try:
            # Conexión en memoria
            con = duckdb.connect(database=":memory:")
            
            # Query eficiente: solo leemos las columnas necesarias para el mapa
            # Limitamos a 100 para prueba de concepto como se solicitó
            query = f"""
                SELECT lat, long
                FROM '{DATA_PATH}'
                WHERE lat IS NOT NULL AND long IS NOT NULL
                LIMIT 100
            """
            
            rows = con.execute(query).fetchall()
            con.close()

            # 3. Generar marcadores
            markers = []
            for lat, lon in rows:
                # Leaflet espera tuplas (lat, lon)
                markers.append(L.Marker(location=(lat, lon), draggable=False))
            
            # Agrupar marcadores para performance y limpieza visual
            cluster = L.MarkerCluster(markers=markers)
            m.add_layer(cluster)
            
            print(f"✅ Cargados {len(rows)} puntos en el mapa desde {DATA_PATH}.")

        except Exception as e:
            print(f"❌ Error consultando DuckDB: {e}")

        return m

app = App(app_ui, server)
