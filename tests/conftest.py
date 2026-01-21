import pytest
import pandas as pd
from pathlib import Path
from src.config import settings

@pytest.fixture(scope="function")
def mock_env_dirs(tmp_path, monkeypatch):
    """
    Sobrescribe las rutas de configuración para apuntar a un directorio temporal.
    Esto aísla los tests del sistema de archivos real.
    """
    # Crear estructura de directorios fake
    (tmp_path / "data" / "raw").mkdir(parents=True)
    (tmp_path / "data" / "processed").mkdir(parents=True)
    (tmp_path / "data" / "cache").mkdir(parents=True)
    (tmp_path / "data" / "external").mkdir(parents=True)

    # Sobrescribir las variables de la instancia settings
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "RAW_DIR", tmp_path / "data" / "raw")
    monkeypatch.setattr(settings, "PROCESSED_DIR", tmp_path / "data" / "processed")
    monkeypatch.setattr(settings, "EXTERNAL_DIR", tmp_path / "data" / "external")
    monkeypatch.setattr(settings, "CACHE_DIR", tmp_path / "data" / "cache")
    monkeypatch.setattr(settings, "GEOCODE_DB_PATH", tmp_path / "data" / "cache" / "test_geocache.db")
    
    return tmp_path

@pytest.fixture
def sample_ad_csv(mock_env_dirs):
    """
    Crea un CSV 'sucio' minimalista simulando el padron de anuncios.
    """
    df = pd.DataFrame({
        "NRO_ANUNCIO": [1001, 1002, 1003],
        "TIPO": ["PANTALLA LED", "Cartel Saliente", "Mobiliario Urbano"],
        "DOMICILIO_CALLE": ["AV. CORRIENTES", "Rivadavia", "Avda Santa Fe"],
        "DOMICILIO_ALTURA": [1000, 2000, None], # Un caso sin altura
        "CLASE": ["LED", "FRONTAL", "TEST"],
        "CARACTERISTICA": ["SIMPLE", "DOBLE", "NULL"],
        "METROS": ["10,5", "5.2", None],
        "FECHA_ALTA_ANUNCIO": ["2023-01-01", "2023-02-01", "invalid-date"]
    })
    
    file_path = settings.RAW_DIR / "padron_anuncios.csv"
    df.to_csv(file_path, index=False)
    return file_path
