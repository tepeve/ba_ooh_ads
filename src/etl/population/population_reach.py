# https://github.com/EL-BID/Matriz-Origen-Destino-Transporte-Publico/tree/main
# https://github.com/EL-BID/UrbanTrips
# https://data.buenosaires.gob.ar/dataset/viajes-etapas-transporte-publico

# estimación de la población alcanzada por cada h3 donde está emplazado un aviso de vía pública
# distintas capas de análisis:
# Población residente según Censo de Población y Vivienda 2022 - INDEC
# Población circulante según datos de movilidad en transporte público (datos de SUBE en CABA)

# Imports y carga
import h3
import pandas as pd
import geopandas as gpd
from pathlib import Path
import folium
from folium.plugins import MarkerCluster
import os, sys
import requests
from io import BytesIO
import logging
import duckdb

from shapely.geometry import Polygon, MultiPolygon
from h3 import LatLngPoly

from utils.utils_spatial import add_h3_index
from src.config import settings


# Configuración de Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def load_trips_data(url: str) -> pd.DataFrame:
    """
    Carga el dataset de etapas de viaje desde la URL definida.
    Marca viajes que inician o terminan en CABA.
    Agrega columnas con índices H3 de origen y destino.
    """
    # Descarga robusta a disco para evitar IncompleteRead
    filename = url.split('/')[-1]
    local_path = settings.EXTERNAL_DIR / filename
    
    if not local_path.exists():
        logger.info(f"Descargando datos de etapas de viaje desde: {url}")
        settings.EXTERNAL_DIR.mkdir(parents=True, exist_ok=True)
        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            with open(local_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192): 
                    f.write(chunk)
    else:
        logger.info(f"Usando archivo en caché: {local_path}")

    logger.info(f"Leyendo CSV...")
    df_etapas = pd.read_csv(local_path)
    
    # armo flags para identificar viajes que inician o terminan en CABA usando el código de dpto censal que viene en el dataset
    df_etapas["origen_caba"] = df_etapas.departamento_origen_viaje.between(2000,5999)
    df_etapas["destino_caba"] = df_etapas.departamento_destino_viaje.between(2000,5999)

    # Agregamos índices H3 de origen y destino
    df_etapas['origen_h3r10'] = add_h3_index(df_etapas, lat_col='latitud_origen_viaje', lon_col='longitud_origen_viaje', resolution=settings.H3_RESOLUTION,inplace=False)
    df_etapas['destino_h3r10'] = add_h3_index(df_etapas, lat_col='latitud_destino_viaje', lon_col='longitud_destino_viaje', resolution=settings.H3_RESOLUTION,inplace=False)
    
    df_etapas['origen_h3r9'] = df_etapas['origen_h3r10'].apply(lambda x: h3.cell_to_parent(x, settings.H3_RESOLUTION) if pd.notna(x) else None)
    df_etapas['destino_h3r9'] = df_etapas['destino_h3r10'].apply(lambda x: h3.cell_to_parent(x, settings.H3_RESOLUTION) if pd.notna(x) else None)

    return df_etapas

def aggregate_trips_by_h3(df_etapas: pd.DataFrame) -> pd.DataFrame:
    """
    Agrega las etapas de viaje por hexágono H3 de origen y destino, desagregando por edad y género.
    Normaliza los tramos de edad para coincidir con el formato censal (ej: '20 A 24').
    """
    
    # 1. Normalización de Tramos de Edad (Float -> String INDEC)
    def _normalizar_edad(valor):
        if pd.isna(valor):
            return 'Desconocido'
        
        try:
            val_int = int(valor)
            if val_int >= 100:
                return '100 Y MÁS'
            # Formateamos con dos dígitos (00, 05) para coincidir con '00 A 04'
            return f"{val_int:02d} A {val_int+4:02d}"
        except ValueError:
            return 'Desconocido'

    # Aplicamos la transformación si existe la columna, sino creamos default
    if 'grupo_edad' in df_etapas.columns:
        df_etapas['tramo_edad'] = df_etapas['grupo_edad'].apply(_normalizar_edad)
    else:
        logger.warning("Columna 'grupo_edad' no encontrada. Se usará 'Desconocido'.")
        df_etapas['tramo_edad'] = 'Desconocido'

    # Aseguramos columna de género
    if 'genero' not in df_etapas.columns:
        df_etapas['genero'] = 'Desconocido'

    # Filtramos datos válidos básicos
    df_etapas = df_etapas.dropna(subset=['origen_caba','destino_caba', 'id_tarjeta', 'factor_expansion_viaje'])

    # 2. Transformación a formato largo (Long Format)
    # Conservamos 'tramo_edad' (ya normalizado) y 'genero'
    cols_to_keep = ['id_tarjeta', 'factor_expansion_viaje', 'genero', 'tramo_edad']
    
    df_etapas_long = pd.concat([
        df_etapas[['origen_h3r9', 'origen_caba'] + cols_to_keep].rename(columns={'origen_h3r9': 'h3_index','origen_caba':'in_caba'}),
        df_etapas[['destino_h3r9', 'destino_caba'] + cols_to_keep].rename(columns={'destino_h3r9': 'h3_index', 'destino_caba':'in_caba'})
    ], ignore_index=True)

    # Filtramos solo hexágonos dentro de CABA
    df_etapas_long = df_etapas_long[df_etapas_long['in_caba']]
    df_etapas_long = df_etapas_long.drop(columns=['in_caba'])

    # 3. Deduplicación
    # Una persona cuenta 1 vez en el hexágono por tramo/género
    df_unique = df_etapas_long.drop_duplicates(subset=['h3_index', 'id_tarjeta']).copy()

    # 4. Estandarización de Género (F->mujeres, M->hombres)
    df_unique['genero_norm'] = df_unique['genero'].map({
        'F': 'mujeres_circulante', 
        'M': 'hombres_circulante'
    }).fillna('otros_circulante')

    # 5. Agregación
    df_agg = df_unique.groupby(['h3_index', 'tramo_edad', 'genero_norm'])['factor_expansion_viaje'].sum().reset_index()

    # 6. Pivot para columnas finales
    df_pivot = df_agg.pivot(index=['h3_index', 'tramo_edad'], columns='genero_norm', values='factor_expansion_viaje').fillna(0)
    
    df_pivot.columns.name = None
    df_pivot = df_pivot.reset_index()
    
    # Calcular total
    cols_metricas = [c for c in df_pivot.columns if 'circulante' in c]
    df_pivot['total_circulante'] = df_pivot[cols_metricas].sum(axis=1).astype(int)
    
    # Asegurar tipos enteros
    for col in cols_metricas:
        df_pivot[col] = df_pivot[col].astype(int)

    return df_pivot

def create_h3_grid():
     
    """Función principal para agregar población residente por hexágono H3."""
    
    # obtenemos límites de la ciudad de buenos aires para recortar hexagonos
    import osmnx as ox
    gdf_caba = ox.geocode_to_gdf('Ciudad Autónoma de Buenos Aires, Argentina')
    gdf_caba = gdf_caba.to_crs(epsg=4326)  # Asegurar CRS WGS84


    geom = gdf_caba.geometry.iloc[0]

    # H3 v4: polygon_to_cells espera LatLngPoly (no GeoJSON dict)
    def _poly_to_latlngpoly(poly: Polygon) -> LatLngPoly:
        outer = [(lat, lon) for lon, lat in poly.exterior.coords]
        holes = [
            [(lat, lon) for lon, lat in ring.coords]
            for ring in poly.interiors
        ]
        return LatLngPoly(outer, holes)

    hexs = set()
    if isinstance(geom, MultiPolygon):
        polys = list(geom.geoms)
    else:
        polys = [geom]

    for poly in polys:
        hexs.update(h3.polygon_to_cells(_poly_to_latlngpoly(poly), settings.H3_RESOLUTION))


    # creamos la grilla de indices H3 que cubren CABA
    # hexs = h3.polygon_to_cells(gdf_caba.geometry.iloc[0].__geo_interface__, H3RESOL)
    # llevamos los indices a poligonos
    # H3 v4 devuelve (lat, lon), shapely necesita (lon, lat)
    polygonise = lambda hex_id: Polygon(
                                [(lng, lat) for lat, lng in h3.cell_to_boundary(hex_id)]
                                )
    all_polys = gpd.GeoSeries(list(map(polygonise, hexs)), \
                                      index=hexs, \
                                      crs="EPSG:4326" \
                                     )
    
    h3_all = gpd.GeoDataFrame({"geometry": all_polys,
                                 "h3_index": all_polys.index},
                                crs=all_polys.crs
                               )

   # vamos a hacer una interpolación diasimétrica entre radios censales y hexágonos H3
    
    # cargamos radios censales como geoDataFrame
    radios_censales = gpd.read_parquet(settings.EXTERNAL_DIR / "radios_censales.parquet")
    
    h3_land = gpd.overlay(h3_all, 
                            radios_censales.to_crs(h3_all.crs), 
                            how="intersection"
                           )
    
    return h3_land, radios_censales



def add_intersection_area_proportions(h3_land: gpd.GeoDataFrame,
                                      radios_censales: gpd.GeoDataFrame,
                                      radio_id_col: str,
                                      metric_col: str = None,                                      
                                      projected_crs: int = 3857) -> gpd.GeoDataFrame:
    """
    Añade a h3_land:
      - intersect_area_m2: área de la intersección en m2
      - radio_area_m2: área del radio censal padre en m2 (mapeada desde radios_censales)
      - prop_to_radio: proporción = intersect_area_m2 / radio_area_m2
      - allocated_<metric_col>: si metric_col se pasa, crea la columna con la parte asignada


    radio_id_col: nombre de la columna que identifica el radio en radios_censales y en h3_land.
    projected_crs: CRS proyectado para calcular áreas (por defecto EPSG:3857).
    """
    # reproyectar a sistema métrico
    radios_p = radios_censales.to_crs(epsg=projected_crs).copy()
    h3_p = h3_land.to_crs(epsg=projected_crs).copy()

    # asegurar geometrías válidas si hay problemas topológicos
    radios_p['geometry'] = radios_p['geometry'].buffer(0)
    h3_p['geometry'] = h3_p['geometry'].buffer(0)

    # áreas
    radios_p['radio_area_m2'] = radios_p.geometry.area
    h3_p['intersect_area_m2'] = h3_p.geometry.area

    # preparar mapa de área por radio
    radio_area_map = radios_p.set_index(radio_id_col)['radio_area_m2'].to_dict()

    # mapear el área del radio padre a cada intersección (asegurar que radio_id_col exista en h3_p)
    h3_p['radio_area_m2'] = h3_p[radio_id_col].map(radio_area_map)

    # proporción (cuidado con radios de área 0)
    h3_p['prop_to_radio'] = h3_p['intersect_area_m2'] / h3_p['radio_area_m2']
    h3_p['prop_to_radio'] = h3_p['prop_to_radio'].fillna(0)

        # opcional: repartir un metric_col del radio al h3
    if metric_col:
        # si overlay ya trajo metric_col, usarlo; si no, mapear desde radios_p
        if metric_col in h3_p.columns:
            h3_p[f'allocated_{metric_col}'] = h3_p[metric_col] * h3_p['prop_to_radio']
        else:
            metric_map = radios_p.set_index(radio_id_col)[metric_col].to_dict()
            h3_p[f'allocated_{metric_col}'] = h3_p[radio_id_col].map(metric_map) * h3_p['prop_to_radio']

    # devolver en CRS original de h3_land (geom original) si se desea
    return h3_p.to_crs(h3_land.crs)

def load_ct_population_data(dct_data_link: str, METRIC_COL: str):
    """
    Descarga y procesa datos censales de población por tramo etario en cada radio censal y 
    se proyecta la composición de hombres y mujeres tomando las tasas de feminidad de CABA en el Censo 2022.
    Retorna un DataFrame con columnas: id_geo, tramo_edad, 

    """

    # Descargamos data censal desde S3 usando DuckDB
    #  Configurar DuckDB
    con = duckdb.connect()
    for cmd in [
        "INSTALL spatial",
        "LOAD spatial", 
        "INSTALL httpfs",
        "LOAD httpfs"
    ]:
        con.execute(cmd)


    query_age = """
    SELECT 
        id_geo AS cod_indec,
        etiqueta_categoria as tramo_edad,
        SUM(conteo) AS total_conteo
    FROM 's3://arg-fulbright-data/censo-argentino-2022/censo-2022-largo.parquet'
    WHERE codigo_variable = 'PERSONA_EDADQUI'
    AND valor_provincia = '02'
    GROUP BY id_geo, etiqueta_categoria
    ORDER BY id_geo, etiqueta_categoria;
    """

    census_age = con.execute(query_age).fetchdf()


    # Ahora vamos a proyectar la cantidad de hombres y mujeres por tramo etario 
    # usando las tasas de feminidad en CABA para el Censo 2022.
    # https://censo.gob.ar/index.php/datos_definitivos_caba/
    # DataFrame de Tasas de Feminidad (Armado a mano con los datos del archivo)
    # https://censo.gob.ar/wp-content/uploads/2023/11/c2022_caba_est_c4_1.xlsx

    # Tasas de feminidad por tramo etario en CABA
    data_tasas = {
        'tramo_edad': [
            '00 A 04', '05 A 09', '10 A 14', '15 A 19', '20 A 24', '25 A 29', '30 A 34', '35 A 39',
            '40 A 44', '45 A 49', '50 A 54', '55 A 59', '60 A 64', '65 A 69', '70 A 74',
            '75 A 79', '80 A 84', '85 A 89', '90 A 94', '95 A 99', '100 Y MÁS'
        ],
        'tasa_feminidad': [
            97, 97, 97, 101, 108, 109, 108, 106,
            110, 115, 118, 123, 126, 137, 147,
            163, 187, 223, 290, 370, 557
        ]
    }

    df_tasas = pd.DataFrame(data_tasas)


    # Vamos a recategorizar los tramos de edad más altos de la información de cada radio censal
    # para que coincidan con los datos de tasas de feminidad.
    census_age['tramo_edad'] = census_age['tramo_edad'].replace(
        {'100 A 104': '100 Y MÁS', '105 Y MÁS': '100 Y MÁS'}
    )

    # Group by id_geo and etiqueta_categoria to unify the counts
    census_age = census_age.groupby(['cod_indec', 'tramo_edad'], as_index=False)['total_conteo'].sum()


    # Ahora hacemos un merge de census_age con df_tasas para luego calcular las proyecciones 
    # de hombres y mujeres en cada radio censal y tramo etario.
    census_age_by_gender = census_age.merge(df_tasas, left_on='tramo_edad', right_on='tramo_edad', how='left')

    # Calculamos la cantidad de hombres y mujeres usando la tasa de feminidad
    # Fórmula: Tasa Fem = (Mujeres / Hombres) * 100
    # Total = Mujeres + Hombres
    # Hombres = Total / (1 + (Tasa Fem / 100))
    census_age_by_gender['hombres_float'] = census_age_by_gender['total_conteo'] / (1 + (census_age_by_gender['tasa_feminidad'] / 100))
    # Redondeamos hombres al entero más cercano
    census_age_by_gender['hombres'] = census_age_by_gender['hombres_float'].round().astype(int)
    # Mujeres = Total - Hombres
    census_age_by_gender['mujeres'] = census_age_by_gender['total_conteo'] - census_age_by_gender['hombres']

    # chequeamos que la suma de hombres y mujeres dé el total original en cada radio censal y grupo etario
    check = (census_age_by_gender['hombres'] + census_age_by_gender['mujeres']) == census_age_by_gender['total_conteo']
    print(f"Registros con errores de suma: {len(check) - check.sum()}")

    # Limpieza de columnas auxiliares
    census_age_by_gender = census_age_by_gender.drop(columns=['hombres_float'])    

    return census_age_by_gender

    

def distribute_population_to_h3(h3_land_weighted, census_data, radio_id_col='id_geo'):
    """
    h3_land_weighted: GeoDataFrame que sale de add_intersection_area_proportions
                      Debe tener columnas: 'h3_index', 'cod_indec', 'prop_to_radio'
    census_data: DataFrame que sale de load_ct_population_data
                 Debe tener: 'cod_indec', 'hombres', 'mujeres', 'total_conteo', 'tramo_edad'
    """
    
    # 1. MERGE: Unir la geometría (H3-Radio) con la demografía (Datos del Radio)
    # Esto va a multiplicar las filas: si un radio toca 3 hexágonos, 
    # se triplicarán sus filas de datos censales (una para cada pedazo).
    merged = h3_land_weighted.merge(
        census_data, 
        left_on=radio_id_col, 
        right_on='cod_indec', 
        how='inner' # Solo nos interesan radios con datos y geometría
    )
    
    # 2. DISTRIBUCIÓN (Allocation)
    # Multiplicamos la población total del radio por la proporción de área que cae en este hexágono específico
    cols_to_distribute = ['total_conteo', 'hombres', 'mujeres']
    
    for col in cols_to_distribute:
        # Resultado parcial (flotante): Ej. 3.4 personas de este radio caen en este hexágono
        merged[f'{col}_h3_part'] = merged[col] * merged['prop_to_radio']

    # 3. AGREGACIÓN POR H3
    # Sumamos todos los pedacitos que cayeron en cada hexágono.
    # Agrupamos también por 'tramo_edad' si quieres mantener ese detalle en la celda H3.
    h3_population = merged.groupby(['h3_index', 'tramo_edad'], as_index=False)[[
        'total_conteo_h3_part', 
        'hombres_h3_part', 
        'mujeres_h3_part'
    ]].sum()
    
    # 4. REDONDEO FINAL (Estrategia sugerida)
    # Al sumar pedazos (0.3 personas + 0.4 personas), volvemos a tener decimales.
    # Lo ideal es redondear AL FINAL, por celda H3, para minimizar el error acumulado.
    
    h3_population['hombres_h3'] = h3_population['hombres_h3_part'].round().astype(int)
    
    # Aplicamos de nuevo la lógica del residuo para que cierre la suma en la celda H3
    h3_population['total_h3'] = h3_population['total_conteo_h3_part'].round().astype(int)
    h3_population['mujeres_h3'] = h3_population['total_h3'] - h3_population['hombres_h3']
    
    return h3_population



def integrate_population_data(df_residentes: pd.DataFrame, df_circulante: pd.DataFrame) -> pd.DataFrame:
    """
    Une los datos de población residente (Censo) y circulante (Transporte) por H3 y tramo de edad.
    Calcula el 'Total Reach' sumando ambas poblaciones.
    """
    logger.info("Integrando población residente y circulante...")

    # 1. Estandarizar nombres de claves
    # df_residentes viene con 'h3_index', df_circulante con 'h3_index'
    # df_residentes = df_residentes.rename(columns={'hex_id': 'h3_index'})

    # 2. Renombrar columnas de residentes para mayor claridad antes del merge
    # De 'hombres_h3' a 'hombres_residentes', etc.
    df_residentes = df_residentes.rename(columns={
        'hombres_h3': 'hombres_residentes',
        'mujeres_h3': 'mujeres_residentes',
        'total_h3': 'total_residentes'
    })

    # Seleccionamos solo las columnas finales de residentes (descartamos las _part intermedias)
    cols_residentes = ['h3_index', 'tramo_edad', 'hombres_residentes', 'mujeres_residentes', 'total_residentes']
    df_residentes = df_residentes[cols_residentes]

    # 3. Merge Outer
    # Usamos outer porque puede haber hexágonos con residentes pero sin paradas de bondi, y viceversa.
    df_final = pd.merge(
        df_residentes,
        df_circulante,
        on=['h3_index', 'tramo_edad'],
        how='outer'
    )

    # 4. Llenar NaNs con 0
    # Las columnas numéricas que quedaron vacías tras el merge son ceros lógicos
    cols_numericas = [
        'hombres_residentes', 'mujeres_residentes', 'total_residentes',
        'hombres_circulante', 'mujeres_circulante', 'total_circulante', 'otros_circulante'
    ]
    
    # Solo llenamos las que existen (por si 'otros_circulante' no se generó)
    cols_a_llenar = [c for c in cols_numericas if c in df_final.columns]
    df_final[cols_a_llenar] = df_final[cols_a_llenar].fillna(0)

    # 5. Calcular Total Reach (Residente + Circulante)
    # Si no existe 'otros_circulante', asumimos 0
    otros = df_final['otros_circulante'] if 'otros_circulante' in df_final.columns else 0

    df_final['hombres_total_reach'] = df_final['hombres_residentes'] + df_final['hombres_circulante']
    df_final['mujeres_total_reach'] = df_final['mujeres_residentes'] + df_final['mujeres_circulante']
    
    # El total general incluye hombres, mujeres y 'otros' (si hubiera en circulante)
    df_final['total_reach'] = df_final['total_residentes'] + df_final['total_circulante']

    # Convertir a enteros para optimizar espacio
    cols_finales_num = cols_a_llenar + ['hombres_total_reach', 'mujeres_total_reach', 'total_reach']
    for col in cols_finales_num:
        df_final[col] = df_final[col].astype(int)

    return df_final


def run_reach():
    # Cargar y procesar datos de etapas de viaje
    df_etapas = load_trips_data(settings.ETAPAS_URL)
    df_trips_agg = aggregate_trips_by_h3(df_etapas)

    # Crear grilla H3 y preparar geometrías
    h3_land, radios_censales = create_h3_grid()

    # Añadir proporciones de intersección
    h3_land_weighted = add_intersection_area_proportions(
        h3_land, 
        radios_censales, 
        radio_id_col='cod_indec',
        metric_col=None
    )

    # Cargar datos censales de población por tramo etario y género
    census_data = load_ct_population_data(
        dct_data_link=None,
        METRIC_COL='total_conteo'
    )

    # Distribuir población a hexágonos H3
    h3_population = distribute_population_to_h3(
        h3_land_weighted,
        census_data,
        radio_id_col='cod_indec'
    )

    # Integración de los datos de población residente y circulante
    df_final_reach = integrate_population_data(h3_population, df_trips_agg)

    # Guardar resultados
    output_path = settings.PROCESSED_DIR / "population_reach_h3.parquet"
    df_final_reach.to_parquet(output_path)
    logger.info(f"✅ Población alcanzada (Residente + Circulante) guardada en {output_path}")
    logger.info(f"Columnas generadas: {df_final_reach.columns.tolist()}")


if __name__ == "__main__":
    run_reach()