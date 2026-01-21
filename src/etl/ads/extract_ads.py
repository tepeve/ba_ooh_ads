import os
import requests
import logging
from pathlib import Path
from src.config import settings

# Configuración de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constantes
FILENAME = "padron_anuncios.csv"

def download_file(url: str, dest_folder: Path, filename: str, force: bool = False) -> Path:
    """
    Descarga un archivo desde una URL si no existe localmente.
    
    Args:
        url: URL del archivo a descargar.
        dest_folder: Carpeta de destino (Path object).
        filename: Nombre del archivo a guardar.
        force: Si es True, descarga el archivo incluso si ya existe.
        
    Returns:
        Path completo al archivo descargado.
    """
    dest_path = dest_folder / filename
    
    # Crear directorio si no existe
    dest_folder.mkdir(parents=True, exist_ok=True)

    # Verificar si el archivo ya existe
    if dest_path.exists() and not force:
        logger.info(f"El archivo ya existe en {dest_path}. Saltando descarga.")
        return dest_path

    logger.info(f"Iniciando descarga desde {url}...")
    
    try:
        # Usamos stream=True para no cargar archivos gigantes en memoria RAM de golpe
        with requests.get(url, stream=True) as response:
            response.raise_for_status() # Lanza error si la respuesta no es 200 OK
            
            # Escribir el archivo en bloques (chunks)
            with open(dest_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
        
        logger.info(f"Descarga completada exitosamente: {dest_path}")
        return dest_path

    except requests.exceptions.RequestException as e:
        logger.error(f"Error descargando el archivo: {e}")
        # Si falló la descarga y quedó un archivo corrupto a medio escribir, lo borramos
        if dest_path.exists():
            dest_path.unlink()
        raise e

def main():
    """Función principal del módulo de extracción."""
    try:
        file_path = download_file(settings.ADS_DATA_URL, settings.RAW_DIR, FILENAME, force=False)
        logger.info(f"✅ Extracción completada. Datos disponibles en: {file_path}")
    except Exception as e:
        logger.critical(f"❌ Falló la extracción: {e}")
        exit(1)

if __name__ == "__main__":
    main()