



## 📁 Estructura del Repositorio
```
ba_ooh_ads/
├── .venv/                # Gestionado por uv
├── data/
│   ├── raw/              # Datos crudos (el CSV de la web)
│   ├── processed/        # Datos limpios (Parquet con lat/lon)
│   ├── external/         # GeoJSONs de barrios, etc.
│   └── cache/            # Tu base de datos SQLite (geocoding.db)
├── src/
│   ├── etl/              # Scripts de extracción y transformación
│   │   ├── extract.py    # Descarga de datos
│   │   ├── geocoding.py  # Lógica con caché y APIs
│   │   └── transform.py  # Limpieza y normalización
│   ├── analysis/            # Lógica de negocio / Data Science
│   │   ├── __init__.py
│   │   ├── grids.py         # H3, geohash.
│   │   ├── clustering.py    # DBSCAN, K-Means
│   │   └── metrics.py       # Cálculos de densidad, distancias de red
│   └── utils/               # Funciones auxiliares genéricas
│       ├── __init__.py
│       └── spatial.py       # Conversiones H3/Geohash
├── app/                     # Aplicación Streamlit
│   ├── main.py              # Entrypoint de Streamlit
│   └── components/          # Módulos de UI (mapas, filtros, gráficos)
├── notebooks/               # Para experimentación (sandbox)
│   └── 01_exploratorio.ipynb
├── tests/                   # Tests unitarios (pytest)
├── Dockerfile
├── docker-compose.yml
├── Makefile                 # Comandos rápidos (make run, make etl)
├── pyproject.toml           # Configuración de uv y dependencias
└── README.md                # Documentación del proyecto
```

