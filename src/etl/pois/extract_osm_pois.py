from os import name
import geopandas as gpd
import pandas as pd
import osmnx as ox
import logging
import sqlite3
from pathlib import Path
from shapely.ops import unary_union
from shapely import wkt
import yaml
import time
from src.config import settings

# Configuración de Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class OSMPOIExtractor:
    def __init__(self, db_path: Path = settings.OSM_DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._setup_db()

    def _setup_db(self):
        """Inicializa la tabla de caché en SQLite."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # Guardamos osmid, la categoría (key de osm), metadatos y la geometría como WKT (texto)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS osm_pois (
                    osmid TEXT PRIMARY KEY,
                    tag TEXT,
                    tipo_osm TEXT,
                    nombre_osm TEXT,
                    sub_tag TEXT,
                    geometry_wkt TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_osm_key ON osm_pois(tag)")
            conn.commit()

    def _get_from_cache(self, osm_key: str) -> gpd.GeoDataFrame:
        """Intenta recuperar POIs de una categoría específica desde la caché."""
        with sqlite3.connect(self.db_path) as conn:
            query = "SELECT * FROM osm_pois WHERE tag = ?"
            df = pd.read_sql_query(query, conn, params=(osm_key,))
        
        if df.empty:
            return None
        
        # Reconstruir geometría desde WKT
        df['geometry'] = df['geometry_wkt'].apply(wkt.loads)
        df = df.drop(columns=['geometry_wkt'])
        
        # Convertir a GeoDataFrame
        gdf = gpd.GeoDataFrame(df, geometry='geometry', crs="EPSG:4326")
        logger.info(f"Cache HIT para '{osm_key}': {len(gdf)} registros recuperados.")
        return gdf

    def _save_to_cache(self, gdf: gpd.GeoDataFrame, osm_key: str):
        """Guarda los resultados procesados en SQLite."""
        if gdf.empty:
            return

        # Preparamos el DF para guardar (convertir geom a WKT)
        df_save = pd.DataFrame(gdf).copy()
        df_save['geometry_wkt'] = df_save.geometry.apply(lambda x: x.wkt)
        
        # Aseguramos que las columnas coincidan con la tabla
        cols_to_save = ['osmid', 'tag', 'tipo_osm', 'nombre_osm', 'sub_tag', 'geometry_wkt']
        # Renombrar columnas del DF para que coincidan con la DB si es necesario
        # En este script ya las renombramos antes de llamar a esta función
        
        data = df_save[cols_to_save].values.tolist()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.executemany("""
                INSERT OR REPLACE INTO osm_pois (osmid, tag, tipo_osm, nombre_osm, sub_tag, geometry_wkt)
                VALUES (?, ?, ?, ?, ?, ?)
            """, data)
            conn.commit()
        logger.info(f"Guardados {len(data)} registros de '{osm_key}' en caché.")

    def get_boundary_polygon(self):
        """Obtiene el polígono de CABA con buffer, tal como en la lógica original."""
        logger.info("Obteniendo límites de CABA...")
        gdf_caba = ox.geocode_to_gdf('Ciudad Autónoma de Buenos Aires, Argentina')

        # Disolver y aplicar buffer
        recorte_dissolve = gdf_caba.dissolve()
        
        # Buffer de 100m (reproyectando ida y vuelta)
        recorte_dissolve = recorte_dissolve.to_crs('EPSG:3857').buffer(100).to_crs('EPSG:4326')

        # Unary union y Convex Hull
        bordes_recorte = unary_union(recorte_dissolve.geometry).convex_hull
        return bordes_recorte

    def process_category(self, polygon, tag: str) -> gpd.GeoDataFrame:
        """
        Procesa una categoría (key) de OSM:
        1. Busca en caché.
        2. Si no está, descarga de OSM.
        3. Calcula centroides.
        4. Guarda en caché.
        """
        # 1. Intentar Caché
        cached_gdf = self._get_from_cache(tag)
        if cached_gdf is not None:
            return cached_gdf

        # 2. Descargar de OSM
        logger.info(f"Descargando '{tag}' desde OSM API...")
        
        pois = ox.features_from_polygon(polygon=polygon, tags={tag: True})

        pois['osm_tag'] = tag

        gdf = pois.reset_index()\
              .reindex(columns=['osmid', tag, 'element_type', 'name', 'osm_tag', 'geometry'])\
              .rename(columns={tag: 'sub_tag', 'element_type': 'tipo_osm', 'name': 'nombre_osm', 'osm_tag': 'tag'})
    
        gdf = gdf.to_crs('EPSG:4326')
        gdf['tipo_geom_original'] = gdf.geometry.geom_type

        # Conversión a Centroides (Lógica solicitada)
        # Reproyecta a metros (3857) -> calcula centroide -> vuelve a 4326
        gdf['geometry'] = gdf.geometry.to_crs('EPSG:3857').centroid.to_crs('EPSG:4326')
        
        # Eliminamos la geometría original si solo quieres el centroide como geometría activa
        #gdf = gdf.drop(columns=['geometry']) 

        # 4. Guardar en Caché
        self._save_to_cache(gdf, tag)
        
        return gdf
    
    def distill_pois(self, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        """
        Realiza la destilación final de POIs para eliminar duplicados 
        y depurar pois de nuestro interés.
        """
        logger.info("Destilando POIs finales...")
        # Eliminar duplicados basados en 'osmid'
        gdf_distilled = gdf.copy()
        # gdf_distilled = gdf.drop_duplicates(subset=['osmid']).reset_index(drop=True)
        
        # Importamos el archivo que contiene la lista de tipos de POIs que queremos eliminar
        ignore_file = settings.RAW_DIR / 'osm_pois_to_ignore.yaml'
        amenities_eliminar = []
        if ignore_file.exists():
            with open(ignore_file) as file:
                pois_config = yaml.full_load(file) or {}
            # Extraemos los tipos de POIs a eliminar del archivo de configuración
            # 'amenities_eliminar' es una lista de tipos de POIs que queremos eliminar
            amenities_eliminar = pois_config.get('amenities_eliminar', [])
        
        # Filtramos los POIs para eliminar aquellos que están en la lista de 'amenities_eliminar'
        pois_eliminados = gdf_distilled.loc[gdf_distilled['sub_tag'].isin(amenities_eliminar), :].reset_index(drop=True)
        # Filtramos los POIs que seran nuestro dataset final
        gdf_distilled = gdf_distilled.loc[~gdf_distilled['sub_tag'].isin(amenities_eliminar), :].reset_index(drop=True)

        gdf_distilled = gdf_distilled.dropna(subset=['nombre_osm']).reset_index(drop=True)
        gdf_distilled = gdf_distilled.dropna(subset=['tag']).reset_index(drop=True)
        
        # Mostramos la cantidad de POIs eliminados
        logger.info(f"Registros eliminados durante destilación: {len(pois_eliminados)}")
        logger.info(f"Registros después de destilación: {len(gdf_distilled)}")

        return gdf_distilled

    def run(self):
        boundary = self.get_boundary_polygon()
        
        osm_tags = {
            "amenity": True, 
            "leisure": True,  
            "tourism": True,
            "shop": True, 
            "office": True, 
            "craft": True, 
            "industrial": True,
            "clothes": True
        }

        all_gdfs = []

        for tag in osm_tags:
            gdf = self.process_category(boundary, tag)
            if not gdf.empty:
                all_gdfs.append(gdf)
            # Pausa de cortesía para evitar bloqueo de la API
            logger.info("Esperando 10 segundos para evitar saturar la API...")
            time.sleep(10)

        if all_gdfs:
            logger.info("Concatenando resultados finales...")
            final_gdf = pd.concat(all_gdfs, ignore_index=True)
            
            # Asegurar CRS final
            if final_gdf.crs is None:
                final_gdf.set_crs("EPSG:4326", inplace=True)
            
            final_gdf = self.distill_pois(final_gdf)

            # generamos coteo con los subtags únicos presentes en el dataset final
            unique_tags = final_gdf['sub_tag'].value_counts().reset_index()
            unique_tags.columns = ['sub_tag', 'count'] # Renombrar columnas para claridad


            unique_tags.to_csv(settings.PROCESSED_DIR / 'osm_pois_unique_subtags.csv', index=False)
            logger.info(f"Tags únicos guardados en 'osm_pois_unique_subtags.csv'")

            # Guardar Parquet
            settings.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
            output_path = settings.PROCESSED_DIR / "osm_pois.parquet"
            final_gdf.to_parquet(output_path, index=False)
            logger.info(f"✅ Archivo final guardado en: {output_path} ({len(final_gdf)} registros)")
        else:
            logger.warning("No se obtuvieron datos de ninguna categoría.")

if __name__ == "__main__":
    extractor = OSMPOIExtractor()
    extractor.run()
