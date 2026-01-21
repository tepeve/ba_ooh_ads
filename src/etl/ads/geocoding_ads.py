import sqlite3
import time
import logging
from pathlib import Path
from typing import Optional, Tuple, List, Union

import pandas as pd
from geopy.geocoders import Photon
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable
from src.config import settings

# Configuración de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class GeocodingService:
    def __init__(self, db_path: Union[str, Path] = settings.GEOCODE_DB_PATH, user_agent: str = "ba_ooh_ads"):
        """
        Servicio de geocodificación con caché persistente en SQLite.
        """
        self.db_path = Path(db_path)
        self.user_agent = user_agent
        self.geolocator = Photon(user_agent=self.user_agent)
        
        # Crear carpeta de caché si no existe
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._setup_db()
        self._load_cache_stats()

    def _setup_db(self):
        """Inicializa la tabla de caché en SQLite si no existe."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS geocache (
                    address TEXT PRIMARY KEY,
                    lat REAL,
                    long REAL,
                    raw_response TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def _load_cache_stats(self):
        """Carga estadísticas simples para loguear."""
        with sqlite3.connect(self.db_path) as conn:
            try:
                count = conn.execute("SELECT count(*) FROM geocache").fetchone()[0]
                logger.info(f"GeocodingService inicializado. Entradas en caché: {count}")
            except sqlite3.OperationalError:
                logger.info("GeocodingService: Base de datos nueva creada.")

    def _get_from_cache(self, address: str) -> Optional[Tuple[float, float, str]]:
        """Busca coordenadas en la caché local."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT lat, long, raw_response FROM geocache WHERE address = ?", (address,))
            result = cursor.fetchone()
            if result:
                return result # (lat, long, raw)
        return None

    def _save_to_cache(self, data: List[Tuple]):
        """
        Guarda una lista de resultados en la caché.
        Data format: [(address, lat, lon, raw_response), ...]
        """
        if not data:
            return

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.executemany("""
                INSERT OR REPLACE INTO geocache (address, lat, long, raw_response)
                VALUES (?, ?, ?, ?)
            """, data)
            conn.commit()

    def geocode(self, address: str, delay: float = 0.5, timeout: int = 5) -> Tuple[Optional[str], Optional[float], Optional[float]]:        
        """
        Geocodifica una dirección individual. Retorna (address_found, lat, lon).
        """
        if not address or pd.isna(address):
            return None, None, None

        # Normalización básica para key de caché (lowercase + strip)
        cache_key = str(address).strip().lower()

        # 1. Intentar Caché
        cached = self._get_from_cache(cache_key)
        if cached:
            # Retornamos la dirección original (o la del caché si la guardamos), lat, lon
            # cached[2] es raw_response, no lo retornamos al flujo principal por simplicidad
            return address, cached[0], cached[1]
        
        # 2. Consultar API
        try:
            # Usamos la dirección original para la API para no perder info de casing si fuera útil
            location = self.geolocator.geocode(address, timeout=timeout)
            time.sleep(delay) # Respetar límites de la API
            
            if location:
                # Guardamos usando la cache_key normalizada
                self._save_to_cache([(cache_key, location.latitude, location.longitude, str(location.raw))])
                return location.address, location.latitude, location.longitude
            else:
                logger.warning(f"Dirección no encontrada en API: {address}")
                # Podríamos guardar un "no encontrado" para no reintentar, pero por ahora lo dejamos así
                return None, None, None

        except (GeocoderTimedOut, GeocoderUnavailable) as e:
            logger.error(f"Error de conexión/timeout con {address}: {e}")
            time.sleep(2)
            return None, None, None
        
    def bulk_geocode(self, df: pd.DataFrame, address_col: str, delay: float = 0.5, timeout: int = 5) -> pd.DataFrame:
        """
        Procesa un DataFrame completo y agrega columnas 'found_address', 'lat', 'lon'.
        """
        total = len(df)
        logger.info(f"Iniciando geocoding masivo de {total} registros. Columna: {address_col}")
        
        results = []
        
        for i, row in enumerate(df.itertuples(), 1):
            input_address = getattr(row, address_col)
            
            if i % 50 == 0:
                logger.info(f"Procesando {i}/{total} ({((i/total)*100):.1f}%)")

            found_address, lat, lon = self.geocode(input_address, delay=delay, timeout=timeout)
            
            results.append({
                'found_address': found_address,
                'lat': lat,
                'lon': lon
            })

        # Convertir resultados a DF preservando el índice original para evitar desalineación
        results_df = pd.DataFrame(results, index=df.index)

        # Eliminar columnas del DF original que colisionan con las nuevas ('lat', 'lon' si existieran)
        # para evitar columnas duplicadas en el concat
        cols_to_drop = [c for c in results_df.columns if c in df.columns]
        df_clean = df.drop(columns=cols_to_drop)

        # Concatenar alineando por índice
        df_out = pd.concat([df_clean, results_df], axis=1)
        
        hit_ratio = results_df['lat'].notna().mean()
        logger.info(f"Geocoding finalizado. Tasa de éxito: {hit_ratio:.1%}")
        return df_out


def run_pipeline():
    """Ejecuta el pipeline de lectura, geocodificación y guardado."""
    input_file = settings.RAW_DIR / "padron_anuncios.csv"
    output_file = settings.PROCESSED_DIR / "ads_geocoded.parquet"
    
    if not input_file.exists():
        logger.error(f"Archivo de entrada no encontrado: {input_file}")
        exit(1)
        
    logger.info(f"Cargando datos desde {input_file}...")
    # Asumimos CSV separado por ; que es típico en datos de BA, ajustaremos si falla
    try:
        df = pd.read_csv(input_file, sep=",") # Intentar coma primero (default de extract_ads)
        if len(df.columns) < 2: 
             df = pd.read_csv(input_file, sep=";") # Fallback a punto y coma
    except Exception as e:
        logger.error(f"Error leyendo CSV: {e}")
        exit(1)

    logger.info(f"Columnas detectadas: {df.columns.tolist()}")

    # Construcción de dirección completa para mejorar precisión
    # Buscamos columnas comunes de dirección
    cols = [c.lower() for c in df.columns]
    
    # Lógica heurística para encontrar columnas de dirección
    if 'domicilio_calle' in cols and 'domicilio_altura' in cols:
        df['full_address'] = df['domicilio_calle'] + " " + df['domicilio_altura'].fillna('').astype(str) + ", Buenos Aires, Argentina"
    elif 'calle_nombre' in cols and 'calle_altura' in cols:
        df['full_address'] = df['calle_nombre'] + " " + df['calle_altura'].fillna('').astype(str) + ", Buenos Aires, Argentina"
    else:
        # Fallback: intentar usar la primera columna que parezca dirección o usar todas concatenadas
        logger.warning("No se detectaron columnas estandar (calle/altura). Intentando usar columna 0 y 1 o asumiendo 'direccion'.")
        # Para el ejemplo, forzaremos una búsqueda visual si falla, pero agregaremos una columna dummy si no existe
        if 'direccion' in cols:
            df['full_address'] = df['direccion'] + ", Buenos Aires, Argentina"
        else:
             logger.warning("No se pudo construir la dirección automáticamente. Revise nombres de columnas.")
             # Lista vacía para no romper, pero el usuario deberá ajustar los nombres de columnas
             df['full_address'] = None

    # Filtrar solo las que tienen dirección válida para no perder tiempo
    df_to_process = df.dropna(subset=['full_address']).copy()
    
    # Muestreo para pruebas rápidas (comentar para producción completa)
    # df_to_process = df_to_process.head(20) 
    
    service = GeocodingService()
    df_processed = service.bulk_geocode(df_to_process, address_col='full_address')
    
    # Guardar
    settings.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    df_processed.to_parquet(output_file, index=False)
    logger.info(f"✅ Datos geocodificados guardados en: {output_file}")

if __name__ == "__main__":
    run_pipeline()