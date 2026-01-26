import pandas as pd
import geopandas as gpd
import h3
import logging
from pathlib import Path
import numpy as np
from src.config import settings

# Configuración de Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)



def load_and_pivot_population(pop_path: Path) -> pd.DataFrame:
    """
    Carga la población y la pivotea para tener 1 fila por H3 y columnas por métricas.
    Genera métricas detalladas por:
      - Tipo: Residente / Circulante / Total (Reach)
      - Sexo: Hombres / Mujeres / Total
      - Edad: Tramos etarios
    """
    logger.info("Cargando y pivoteando datos de población detallados...")
    df_pop = pd.read_parquet(pop_path)
    
    # 1. Totales Generales por H3 (Suma de todas las edades)
    # Definimos métricas base para agrupar (totales por h3 sin distinguir edad)
    metrics_base = [
        # Totales Residentes
        'hombres_residentes', 'mujeres_residentes', 'total_residentes',
        # Totales Circulantes
        'hombres_circulante', 'mujeres_circulante', 'total_circulante', 
        # Si existe otros_circulante lo incluimos
        'otros_circulante',
        # Totales Combinados (Reach)
        'hombres_total_reach', 'mujeres_total_reach', 'total_reach'
    ]
    # Filtrar solo las que existen en el df
    existing_metrics = [c for c in metrics_base if c in df_pop.columns]
    
    df_h3_total = df_pop.groupby('h3_index')[existing_metrics].sum().reset_index()
    
    # 2. Pivoteo por Tramo de Edad
    # Queremos generar columnas tipo: 'residentes_hombres_age_20_A_24', etc.
    
    # Lista de valores a pivotear (métricas desagregadas por edad)
    values_to_pivot = [
        # Queremos detalle por edad para residentes y circulantes separados por sexo
        'hombres_residentes', 'mujeres_residentes', 
        'hombres_circulante', 'mujeres_circulante',
        # Y también el total combinado si se quiere
        'total_reach', 'hombres_total_reach', 'mujeres_total_reach'
    ]
    existing_pivot_values = [c for c in values_to_pivot if c in df_pop.columns]
    
    # Pivot TABLE
    # Index: h3_index
    # Columns: tramo_edad
    # Values: [metricas...]
    df_pivot = df_pop.pivot_table(
        index='h3_index', 
        columns='tramo_edad', 
        values=existing_pivot_values, 
        aggfunc='sum',
        fill_value=0
    )
    
    # El pivot table crea un MultiIndex en columnas (Métrica, Edad)
    # Lo aplanamos: {Métrica}_age_{Edad}
    # Ejemplo: hombres_residentes_age_20_A_24
    new_columns = []
    for metric, age in df_pivot.columns:
        # Limpiar edad (ej: "20 A 24" -> "20_A_24")
        age_clean = str(age).replace(' ', '_')
        new_columns.append(f"{metric}_age_{age_clean}")
    
    df_pivot.columns = new_columns
    df_pivot = df_pivot.reset_index()
    
    # 3. Join Final
    # Hacemos merge del resumen total con el desglose por edades
    df_wide = pd.merge(df_h3_total, df_pivot, on='h3_index', how='left')
    
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
        neighbors = h3.grid_disk(center_h3, k)
        
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
    anuncios_path = settings.PROCESSED_DIR / "anuncios_geolocalizados.parquet"
    if not anuncios_path.exists():
        raise FileNotFoundError(f"No se encontró: {anuncios_path}")
        
    df_ads = pd.read_parquet(anuncios_path)
    
    # Validamos que existe nro_anuncio para el merge
    if 'nro_anuncio' not in df_ads.columns:
        raise ValueError("El dataset de anuncios no tiene 'nro_anuncio'.")
    if 'h3_index' not in df_ads.columns:
        logger.warning("Falta h3_index, necesario para población.")

    logger.info("Integrando clusters...")
    
    # --- PROCESAMIENTO CLUSTERS GLOBAL ---
    # Estrategia: Tomar el primer cluster asignado (asumiendo unicidad espacial o prioridad)
    try:
        path_global = settings.PROCESSED_DIR / "ads_clusters_global.parquet"
        if path_global.exists():
            df_g = pd.read_parquet(path_global)
            if 'nro_anuncio' in df_g.columns and 'cluster' in df_g.columns:
                df_g_agg = df_g.groupby('nro_anuncio')['cluster'].first().reset_index()
                df_g_agg = df_g_agg.rename(columns={'cluster': 'cluster_global'})
                
                df_ads = pd.merge(df_ads, df_g_agg, on='nro_anuncio', how='left')
                logger.info("Clusters globales integrados.")
            else:
                logger.warning("Faltan columnas clave en ads_clusters_global")
                df_ads['cluster_global'] = None
        else:
            df_ads['cluster_global'] = None
    except Exception as e:
        logger.error(f"Error clusters globales: {e}")
        df_ads['cluster_global'] = None

    # --- PROCESAMIENTO CLUSTERS TEMATICOS (Listas 1-a-N) ---
    # Estrategia: Agrupar en listas valores únicos de categorías y clusters
    try:
        path_tematicos = settings.PROCESSED_DIR / "ads_clusters_tematicos.parquet"
        if path_tematicos.exists():
            df_t = pd.read_parquet(path_tematicos)
            if 'nro_anuncio' in df_t.columns:
                agg_rules = {}
                if 'cluster_special' in df_t.columns:
                    # set() para eliminar duplicados, list() para compatibilidad parquet
                    agg_rules['cluster_special'] = lambda x: list(set(x))
                if 'macro_category' in df_t.columns:
                    agg_rules['macro_category'] = lambda x: list(set(x))
                
                if agg_rules:
                    df_t_agg = df_t.groupby('nro_anuncio').agg(agg_rules).reset_index()
                    
                    rename_map = {}
                    if 'cluster_special' in df_t_agg.columns:
                        rename_map['cluster_special'] = 'cluster_tematico'
                    
                    df_t_agg = df_t_agg.rename(columns=rename_map)
                    
                    df_ads = pd.merge(df_ads, df_t_agg, on='nro_anuncio', how='left')
                    logger.info("Clusters temáticos integrados (modo lista).")
                else:
                    df_ads['cluster_tematico'] = None
                    df_ads['macro_category'] = None
            else:
                 logger.warning("Falta nro_anuncio en ads_clusters_tematicos")
                 df_ads['cluster_tematico'] = None
                 df_ads['macro_category'] = None
        else:
            df_ads['cluster_tematico'] = None
            df_ads['macro_category'] = None
    except Exception as e:
        logger.error(f"Error clusters temáticos: {e}")
        df_ads['cluster_tematico'] = None
        df_ads['macro_category'] = None

    # Normalizar columnas faltantes
    for col in ['cluster_global', 'cluster_tematico', 'macro_category']:
        if col not in df_ads.columns:
            df_ads[col] = None

    # 3. Procesar Población (Wide + K-Ring)
    try:
        pop_path = settings.PROCESSED_DIR / "population_reach_h3.parquet"
        if pop_path.exists() and 'h3_index' in df_ads.columns:
            df_pop_wide = load_and_pivot_population(pop_path)
            df_reach_kring = calculate_kring_reach(df_pop_wide, k=1)
            
            rename_map = {c: f"{c}_1ring" for c in df_reach_kring.columns if c != 'h3_index'}
            df_reach_kring = df_reach_kring.rename(columns=rename_map)

            logger.info("Uniendo métricas de alcance...")
            df_final = pd.merge(df_ads, df_reach_kring, on='h3_index', how='left')
            
            # Llenar nulos de métricas con 0
            cols_reach = list(rename_map.values())
            df_final[cols_reach] = df_final[cols_reach].fillna(0)
        else:
            logger.warning("Saltando población (archivo faltante o sin h3_index).")
            df_final = df_ads
            
    except Exception as e:
        logger.error(f"Error procesando población: {e}")
        df_final = df_ads

    if 'h3_index' in df_final.columns:
        df_final = df_final.drop(columns=['h3_index'])

    # 5. Guardar
    logger.info(f"Guardando consolidado: {len(df_final)} filas.")
    output_path = settings.PROCESSED_DIR / "tablero_anuncios_consolidado.parquet"
    df_final.to_parquet(output_path, index=False)
    logger.info(f"✅ Archivo listo: {output_path}")
if __name__ == "__main__":
    consolidate_data()
