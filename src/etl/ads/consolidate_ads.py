import pandas as pd
import geopandas as gpd
import h3
import logging
from pathlib import Path
import numpy as np

# Configuración de Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Rutas
PROCESSED_DATA_DIR = Path("data/processed")

ADS_PATH = PROCESSED_DATA_DIR / "anuncios_geolocalizados.parquet"
# columnas relevantes: 
# nro_anuncio, estado_anuncio, 
# clase, tipo, carateristica, metros
# fecha_alta_anuncio
# calle_nombre_norm, calle_altura, nombre(barrio),comuna_left, ciudad, pais
# distrito, distrito_simply, distrito_desc (no se porqué están todas en missing)
# needs_geocoding, lat, long, h3_index

POPULATION_PATH = PROCESSED_DATA_DIR / "population_reach_h3.parquet"
# columnas relevantes:
# h3_index, 
# tramo_edad, hombres_residentes, mujeres_residentes, total_residentes
# hombres_cirulantes, mujeres_circulantes, total_circulantes (hay otros_circulante, qué onda?)
# hombres_total_reach, mujeres_total_reach, total_reach

CLUSTERS_GLOBAL_PATH = PROCESSED_DATA_DIR / "ads_clusters_global.parquet"
# nro_anuncio (ojo que puede estar repetido porque el ads puede pertenecer a varios clusters)
# cluster (ojo que puede haber varios clusters)
# geometry (parece estar roto)

CLUSTERS_THEMATIC_PATH = PROCESSED_DATA_DIR / "ads_clusters_tematicos.parquet"
# 'nro_anuncio', 
# 'h3_index', 'geometry' (parece estar roto)
# 'index_right' (no sé qué es)
# 'macro_category_index', 'cluster_special', 'macro_category'],


OUTPUT_PATH = PROCESSED_DATA_DIR / "tablero_anuncios_consolidado.parquet"



def load_and_pivot_population(pop_path: Path) -> pd.DataFrame:
    """
    Carga la población y la pivotea para tener 1 fila por H3 y columnas por métricas.
    """
    logger.info("Cargando y pivoteando datos de población...")
    df_pop = pd.read_parquet(pop_path)
    
    # Agrupamos primero por H3 para tener el total absoluto del hexágono
    # (Sumamos todos los tramos de edad)
    df_h3_total = df_pop.groupby('h3_index')[['total_reach', 'hombres_total_reach', 'mujeres_total_reach']].sum().reset_index()
    
    # Para los tramos de edad, hacemos un pivot
    # Queremos columnas como: 'total_reach_20_A_24', 'total_reach_25_A_29', etc.
    df_pivot_age = df_pop.pivot_table(
        index='h3_index', 
        columns='tramo_edad', 
        values='total_reach', 
        aggfunc='sum',
        fill_value=0
    )
    # Aplanar nombres de columnas
    df_pivot_age.columns = [f"age_{c.replace(' ', '_')}" for c in df_pivot_age.columns]
    df_pivot_age = df_pivot_age.reset_index()
    
    # Unimos totales con desglose por edad
    df_wide = pd.merge(df_h3_total, df_pivot_age, on='h3_index', how='left')
    
    return df_wide

def calculate_kring_reach(df_pop_wide: pd.DataFrame, k: int = 1) -> pd.DataFrame:
    """
    Para cada H3 en el dataset, calcula la suma de métricas de él mismo + sus vecinos (k-ring).
    Esto simula el área de influencia visual del anuncio.
    """
    logger.info(f"Calculando alcance espacial (K-Ring={k})...")
    
    # Convertimos el df a un diccionario para búsqueda rápida {h3: {col: val}}
    # Es más rápido que hacer self-joins espaciales masivos
    pop_dict = df_pop_wide.set_index('h3_index').to_dict('index')
    
    # Columnas numéricas a sumar
    cols_to_sum = [c for c in df_pop_wide.columns if c != 'h3_index']
    
    # Lista para guardar resultados
    results = []
    
    # Iteramos sobre cada hexágono que tiene datos
    # Nota: Si un anuncio cae en un hexágono SIN población registrada, no aparecerá aquí.
    # Eso se maneja en el merge final.
    all_h3_indices = list(pop_dict.keys())
    
    for center_h3 in all_h3_indices:
        # Obtener vecinos (incluye el central)
        neighbors = h3.k_ring(center_h3, k)
        
        # Inicializar acumuladores
        sums = {col: 0 for col in cols_to_sum}
        
        # Sumar valores de vecinos si existen en el diccionario
        for neighbor in neighbors:
            if neighbor in pop_dict:
                data = pop_dict[neighbor]
                for col in cols_to_sum:
                    sums[col] += data[col]
        
        # Guardar resultado
        sums['h3_index'] = center_h3
        results.append(sums)
        
    return pd.DataFrame(results)

def consolidate_data():
    # 1. Cargar Anuncios (Base)
    logger.info("Cargando anuncios...")
    df_ads = pd.read_parquet(ADS_PATH)
    
    # Asegurar que tenemos h3_index (generado en transform_ads.py)
    if 'h3_index' not in df_ads.columns:
        raise ValueError("El dataset de anuncios no tiene la columna 'h3_index'. Ejecuta transform_ads.py primero.")

    # 2. Cargar Clusters (Centralidades)
    # Asumimos que estos parquets tienen un ID de anuncio o geometría para unir.
    # Si tus scripts de clustering guardaron 'ads_clusters_*.parquet' con el índice original o un ID, úsalo.
    # Si guardaron solo geometría, habría que hacer spatial join de nuevo.
    # REVISANDO TU CÓDIGO ANTERIOR: 'assign_clusters_to_ads' hace sjoin.
    # Asumiremos que el parquet de clusters tiene las columnas del anuncio original + 'cluster'.
    
    # Estrategia: Cargar solo las columnas de cluster e ID (o índice) para pegar a df_ads
    # Si df_ads no tiene ID único, usaremos el índice.
    
    logger.info("Integrando clusters...")
    try:
        df_cl_global = pd.read_parquet(CLUSTERS_GLOBAL_PATH)
        # Asumiendo que mantiene el índice original o tiene columnas comunes.
        # Vamos a hacer un merge por índice si es posible, o spatial si no.
        # Simplificación: Si ads_clusters_global es una copia de ads con la col 'cluster',
        # extraemos solo esa columna y la pegamos.
        
        # Renombrar para evitar colisiones
        if 'cluster' in df_cl_global.columns:
            # Asumimos alineación por índice si el orden no cambió, o usamos merge si hay ID
            # Para seguridad, usaremos el índice del dataframe
            df_ads['cluster_global'] = df_cl_global['cluster']
        
        df_cl_tematicos = pd.read_parquet(CLUSTERS_THEMATIC_PATH)
        if 'cluster_special' in df_cl_tematicos.columns:
            df_ads['cluster_tematico'] = df_cl_tematicos['cluster_special']
            df_ads['macro_category'] = df_cl_tematicos['macro_category']
            
    except Exception as e:
        logger.warning(f"No se pudieron integrar los clusters: {e}")

    # 3. Procesar Población (Wide + K-Ring)
    df_pop_wide = load_and_pivot_population(POPULATION_PATH)
    
    # Calculamos el alcance ampliado (K=1 -> ~300m radio)
    df_reach_kring = calculate_kring_reach(df_pop_wide, k=1)
    
    # Renombrar columnas para que quede claro que es "Reach" (Alcance)
    # Ej: total_reach -> reach_total_1ring
    rename_map = {c: f"{c}_1ring" for c in df_reach_kring.columns if c != 'h3_index'}
    df_reach_kring = df_reach_kring.rename(columns=rename_map)

    # 4. Merge Final
    logger.info("Uniendo métricas de alcance a los anuncios...")
    df_final = pd.merge(
        df_ads,
        df_reach_kring,
        left_on='h3_index',
        right_on='h3_index',
        how='left'
    )
    
    # Llenar nulos de alcance con 0 (si no hay nadie en el hexágono ni vecinos)
    cols_reach = list(rename_map.values())
    df_final[cols_reach] = df_final[cols_reach].fillna(0)
    
    # Limpieza
    if 'h3_index' in df_final.columns:
        df_final = df_final.drop(columns=['h3_index'])

    # 5. Guardar
    logger.info(f"Guardando dataset consolidado con {len(df_final)} anuncios y {len(df_final.columns)} columnas.")
    df_final.to_parquet(OUTPUT_PATH, index=False)
    logger.info(f"✅ Archivo listo para Streamlit: {OUTPUT_PATH}")

if __name__ == "__main__":
    consolidate_data()
