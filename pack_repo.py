import os
import sys

# ================= CONFIGURACIÓN =================
# Esta línea mágica encuentra la carpeta donde está guardado este script
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Carpetas relativas a la ubicación del script
TARGET_DIRS = ['src', 'app', 'tests', 'ba_ooh_ads'] # Agregué 'ba_ooh_ads' por si la estructura es anidada

# Archivos sueltos importantes
ROOT_FILES = [
    'Dockerfile', 'docker-compose.yml', 'Makefile', 
    'pyproject.toml', 'requirements.txt', 'README.md',
    'PROJECT_CONTEXT.md', '.env.example'
]

ALLOWED_EXTENSIONS = {'.py', '.md', '.sql', '.toml', '.yml', '.yaml', '.sh', '.json'}
OUTPUT_FILE = os.path.join(BASE_DIR, "repositorio_final.md")
# =================================================

def pack_repo():
    content = f"# REPOSITORIO: {os.path.basename(BASE_DIR)}\n\n"
    total_files = 0
    
    print(f"📍 Escaneando proyecto en: {BASE_DIR}")

    # 1. Procesar archivos raíz
    content += "## Archivos Raíz\n"
    for file_name in ROOT_FILES:
        full_path = os.path.join(BASE_DIR, file_name)
        if os.path.exists(full_path):
            content += add_file_content(full_path, BASE_DIR)
            total_files += 1

    # 2. Procesar carpetas objetivo
    for target_dir in TARGET_DIRS:
        full_target_path = os.path.join(BASE_DIR, target_dir)
        
        if not os.path.exists(full_target_path):
            continue
            
        content += f"\n## Carpeta: {target_dir}/\n"
        for root, _, files in os.walk(full_target_path):
            if '__pycache__' in root or '.pytest_cache' in root:
                continue
                
            for file in files:
                _, ext = os.path.splitext(file)
                if ext in ALLOWED_EXTENSIONS or file in ['Dockerfile']:
                    file_path = os.path.join(root, file)
                    content += add_file_content(file_path, BASE_DIR)
                    total_files += 1

    return content, total_files

def add_file_content(file_path, base_path):
    try:
        # Ignorar archivos > 100KB
        if os.path.getsize(file_path) > 100 * 1024: 
            return f"\n# [OMITIDO POR TAMAÑO: {os.path.basename(file_path)}]\n"

        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            file_content = f.read()
            
        relative_path = os.path.relpath(file_path, base_path)
        return (
            f"\n# ==========================================\n"
            f"# FILE: {relative_path}\n"
            f"# ==========================================\n"
            f"```python\n"
            f"{file_content}\n"
            f"```\n"
        )
    except Exception as e:
        return f"\n# Error leyendo {file_path}: {e}\n"

if __name__ == "__main__":
    full_content, count = pack_repo()
    
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(full_content)
    
    size_mb = os.path.getsize(OUTPUT_FILE) / (1024 * 1024)
    print(f"✅ ¡Listo! Procesados {count} archivos.")
    print(f"📁 Archivo generado en: {OUTPUT_FILE}")
    print(f"⚖️  Peso final: {size_mb:.2f} MB")