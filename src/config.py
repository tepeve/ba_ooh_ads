from pathlib import Path
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Paths
    # Define la raíz del proyecto basándose en la ubicación de este archivo (src/config.py)
    PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
    DATA_DIR: Path = PROJECT_ROOT / "data"
    RAW_DIR: Path = DATA_DIR / "raw"
    PROCESSED_DIR: Path = DATA_DIR / "processed"
    EXTERNAL_DIR: Path = DATA_DIR / "external"
    OUTPUTS_DIR: Path = DATA_DIR / "outputs"
    CACHE_DIR: Path = DATA_DIR / "cache"

    # Database Paths
    OSM_DB_PATH: Path = CACHE_DIR / "osm_pois_cache.db"
    GEOCODE_DB_PATH: Path = CACHE_DIR / "geocache.db"

    # External URLs (Government & Data Sources)
    ADS_DATA_URL: str = "https://cdn.buenosaires.gob.ar/datosabiertos/datasets/administracion-gubernamental-de-ingresos-publicos/padron-anuncios-empadronados/padron-anuncios-empadronados.csv"
    BARRIOS_URL: str = "https://cdn.buenosaires.gob.ar/datosabiertos/datasets/innovacion-transformacion-digital/barrios/barrios.geojson"
    COMUNAS_URL: str = "https://cdn.buenosaires.gob.ar/datosabiertos/datasets/innovacion-transformacion-digital/comunas/comunas.geojson"
    ZONIFICACIONES_URL: str = "https://cdn.buenosaires.gob.ar/datosabiertos/datasets/secretaria-de-desarrollo-urbano/codigo-planeamiento-urbano/codigo-de-planeamiento-urbano-actualizado-al-30062018-poligonos-zip.zip"
    INDEC_CENSO_WFS: str = "https://geonode.indec.gob.ar/geoserver/ows?service=WFS&version=2.0.0&request=GetFeature&typename=geonode:radios_censales&outputFormat=shape-zip&srsName=EPSG:4326"
    ETAPAS_URL: str = "https://cdn.buenosaires.gob.ar/datosabiertos/datasets/transporte-y-obras-publicas/viajes-etapas-transporte-publico/viajes_BAdata_20241016.csv"

    # H3 Parameters
    H3_RESOLUTION: int = 9

    class Config:
        env_file = ".env"

settings = Settings()
