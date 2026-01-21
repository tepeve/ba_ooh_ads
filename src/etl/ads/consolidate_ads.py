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
    df_ads = pd.read_parquet(settings.PROCESSED_DIR / "anuncios_geolocalizados.parquet")
    
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
        df_cl_global = pd.read_parquet(settings.PROCESSED_DIR / "ads_clusters_global.parquet")
        # Asumiendo que mantiene el índice original o tiene columnas comunes.
        # Vamos a hacer un merge por índice si es posible, o spatial si no.
        # Simplificación: Si ads_clusters_global es una copia de ads con la col 'cluster',
        # extraemos solo esa columna y la pegamos.
        
        # Renombrar para evitar colisiones
        if 'cluster' in df_cl_global.columns:
            # Asumimos alineación por índice si el orden no cambió, o usamos merge si hay ID
            # Para seguridad, usaremos el índice del dataframe
            df_ads['cluster_global'] = df_cl_global['cluster']
        
        df_cl_tematicos = pd.read_parquet(settings.PROCESSED_DIR / "ads_clusters_tematicos.parquet")
        if 'cluster_special' in df_cl_tematicos.columns:
            df_ads['cluster_tematico'] = df_cl_tematicos['cluster_special']
            df_ads['macro_category'] = df_cl_tematicos['macro_category']
            
    except Exception as e:
        logger.warning(f"No se pudieron integrar los clusters: {e}")

    # 3. Procesar Población (Wide + K-Ring)
    df_pop_wide = load_and_pivot_population(settings.PROCESSED_DIR / "population_reach_h3.parquet")
    
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
    output_path = settings.PROCESSED_DIR / "tablero_anuncios_consolidado.parquet"
    df_final.to_parquet(output_path, index=False)
    logger.info(f"✅ Archivo listo para Shiny: {output_path}")

if __name__ == "__main__":
    consolidate_data()
