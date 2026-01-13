
import logging
import requests
import zipfile
import tempfile
import os
import geopandas as gpd
import pandas as pd
from pathlib import Path
from io import BytesIO

from utils.utils_spatial import download_map


# Configuración de Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# VARIABLES
URL_PROV = ""
URL_BARRIOS = "https://cdn.buenosaires.gob.ar/datosabiertos/datasets/innovacion-transformacion-digital/barrios/barrios.geojson"
URL_COMUNAS = "https://cdn.buenosaires.gob.ar/datosabiertos/datasets/innovacion-transformacion-digital/comunas/comunas.geojson"
URL_ZONIFICACIONES = "https://cdn.buenosaires.gob.ar/datosabiertos/datasets/secretaria-de-desarrollo-urbano/codigo-planeamiento-urbano/codigo-de-planeamiento-urbano-actualizado-al-30062018-poligonos-zip.zip"
URL_CENSO= 'https://geonode.indec.gob.ar/geoserver/ows?service=WFS&version=2.0.0&request=GetFeature&typename=geonode:radios_censales&outputFormat=shape-zip&srsName=EPSG:4326'


OUTPUT_DIR = Path("data/external")


def download_and_process_zonificacion(url: str) -> gpd.GeoDataFrame:
    """
    Descarga el ZIP de zonificaciones, extrae el Shapefile y simplifica la columna de distritos.
    Devuelve el GeoDataFrame procesado.
    """

    # Descargar el ZIP con requests
    logger.info(f"Descargando y procesando Zonificaciones desde: {url}")
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    content = response.content

    gdf = None
    head = content[:16] or b""
    # Leer el contenido del ZIP directamente desde memoria
    gdf = gpd.read_file(BytesIO(content))
    logger.info("Zonificaciones descargadas y leídas correctamente.")

    logger.info("Procesando Zonificaciones...")
    # Normalizar columnas y aplicar transformaciones conocidas
    gdf.columns = [str(c).lower() for c in gdf.columns]
    gdf.drop(columns=["nombre", "normativa"], inplace=True)

    gdf["distrito_simply"] = gdf["distrito"].astype(str).str.split(n=1).str[0]
    mask_u = gdf["distrito_simply"].astype(str).str.contains(r"U(?=\d)", regex=True)
    gdf.loc[mask_u, "distrito_simply"] = "U"

    # Mapping simple
    data_mapping = {
            "distrito_simply": ["E4", "UP", "R2a", "ARE", "R1b", "RU", "R1a", "R2b", "C3", "E3", "NE", "U", "C2", "UP/APH", "APH", "E2", "E1", "P", "UF", "I1", "I2", "RUA/E4", "RUA", "C1"],
            "distrito_desc": [
                "EQUIPAMIENTO ESPECIAL", "URBANIZACIÓN PARQUE", "RESIDENCIAL GENERAL DE DENSIDAD ALTA", "ÁREA DE RESERVA ECOLÓGICA",
                "RESIDENCIAL EXCLUSIVO DE DENSIDAD MEDIA BAJA", "RENOVACIÓN URBANA", "RESIDENCIAL EXCLUSIVO DE DENSIDAD MEDIA",
                "RESIDENCIAL GENERAL DE DENSIDAD MEDIA BAJA", "CENTRO LOCAL", "EQUIPAMIENTO LOCAL", "NORMAS ESPECIALES",
                "URBANIZACIÓN DETERMINADA", "CENTROS PRINCIPALES", "URBANIZACIÓN PARQUE / ÁREA DE PROTECCIÓN HISTÓRICA",
                "ÁREA DE PROTECCIÓN HISTÓRICA", "EQUIPAMIENTO GENERAL", "EQUIPAMIENTO MAYORISTA", "DISTRITO PORTUARIO",
                "URBANIZACIÓN FUTURA", "INDUSTRIAL EXCLUSIVO", "INDUSTRIAL COMPATIBLE CON EL USO RESIDENCIAL EN FORMA RESTRINGIDA",
                "RENOVACIÓN URBANA LINDERA A AUTOPISTAS / EQUIPAMIENTO ESPECIAL", "RENOVACIÓN URBANA LINDERA A AUTOPISTAS", "ÁREA CENTRAL"
            ]
        }

    df_mapping = pd.DataFrame(data_mapping)

    gdf = gdf.merge(df_mapping, on="distrito_simply", how="left")

    gdf = gpd.GeoDataFrame(gdf, geometry='geometry')

    logger.info("Zonificaciones procesadas correctamente.")
    # Asegurar CRS WGS84
    gdf = gdf.to_crs(epsg=4326)
    logger.info("Zonificaciones reproyectadas a EPSG:4326.")

    return gdf



def process_admin_layers():
    """Descarga, procesa y guarda capas administrativas."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Barrios
    try:
        gdf_barrios = download_map(URL_BARRIOS)
        # Normalizar, renombrar y seleccionar columnas
        gdf_barrios = gdf_barrios.rename(columns=str.lower)
        
        gdf_barrios['barrio_desc'] = gdf_barrios['nombre'].str.title()
        gdf_barrios['barrio_id'] = gdf_barrios['id'].astype(int)
        gdf_barrios = gdf_barrios[['barrio_id', 'barrio_desc', 'geometry']]
        
        # Asegurar CRS (WGS84 para lat/lon)
        if gdf_barrios.crs is None:
            gdf_barrios.set_crs(epsg=4326, inplace=True)
        else:
            gdf_barrios.to_crs(epsg=4326, inplace=True)

        output_path = OUTPUT_DIR / "barrios.parquet"
        gdf_barrios.to_parquet(output_path)
        logger.info(f"✅ Barrios guardados en {output_path}")

    except Exception as e:
        logger.error(f"Error procesando Barrios: {e}")

    # 2. Comunas
    try:
        gdf_comunas = download_map(URL_COMUNAS)
        # Normalizar, renombrar y seleccionar columnas
        gdf_comunas = gdf_comunas.rename(columns=str.lower)
        gdf_comunas['comuna_id'] = gdf_comunas['id'].astype(int)
        gdf_comunas['comuna_desc'] = gdf_comunas['comuna'].astype(str).str.title()
        gdf_comunas = gdf_comunas[['comuna_id', 'comuna_desc', 'geometry']] 
        
        # Asegurar CRS
        gdf_comunas.to_crs(epsg=4326, inplace=True)

        output_path = OUTPUT_DIR / "comunas.parquet"
        gdf_comunas.to_parquet(output_path)
        logger.info(f"✅ Comunas guardadas en {output_path}")

    except Exception as e:
        logger.error(f"Error procesando Comunas: {e}")

    # 3. Zonificaciones 
    try:
        gdf_zonif = download_and_process_zonificacion(URL_ZONIFICACIONES)
        output_path = OUTPUT_DIR / "zonificacion.parquet"
        gdf_zonif.to_parquet(output_path)
        logger.info(f"✅ Zonificaciones guardadas en {output_path}")
    except Exception as e:
        logger.error(f"Error procesando Zonificaciones: {e}")

    # 4. radios censales
    # info en: https://portalgeoestadistico.indec.gob.ar/maps/geoportal/nota_radios_censales.pdf
    try:
        gdf_rcensales = download_map(URL_CENSO)
         # Normalizar, renombrar y seleccionar columnas
        gdf_rcensales = gdf_rcensales.rename(columns=str.lower)
        # filtramos radio censales de caba unicamente
        gdf_rcensales = gdf_rcensales.query("cpr == '02'")        
        gdf_rcensales = gdf_rcensales[['jur', 'dpto', 'cod_indec', 'geometry']]
        # Asegurar CRS (WGS84)
        if gdf_rcensales.crs is None:
            gdf_rcensales.set_crs(epsg=4326, inplace=True)
        else:
            gdf_rcensales.to_crs(epsg=4326, inplace=True)

        output_path = OUTPUT_DIR / "radios_censales.parquet"
        gdf_rcensales.to_parquet(output_path)
        logger.info(f"✅ Radios censales guardados en {output_path}")
    except Exception as e:
        logger.error(f"Error procesando Radios Censales: {e}")


if __name__ == "__main__":
    process_admin_layers()