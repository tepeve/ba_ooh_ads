import pytest
import pandas as pd
import geopandas as gpd
from shapely.geometry import Polygon
from src.config import settings
from src.etl.ads import transform_ads

def test_transform_pipeline_end_to_end(mock_env_dirs, sample_ad_csv, mocker):
    """
    Simula la ejecución completa de transform_ads.py.
    - Lee el CSV mockeado.
    - Normaliza columnas.
    - 'Geocodifica' (mock).
    - Asigna Barrios (mock join).
    - Genera H3.
    - Guarda Parquet.
    """
    
    # 1. Mockear la variable global RAW_DATA_PATH en el módulo
    # Como ya fue importado, necesitamos parchearlo directamente en el módulo
    mocker.patch.object(transform_ads, 'RAW_DATA_PATH', sample_ad_csv)
    
    # 2. Mockear GeocodingService.bulk_geocode para evitar latencia/internet
    # Devolvemos un DF con coordenadas fijas para los registros del sample_csv
    df_geo_mock = pd.DataFrame({
        'found_address': ['Mock Addr 1', 'Mock Addr 2', 'Mock Addr 3'],
        'lat': [-34.6037, -34.6037, -34.6037], # Obelisco coords para todos
        'long': [-58.3816, -58.3816, -58.3816]
    })
    mocker.patch("src.etl.ads.transform_ads.GeocodingService.bulk_geocode", return_value=df_geo_mock)

    # 3. Mockear la carga de capas administrativas (Barrios/Comunas/Zonif)
    # Creamos un GeoDataFrame dummy para que el spatial join no falle
    poly = Polygon([(-58.4, -34.6), (-58.3, -34.6), (-58.3, -34.7), (-58.4, -34.7)])
    gdf_mock = gpd.GeoDataFrame(
        {'barrio_desc': ['TEST BARRIO'], 'comuna_desc': ['C1'], 'distrito_simply': ['U20']}, 
        geometry=[poly], 
        crs="EPSG:4326"
    )
    
    # Interceptamos todas las llamadas a read_parquet del módulo geopandas dentro de transform_ads
    # NOTA: transform_ads usa gpd.read_file para geojson/shp, PERO si usa read_parquet para dataframes intermedios?
    # Revisar implementacion real. En el contexto, se mencionan archivos GeoJSON (barrios.geojson etc).
    # Como el prompt dice 'Interceptamos todas las llamadas a read_parquet del módulo geopandas',
    # Asumimos que el script las usa. Si usa read_file, también deberíamos mockearlo.
    # Por seguridad, mockeamos read_file tambien si es what geopandas uses for geojson.
    
    mocker.patch("geopandas.read_file", return_value=gdf_mock) 
    mocker.patch("geopandas.read_parquet", return_value=gdf_mock)
    
    # 4. Ejecutar el pipeline
    transform_ads.run_transform()
    
    # 5. Aserciones finales
    output_file = settings.PROCESSED_DIR / "anuncios_geolocalizados.parquet"
    assert output_file.exists(), "El archivo parquet final no fue generado"
    
    df_result = pd.read_parquet(output_file)
    
    # Verificar estructura y datos
    assert not df_result.empty, "El dataframe resultante está vacío"
    assert "h3_index" in df_result.columns, "Falta columna H3"
    assert "lat" in df_result.columns
    assert "barrio_desc" in df_result.columns or "barrio" in df_result.columns
    
    # Verificar normalización
    assert "domicilio_calle" in df_result.columns # Columna renometada de DOMICILIO_CALLE -> lower
    assert df_result.iloc[0]['calle_nombre_norm'] == "Avenida Corrientes" # AV. CORRIENTES normalizado
