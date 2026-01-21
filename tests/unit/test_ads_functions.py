import pytest
import pandas as pd
from pathlib import Path
from unittest.mock import MagicMock
import requests

from src.etl.ads.transform_ads import clean_column_name, normalize_address_text
from src.etl.ads.extract_ads import download_file

# --- Transform Tests ---

@pytest.mark.parametrize("input_str, expected", [
    ("NRO ANUNCIO", "nro_anuncio"),
    ("Domicilio Calle", "domicilio_calle"),
    ("Árbol", "arbol"), # Tildes
    ("  Espacios  Extra  ", "espacios_extra"),
    ("Mixed.Punctuation", "mixedpunctuation"),
])
def test_clean_column_name(input_str, expected):
    """Valida la normalización de nombres de columnas."""
    assert clean_column_name(input_str) == expected

def test_normalize_address_text():
    """Valida que las regex de direcciones funcionen correctamente."""
    df = pd.DataFrame({
        "calle": ["Av. Corrientes", "Avda Santa Fe", "Pje. Obelisco", "Calle  Con  Espacios", "Tte Gral Peron"]
    })
    
    result = normalize_address_text(df, "calle")
    
    expected = [
        "Avenida Corrientes",
        "Avenida Santa Fe",
        "Obelisco", # Pje se elimina
        "Calle Con Espacios", # Espacios colapsados
        "Peron" # Tte Gral se elimina
    ]
    assert result.tolist() == expected

# --- Extract Tests ---

def test_download_file_success(mock_env_dirs, mocker):
    """Testea descarga exitosa escribiendo chunks."""
    # Mock de requests.get retornando un objeto que soporta context manager y iter_content
    mock_response = MagicMock()
    mock_response.iter_content.return_value = [b"chunk1", b"chunk2"]
    mock_response.status_code = 200
    
    mock_get = mocker.patch("requests.get", return_value=mock_response)
    # Necesario para el contexto `with requests.get(...) as r:`
    mock_response.__enter__.return_value = mock_response
    mock_response.__exit__.return_value = None

    dest_folder = mock_env_dirs / "data" / "raw"
    output_path = download_file("http://fake.url/file.csv", dest_folder, "test.csv")

    assert output_path.exists()
    assert output_path.read_bytes() == b"chunk1chunk2"

def test_download_file_failure_cleanup(mock_env_dirs, mocker):
    """Testea que si falla la descarga, se borre el archivo parcial."""
    mock_response = MagicMock()
    # Simulamos que falla a mitad de camino
    mock_response.iter_content.side_effect = requests.exceptions.ChunkedEncodingError("Connection broken")
    
    mocker.patch("requests.get", return_value=mock_response)
    mock_response.__enter__.return_value = mock_response
    mock_response.__exit__.return_value = None
    
    dest_folder = mock_env_dirs / "data" / "raw"
    
    with pytest.raises(requests.exceptions.RequestException):
        download_file("http://fake.url/file.csv", dest_folder, "fail.csv")
    
    # El archivo no debería existir (cleanup)
    assert not (dest_folder / "fail.csv").exists()
