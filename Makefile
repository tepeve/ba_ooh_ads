.PHONY: build up down shell etl clean

# Construir la imagen
build:
	docker-compose build

# Levantar la app (Shiny) en segundo plano
up:
	docker-compose up -d

# Ver logs
logs:
	docker-compose logs -f

# Bajar todo
down:
	docker-compose down

# Entrar a la terminal del contenedor (para debuggear)
shell:
	docker-compose run --rm app /bin/bash

# Descargar capas base (Barrios, Comunas)
layers:
	docker-compose run --rm app python src/etl/population/extract_govmaps.py
	
# Ejecutar el Pipeline ETL completo dentro de Docker
ads:
	docker-compose run --rm app python src/etl/ads/extract_ads.py
	docker-compose run --rm app python src/etl/ads/transform_ads.py

# Descargar osm pois
osm_pois:
	docker-compose run --rm app python src/etl/pois/extract_osm_pois.py
	docker-compose run --rm app python src/etl/pois/pois_macro_categories.py
	docker-compose run --rm app python src/etl/pois/centrality_clustering.py

# Calcular alcance poblacional
popu_reach:
	docker-compose run --rm app python src/etl/population/population_reach.py

consolidate:
	docker-compose run --rm app python src/etl/ads/consolidate_ads.py

# Pipeline completo actualizado
etl-full: layers ads osm_pois popu_reach consolidate  

# Limpiar archivos temporales y caché de Python
clean_cache:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

# Borrar todos los archivos en data/ (útil para reiniciar el entorno)
clean_data:
	sudo rm -rf data/*