#Importamos librerias
import logging
import os
from pathlib import Path
from venv import logger
import folium
import geopandas as gpd
import pandas as pd
import osmnx as ox
from sklearn.cluster import DBSCAN
import yaml
import numpy as np
from shapely.geometry import Polygon
from concave_hull import concave_hull
from datetime import datetime
from src.config import settings


# References:
# https://scikit-learn.org/stable/modules/generated/sklearn.cluster.DBSCAN.html
# https://github.com/ibelogi/identificar_centralidades/blob/main/02_clustering.ipynb
# https://bitsandbricks.github.io/post/dbscan-machine-learning-para-detectar-centros-de-actividad-urbana/


# Configuración de Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Rutas a archivos procesados (usar settings)
OSM_POIS = settings.PROCESSED_DIR / "osm_pois.parquet"
OSM_POIS_MACROCATEGORIES = settings.PROCESSED_DIR / "osm_pois_categorized.csv"


# definición de parámetros de clustering por macro categoría
params_clustering = {0:{'eps': 200, 
                         'min_samples': 30} ,
                     1: {'eps': 400,
                         'min_samples': 20},
                     2: {'eps': 500, 
                         'min_samples': 40}
                               }




# Funciones para el pipeline de clustering:


# Función principal de preparación de datos para clustering
def dataprep_to_clustering(gdf_osm_pois, osm_macro_categories):
    
    # Unimos gdf_osm_pois con osm_macro_categories para obtener 'macro_category' y 'param_type' para cada POI
    gdf_osm_pois = gdf_osm_pois.merge(osm_macro_categories[['sub_tag', 'macro_category','param_type']], on='sub_tag', how='left')

    # convertimos gdf a una proyeccion metrica para calcular distancias en metros
    gdf_osm_pois['geometry_2'] = gdf_osm_pois.to_crs('EPSG:3857').geometry.centroid
    # Extraemos coordenadas x e y de geometry (lo requiere la api de DBSCAN)
    gdf_osm_pois['x'] = gdf_osm_pois.geometry_2.x
    gdf_osm_pois['y'] = gdf_osm_pois.geometry_2.y
    # ordenamos de norte a sur y de oeste a este
    gdf_osm_pois.sort_values(['x', 'y'], inplace=True)

    # preparamos la matriz de coordenadas
    X = gdf_osm_pois.loc[:,['y','x']].values
    
    return gdf_osm_pois, X



# Función para entrenar DBSCAN y asignar etiquetas ordenadas por tamaño
def train_dbscan(X, gdf_osm_pois, eps=200, min_samples=30, cluster_col='cluster'):
    """Entrena DBSCAN y asigna etiquetas ordenadas por tamaño"""
    dbscan = DBSCAN(eps=eps, min_samples=min_samples, metric='manhattan').fit(X)
    
    gdf_osm_pois[cluster_col] = dbscan.labels_
    etiquetas_clusters = gdf_osm_pois[cluster_col].value_counts().index[gdf_osm_pois[cluster_col].value_counts().index > -1]
    etiquetas_por_tamanio = {k: v for k, v in zip(etiquetas_clusters, range(len(etiquetas_clusters)))}
    gdf_osm_pois[cluster_col] = gdf_osm_pois[cluster_col].replace(etiquetas_por_tamanio)
    
    return gdf_osm_pois


# Función para crear GeoDataFrame de bordes de clusters usando concave hull
def create_gdf_cluster_borders(gdf_osm_pois, cluster_col='cluster', group_cols=['cluster']):
    """Crea polígonos de clusters usando concave hull"""
    gdf_osm_pois['x_y_concat'] = list(zip(gdf_osm_pois['x'], gdf_osm_pois['y']))
    borders = gdf_osm_pois.groupby(group_cols)['x_y_concat'].agg(list).reset_index()
    borders = borders.loc[borders[cluster_col] != -1].reset_index(drop=True)

    for index, row in borders.iterrows():
        puntos = borders.x_y_concat[index]
        borders.at[index, 'geometry'] = Polygon(concave_hull(puntos, concavity=2)) if len(puntos) > 4 else Polygon()

    borders.drop(columns='x_y_concat', inplace=True)
    borders = gpd.GeoDataFrame(borders, geometry='geometry', crs='EPSG:3857').to_crs("EPSG:4326")
    
    return borders


# Mapeo de sub_tags a macro categorías
def map_clusters(borders_clusters):
    import folium
    from folium.plugins import MarkerCluster

    center = [-34.61, -58.38]
    m = folium.Map(location=center, zoom_start=12, tiles="cartodbpositron")

    for cat in borders_clusters_especiales['macro_category'].unique():
        fg = folium.FeatureGroup(name=cat)
        gdf_cat = borders_clusters_especiales[borders_clusters_especiales['macro_category'] == cat]
        folium.GeoJson(
            gdf_cat.to_json(),
            style_function=lambda feat: {"color": "#444444", "weight": 1, "fillOpacity": 0.1},
            popup=folium.GeoJsonPopup(fields=["macro_category"], labels=True)
        ).add_to(fg)
        fg.add_to(m)

    folium.LayerControl().add_to(m)

    m.save(OUTPUT_DATA_DIR / 'pois_clusters.html')

    return logger.info(f"Mapa guardado en {OUTPUT_DATA_DIR / 'pois_clusters.html'}")


# Función para asignar clusters a anuncios
def assign_clusters_to_ads(gdf_ads, borders_clusters):
    # Aseguramos que ambos GeoDataFrames estén en el mismo CRS
    gdf_ads = gdf_ads.to_crs("EPSG:4326")
    borders_clusters = borders_clusters.to_crs("EPSG:4326")

    # Realizamos un join espacial para asignar clusters a los anuncios
    gdf_ads_with_clusters = gpd.sjoin(gdf_ads, borders_clusters, how="left", predicate='within')

    return gdf_ads_with_clusters


# Pipeline principal de clustering   
def run_clustering():
    logger.info("Iniciando pipeline de clustering de centralidades...")
    # Cargar datos de POIs y macro categorías
    logger.info("Cargando datos de POIs y macro categorías de pois...")
    gdf_osm_pois = gpd.read_parquet(OSM_POIS)        
    osm_macro_categories = pd.read_csv(OSM_POIS_MACROCATEGORIES)
        
    gdf_osm_pois, X = dataprep_to_clustering(gdf_osm_pois, osm_macro_categories)
    logger.info("Datos preparados para clustering.")
    
    # Clustering global
    gdf_osm_pois = train_dbscan(X, gdf_osm_pois)
    borders_global = create_gdf_cluster_borders(gdf_osm_pois)
    logger.info("Clustering global completado.")
    
    # Clustering temático por macro_category
    gdf_osm_pois['macro_category_index'] = gdf_osm_pois['macro_category'].astype('category').cat.codes
    clusters_tematicos = pd.DataFrame()
    
    for cat_idx in sorted(gdf_osm_pois['macro_category_index'].unique()):
        pois_cat = gdf_osm_pois[gdf_osm_pois['macro_category_index'] == cat_idx].copy()
        param_type = pois_cat['param_type'].iloc[0]
        eps = params_clustering[param_type]['eps']
        min_samples = params_clustering[param_type]['min_samples']
        
        X_cat = pois_cat[['y', 'x']].values
        pois_cat = train_dbscan(X_cat, pois_cat, eps, min_samples, 'cluster_special')
        clusters_tematicos = pd.concat([clusters_tematicos, pois_cat], ignore_index=True)
    
    borders_tematicos = create_gdf_cluster_borders(
        clusters_tematicos, 
        cluster_col='cluster_special', 
        group_cols=['macro_category_index', 'cluster_special']
    )
    borders_tematicos['macro_category'] = borders_tematicos['macro_category_index'].map(
        dict(enumerate(gdf_osm_pois['macro_category'].astype('category').cat.categories))
    )
    logger.info("Clustering temático completado.")
    
    # Asignar clusters a anuncios
    df_ads = pd.read_parquet(settings.PROCESSED_DIR / "anuncios_geolocalizados.parquet") 
    gdf_ads = gpd.GeoDataFrame(df_ads,geometry=gpd.points_from_xy(df_ads['long'], df_ads['lat'], crs="EPSG:4326"))

    gdf_ads_global = assign_clusters_to_ads(gdf_ads, borders_global)
    gdf_ads_tematicos = assign_clusters_to_ads(gdf_ads, borders_tematicos)
    
    # Guardar resultados
    settings.OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    borders_global.to_file(settings.OUTPUTS_DIR / "pois_clusters_global.geojson", driver='GeoJSON')
    borders_tematicos.to_file(settings.OUTPUTS_DIR / "pois_clusters_tematicos.geojson", driver='GeoJSON')
    gdf_ads_global.to_parquet(settings.PROCESSED_DIR / "ads_clusters_global.parquet")
    gdf_ads_tematicos.to_parquet(settings.PROCESSED_DIR / "ads_clusters_tematicos.parquet")
    
    logger.info("Pipeline de clustering completado.")

if __name__ == "__main__":
    run_clustering()