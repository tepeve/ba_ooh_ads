import pytest
import sqlite3
import pandas as pd
from unittest.mock import MagicMock
from src.etl.ads.geocoding_ads import GeocodingService
from src.config import settings

@pytest.fixture
def geocoding_service(mock_env_dirs):
    """Instancia el servicio usando la DB temporal del mock_env."""
    return GeocodingService(db_path=settings.GEOCODE_DB_PATH)

def test_geocode_fetches_from_cache(geocoding_service, mocker):
    """Si la dirección está en BD, no llama a la API."""
    # 1. Pre-poblar la base de datos simulada
    with sqlite3.connect(geocoding_service.db_path) as conn:
        conn.execute(
            "INSERT INTO geocache (address, lat, long, raw_response) VALUES (?, ?, ?, ?)",
            ("calle falsa 123", -34.0, -58.0, "{}")
        )
    
    # 2. Mockear la API (geopy) para asegurar que NO se llame
    # Necesitamos acceder al objeto geolocator interno
    mock_api = mocker.patch.object(geocoding_service.geolocator, 'geocode')
    
    # 3. Ejecutar
    addr, lat, lon = geocoding_service.geocode("Calle Falsa 123") # Normaliza a minúsculas internamente
    
    # 4. Validar
    assert lat == -34.0
    assert lon == -58.0
    mock_api.assert_not_called()

def test_geocode_calls_api_and_saves(geocoding_service, mocker):
    """Si no está en caché, llama a API y guarda."""
    # 1. Mockear respuesta de API
    mock_location = MagicMock()
    mock_location.latitude = -34.1
    mock_location.longitude = -58.1
    mock_location.address = "Calle Real 123, BA"
    mock_location.raw = {"place_id": 1}
    
    mock_api = mocker.patch.object(geocoding_service.geolocator, 'geocode', return_value=mock_location)
    
    # 2. Ejecutar
    addr, lat, lon = geocoding_service.geocode("Calle Real 123")
    
    # 3. Validar retorno
    assert lat == -34.1
    
    # 4. Validar persistencia en DB
    with sqlite3.connect(geocoding_service.db_path) as conn:
        row = conn.execute("SELECT lat, long FROM geocache WHERE address = ?", ("calle real 123",)).fetchone()
        assert row is not None
        assert row[0] == -34.1
