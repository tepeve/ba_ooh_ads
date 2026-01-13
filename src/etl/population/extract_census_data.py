import duckdb
import pandas as pd
import geopandas as gpd

# Configurar DuckDB
con = duckdb.connect()
for cmd in [
    "INSTALL spatial",
    "LOAD spatial", 
    "INSTALL httpfs",
    "LOAD httpfs"
]:
    con.execute(cmd)





# Exportar datos combinados a archivo temporal
query = """
COPY (
    SELECT 
        g.cod_2022,
        g.prov,
        g.depto,
        g.pob_tot_p,
        g.geometry,
        c.codigo_variable,
        c.valor_categoria,
        c.etiqueta_categoria,
        c.conteo
    FROM 's3://arg-fulbright-data/censo-argentino-2022/radios-2022.parquet' g
    JOIN 's3://arg-fulbright-data/censo-argentino-2022/censo-2022-largo.parquet' c
        ON g.cod_2022 = c.id_geo
    WHERE c.codigo_variable = 'POB_TOT_P'
) TO 'temp_census_data.parquet' (FORMAT PARQUET);
"""

con.execute(query)

# Leer de vuelta en Python como GeoDataFrame
df = pd.read_parquet('temp_census_data.parquet')
df["geometry"] = gpd.GeoSeries.from_wkb(df["geometry"])
gdf = gpd.GeoDataFrame(df, geometry="geometry", crs="EPSG:4326")



# https://www.indec.gob.ar/indec/web/Institucional-Indec-BasesDeDatos-6