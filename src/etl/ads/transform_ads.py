import pandas as pd
import geopandas as gpd
import unicodedata
import logging
from pathlib import Path
from datetime import datetime


from utils.utils_spatial import add_h3_index, join_with_admin_layer
from etl.ads.geocoding_ads import GeocodingService
from src.config import settings

# Configuración de Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Añadir: ruta al CSV crudo usando la configuración central
RAW_DATA_PATH = settings.RAW_DIR / "padron_anuncios.csv"

def clean_column_name(name: str) -> str:
    """
    Normaliza nombres de columnas: minúsculas, sin tildes, espacios -> guiones bajos.
    """
    # Eliminar tildes (NFD form decomposes characters)
    nfkd_form = unicodedata.normalize('NFKD', name)
    name_ascii = "".join([c for c in nfkd_form if not unicodedata.combining(c)])
    
    return name_ascii.lower().strip().replace(' ', '_').replace('.', '')

def normalize_address_text(df: pd.DataFrame, col_name: str) -> pd.Series:
    """
    Aplica reglas específicas de normalización de direcciones para CABA.
    Args:
        df: DataFrame con los datos.
        col_name: Nombre de la columna de direcciones a normalizar.
    Returns:
        Serie con las direcciones normalizadas.
    """
    # Mapeo de reemplazos (Regex Key -> Value)
    replacements = {
        r'\bAvda\b': 'Avenida',   # \b asegura que sea palabra completa
        r'\bAv\b': 'Avenida',   # \b asegura que sea palabra completa
        r'\bAv.\b': 'Avenida',   # \b asegura que sea palabra completa
        r'\bPje\b': '',
        r'\bBlvd\b': '',
        r'\bPte\s': '',           # Pte seguido de espacio
        r'\bGob\s': '',
        r'\bDr\s': '',
        r'\bInt\s': '',
        r'\bTte Gral\s': '',
        r'\bSdo\b': 'Soldado',
        r'\bGral\b': 'General',
        r'\bCnel\b': 'Coronel',
        r'\bAlmte\b': 'Almirante',
        r'\bCmdro\b': 'Comodoro',
        r'\bRgto\b': 'Regimiento',
        r'\bFgta\b': 'Fragata',
        r'Juan B Alberdi': 'Juan Bautista Alberdi'
    }
    
    series = df[col_name].copy().astype(str)
    
    for pattern, replacement in replacements.items():
        series = series.str.replace(pattern, replacement, regex=True)
        
    # Limpieza final de espacios múltiples generados por los reemplazos
    series = series.str.replace(r'\s+', ' ', regex=True).str.strip()
    return series

def run_transform():
    # Cargar datos
    logger.info(f"Cargando datos crudos desde {RAW_DATA_PATH}...")
    df = pd.read_csv(RAW_DATA_PATH, low_memory=False) # low_memory=False evita warnings de tipos mixtos
    
    # Limpieza de nombres de columnas
    df.columns = [clean_column_name(c) for c in df.columns]
    logger.info(f"Columnas normalizadas: {df.columns.tolist()[:5]}...")

    # Enriquecimiento Básico y Tipos de Datos
    logger.info("Aplicando tipos de datos y constantes...")
    
    # Constantes geográficas
    df['ciudad'] = "Ciudad de Buenos Aires"
    df['pais'] = "Argentina"

    # Conversión de Tipos
    # Altura: Usamos Int64 para permitir nulos (NaN) sin convertir a float
    df['calle_altura'] = pd.to_numeric(df['calle_altura'], errors='coerce').astype('Int64')
    
    df['calle_altura'] = df['calle_altura'].fillna('').astype(str).replace('<NA>', '').replace('nan', '')
    
    # Fechas
    df['fecha_alta_anuncio'] = pd.to_datetime(df['fecha_alta_anuncio'], errors='coerce').dt.date
    
    # Numéricos y Textos
    df['zona'] = pd.to_numeric(df['zona'], errors='coerce').fillna(0).astype(int)
    df['metros'] = pd.to_numeric(df['metros'], errors='coerce')
    df['calle_nombre'] = df['calle_nombre'].astype(str).str.title()  # Capitalizar nombres de calles

    # Estandarizamos texto para filtrar robustamente
    df['caracteristica'] = df['caracteristica'].fillna('').str.upper()
    df['tipo'] = df['tipo'].fillna('').str.upper()
    df['clase'] = df['clase'].fillna('').str.upper()

    # Normalización de Direcciones (Aplica a TODOS los registros)
    logger.info("Normalizando direcciones...")
    df['calle_nombre_norm'] = normalize_address_text(df, 'calle_nombre')

    # Generación de Direcciones Completas
    logger.info("Generando direcciones completas...")
    # Formato: "Calle Altura, Ciudad, Pais"
    df['full_address'] = (
            df['calle_nombre_norm'] + " " +
            df['calle_altura'] + ", " +
            df['ciudad'] + ", " +
            df['pais']
        )

    # Limpiamos espacios extra y NaN
    df['full_address'] = df['full_address'].str.strip().replace('nan', '').replace('  ', ' ')
    df['full_address'] = df['full_address'].str.replace(r'\s+', ' ', regex=True)  # Reemplazar múltiples espacios por uno solo
    df['full_address'] = df['full_address'].str.replace(r'^\s+|\s+$', '', regex=True)  # Eliminar espacios al inicio y final
    df['full_address'] = df['full_address'].str.replace(r',\s*,', ',', regex=True)  # Eliminar comas dobles
    logger.info(f"Direcciones completas generadas: {df['full_address'].head(5).tolist()}")

    # Filtrado de registros irrelevantes
    logger.info("Filtrando registros irrelevantes...")
    # Excluir registros con características específicas
    mask_exclude = (
        (df['caracteristica'] == "TRANSP.PUBLICO") |
        (df['caracteristica'] == "TAXI") |
        (df['tipo'] == "SUBTERRANEO") |
        (df['clase'] == "LETRERO")
    )

    df_excluded = df[mask_exclude].copy()
    df_kept = df[~mask_exclude].copy()

    # Guardar excluidos (Auditoría)
    settings.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    excluded_path = settings.PROCESSED_DIR / "anuncios_excluidos.csv"
    df_excluded.to_csv(excluded_path, index=False)
    logger.info(f"Registros excluidos: {len(df_excluded)}. Guardados en {excluded_path}")
    logger.info(f"Registros a procesar: {len(df_kept)}")

    # Coordenadas (Limpieza inicial de comas por puntos si existen)
    cols_coords = ['long', 'lat']
    for col in cols_coords:
        if col in df_kept.columns:
            # Reemplazar comas por puntos si es string, luego a numérico
            if df_kept[col].dtype == 'object':
                df_kept[col] = df_kept[col].str.replace(',', '.')
            df_kept[col] = pd.to_numeric(df_kept[col], errors='coerce')

    # Lógica de Geocodificación
    # Identificar registros que necesitan geocoding (Lat/long vacíos, nulos o 0)
    # Criterio: Nulo OR Cero OR Fuera de rango (Lat > -30 es improbable en CABA)
    geo_mask = (
        df_kept['lat'].isna() | 
        df_kept['long'].isna() | 
        (df_kept['lat'] == 0) |
        (df_kept['lat'] > -30) # Filtro burdo para coords mal cargadas
    )
    
    df_kept['needs_geocoding'] = geo_mask
    n_to_geocode = df_kept['needs_geocoding'].sum()
    logger.info(f"Registros detectados sin coordenadas válidas: {n_to_geocode}")


    if n_to_geocode > 0:
        # Separar dataset para geocodificar
        df_to_geo = df_kept[geo_mask].copy()
        
        # Instanciar servicio
        geo_service = GeocodingService()
        
        # Ejecutar Geocoding (devuelve df con cols 'lat' y 'long')
        # Usamos delay=1.0 para ser gentiles con Nominatim
        df_geocoded = geo_service.bulk_geocode(df_to_geo, address_col='full_address', delay=1.0, timeout=20)
       
        # Integración de Resultados (Merge/Update)
        # Actualizamos las columnas lat/long originales con los nuevos valores
        # Pandas update usa el índice para alinear
        df_kept.loc[geo_mask, 'lat'] = df_geocoded['lat']
        # El geocoding devuelve 'lon', nuestra columna destino es 'long'
        df_kept.loc[geo_mask, 'long'] = df_geocoded['lon']
        
        # Marcar cuáles fueron recuperados exitosamente (lat no nulo despues del proceso)
        recovered = df_kept.loc[geo_mask, 'lat'].notna().sum()
        logger.info(f"Geocodificación completada. Recuperados: {recovered} de {n_to_geocode}")

    
    # Enriquecimiento Geoespacial
    logger.info("Iniciando enriquecimiento geoespacial...")
    
    # 8.1 Agregar índices H3 (resolución 9 ~ nivel manzana)
    logger.info("Generando índices H3 resolución 9...")
    df_kept = add_h3_index(df_kept, lat_col='lat', lon_col='long', resolution=settings.H3_RESOLUTION,inplace=True,out_col='h3_index')
    h3_count = df_kept['h3_index'].notna().sum()
    logger.info(f"Índices H3 generados: {h3_count} de {len(df_kept)}")
    
    # 8.2 Cargar capas administrativas desde parquets
    logger.info("Cargando capas administrativas...")
    
    try:
        gdf_barrios = gpd.read_parquet(settings.EXTERNAL_DIR / "barrios.parquet")
        logger.info(f"✓ Barrios cargados: {len(gdf_barrios)} registros")
    except Exception as e:
        logger.warning(f"No se pudo cargar barrios.parquet: {e}")
        gdf_barrios = None
    
    try:
        gdf_comunas = gpd.read_parquet(settings.EXTERNAL_DIR / "comunas.parquet")
        logger.info(f"✓ Comunas cargadas: {len(gdf_comunas)} registros")
    except Exception as e:
        logger.warning(f"No se pudo cargar comunas.parquet: {e}")
        gdf_comunas = None
    
    try:
        gdf_zonificacion = gpd.read_parquet(settings.EXTERNAL_DIR / "zonificacion.parquet")
        logger.info(f"✓ Zonificación cargada: {len(gdf_zonificacion)} registros")
    except Exception as e:
        logger.warning(f"No se pudo cargar zonificacion.parquet: {e}")
        gdf_zonificacion = None
    
    # Realizar spatial joins (solo para registros con coordenadas válidas)
    # Filtramos temporalmente los registros con coordenadas válidas
    valid_coords_mask = df_kept['lat'].notna() & df_kept['long'].notna()
    df_with_coords = df_kept[valid_coords_mask].copy()
    
    logger.info(f"Realizando spatial joins para {len(df_with_coords)} registros con coordenadas válidas...")
    
    # Join con Barrios
    if gdf_barrios is not None:
        logger.info("Ejecutando spatial join con Barrios...")
        df_with_coords = join_with_admin_layer(
            df_with_coords, 
            gdf_barrios, 
            lat_col='lat', 
            lon_col='long'
        )
        # Verificar qué columnas se agregaron y renombrar si es necesario
        if 'barrio' in df_with_coords.columns:
            barrios_asignados = df_with_coords['barrio'].notna().sum()
            logger.info(f"✓ Barrios asignados: {barrios_asignados}")
    
    # Join con Comunas
    if gdf_comunas is not None:
        logger.info("Ejecutando spatial join con Comunas...")
        df_with_coords = join_with_admin_layer(
            df_with_coords, 
            gdf_comunas, 
            lat_col='lat', 
            lon_col='long'
        )
        # Verificar qué columnas se agregaron
        if 'comuna' in df_with_coords.columns:
            comunas_asignadas = df_with_coords['comuna'].notna().sum()
            logger.info(f"✓ Comunas asignadas: {comunas_asignadas}")
    
    # Join con Zonificación
    if gdf_zonificacion is not None:
        logger.info("Ejecutando spatial join con Zonificación...")
        df_with_coords = join_with_admin_layer(
            df_with_coords, 
            gdf_zonificacion, 
            lat_col='lat', 
            lon_col='long'
        )
        if 'distrito_simply' in df_with_coords.columns:
            distritos_asignados = df_with_coords['distrito_simply'].notna().sum()
            logger.info(f"✓ Distritos asignados: {distritos_asignados}")
    
    # Reintegrar los resultados al DataFrame completo
    # Las columnas nuevas que no existían en df_kept se agregan con NaN para los registros sin coords
    nuevas_columnas = [col for col in df_with_coords.columns if col not in df_kept.columns]
    
    for col in nuevas_columnas:
        df_kept[col] = None
    
    # comprobar columnas duplicadas
    logger.info(f"columnas duplicadas: {df_with_coords.columns[df_with_coords.columns.duplicated()].unique()}")
    logger.info(f"columnas duplicadas: {df_kept.columns[df_kept.columns.duplicated()].unique()}")
    
    logger.info(f"indices duplicadas: {df_with_coords.index.duplicated().any(), df_with_coords.index[df_with_coords.index.duplicated()][:10]}")
     
    # Si el spatial join produjo filas duplicadas (mismo índice original) --- colapsar
    if df_with_coords.index.duplicated().any():
        dup_idx = df_with_coords.index[df_with_coords.index.duplicated()].unique()
        logger.warning(f"Índices duplicados detectados en df_with_coords: {list(dup_idx)}. Conservando la primera ocurrencia por índice.")
        df_with_coords = df_with_coords[~df_with_coords.index.duplicated(keep='first')]

    # Reindexar explícitamente a la selección destino para alinear etiquetas y evitar reindex errors
    target_index = df_kept.loc[valid_coords_mask].index
    df_with_coords = df_with_coords.reindex(target_index)

    df_kept.loc[valid_coords_mask, df_with_coords.columns] = df_with_coords
    
    logger.info(f"Enriquecimiento geoespacial completado. Nuevas columnas: {nuevas_columnas}")
    
    # Limpieza Final y Guardado
    
    # Filtro final de seguridad: Solo guardar lo que tenga coordenadas válidas
    # Opcional: ¿Quieres descartar lo que falló en geocoding? Por ahora lo dejamos pero con Nulos
    final_count = len(df_kept)
    valid_geo_count = df_kept['lat'].notna().sum()
    
    logger.info(f"Guardando Parquet final. Total: {final_count}. Con Geo: {valid_geo_count}")
    
    # Guardamos en Parquet (mucho más eficiente que CSV para tipos de datos)
    output_path = settings.PROCESSED_DIR / "anuncios_geolocalizados.parquet"
    df_kept.to_parquet(output_path, index=False)
    logger.info(f"✅ Proceso finalizado exitosamente: {output_path}")

if __name__ == "__main__":
    run_transform()