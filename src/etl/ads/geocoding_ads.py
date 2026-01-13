import sqlite3
import time
import logging
from pathlib import Path
from typing import Optional, Tuple, List

import pandas as pd
from geopy.geocoders import Photon #, Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError, GeocoderUnavailable

# Configuración de logging para este módulo
logger = logging.getLogger(__name__)

class GeocodingService:
    def __init__(self, db_path: str = "data/cache/geocache.db", user_agent: str = "ba_ooh_ads"):
        """
        Servicio de geocodificación con caché persistente en SQLite.
        
        Args:
            db_path: Ruta relativa al archivo de base de datos SQLite.
            user_agent: Identificador único requerido por los términos de uso de Nominatim.
        """
        self.db_path = Path(db_path)
        self.user_agent = user_agent
        #self.geolocator = Nominatim(user_agent=self.user_agent)
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
            count = conn.execute("SELECT count(*) FROM geocache").fetchone()[0]
        logger.info(f"GeocodingService inicializado. Entradas en caché: {count}")

    def _get_from_cache(self, address: str) -> Optional[Tuple[float, float]]:
        """Busca coordenadas en la caché local."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT lat, long FROM geocache WHERE address = ?", (address,))
            result = cursor.fetchone()
            if result:
                return result
        return None

    def _save_to_cache(self, data: List[Tuple]):
        """
        Guarda una lista de resultados en la caché de una sola vez (Bulk Insert).
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



    def geocode(self, address: str, delay: float = 1.0, timeout: int = 5, exactly_one: bool = True) -> Tuple[Optional[float], Optional[float]]:        
        """
        Geocodifica una dirección individual.
        Prioriza la caché. Si no está, consulta la API y espera 'delay' segundos.
        """
        if not address or pd.isna(address):
            return None, None, None

        clean_address = address.strip().title()

        # 1. Intentar Caché
        cached = self._get_from_cache(clean_address)
        if cached:
            return address, cached[0], cached[1]
        
        # 2. Consultar API
        try:
            location = self.geolocator.geocode(address, timeout=timeout, exactly_one=exactly_one)
            time.sleep(delay)
            if location:
                self._save_to_cache([(clean_address, location.latitude, location.longitude, str(location.raw))])
                return location.address, location.latitude, location.longitude
            else:
                logger.warning(f"Dirección no encontrada: {address}")
                return None, None, None

        except (GeocoderTimedOut, GeocoderUnavailable) as e:
            logger.error(f"Error de conexión/timeout con {address}: {e}")
            time.sleep(2)
            return None, None, None
        
        
    def bulk_geocode(self, df: pd.DataFrame, address_col: str, delay: float = 1.0, timeout: int = 5) -> pd.DataFrame:
        """
        Procesa un DataFrame completo y agrega columnas 'lat' y 'lon'.
        Muestra progreso y estadísticas al final.
        """
        total = len(df)
        logger.info(f"Iniciando geocoding masivo de {total} registros...")
        
        addresses = []
        lats = []
        lons = []
        cache_hits = 0
        api_calls = 0
        
        # Iteramos sobre el DataFrame
        # Nota: Usamos itertuples() que es más rápido que iterrows()
        for i, row in enumerate(df.itertuples(), 1):
            address = getattr(row, address_col)
            clean_addr = str(address).strip().lower() if address else ""
            if self._get_from_cache(clean_addr):
                cache_hits += 1
            else:
                api_calls += 1
                if i % 10 == 0:
                    logger.info(f"Procesando {i}/{total} - (API Calls recientes...)")

            address, latitude, longitude = self.geocode(address, delay=delay, timeout=timeout, exactly_one=True)
            
            addresses.append(address)
            lats.append(latitude)
            lons.append(longitude)

        # Asignar resultados al DF
        df['address'] = addresses
        df['lat'] = lats
        df['long'] = lons
        
        logger.info(f"Geocoding finalizado. Hits Caché: {cache_hits} | API Calls: {api_calls}")
        return df

if __name__ == "__main__":
    # Prueba rápida si corres este script directamente
    logging.basicConfig(level=logging.INFO)
    service = GeocodingService()
    latitude, longitude = service.geocode("Obelisco, Buenos Aires, Argentina")
    print(f"Resultado Prueba: Lat={latitude}, Lon={longitude}")