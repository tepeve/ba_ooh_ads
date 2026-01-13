from io import BytesIO
import h3
import pandas as pd
import geopandas as gpd
from typing import Optional
import requests
import logging

logger = logging.getLogger(__name__)


def download_map(url: str) -> gpd.GeoDataFrame:
    """Descarga un GeoJSON y lo devuelve como GeoDataFrame."""
    logger.info(f"Descargando datos desde: {url}")
    response = requests.get(url)
    response.raise_for_status()
    
    # Cargar directamente desde memoria
    gdf = gpd.read_file(BytesIO(response.content))

    gdf = gpd.GeoDataFrame(gdf, geometry='geometry')
    return gdf
    

# def add_h3_index(df: pd.DataFrame, lat_col: str = 'lat', lon_col: str = 'long', resolution: int = 10) -> pd.DataFrame:
#     """
#     Agrega una columna 'h3_index' al DataFrame basada en latitud y longitud.
    
#     Args:
#         df: DataFrame con coordenadas.
#         resolution: Resolución H3 (9 es aprox 0.1km2, nivel manzana).
#     """
#     def get_h3(row):
#         try:
#             # Nota: h3.latlng_to_cell es la API v4 (antes geo_to_h3)
#             return h3.latlng_to_cell(row[lat_col], row[lon_col], resolution)
#         except Exception:
#             return None

#     df[f'h3_res{resolution}'] = df.apply(get_h3, axis=1)
#     return df

def add_h3_index(
    df: pd.DataFrame,
    lat_col: str = "lat",
    lon_col: str = "long",
    resolution: int = 10,
    out_col: Optional[str] = None,
    inplace: bool = False,
) -> pd.Series | pd.DataFrame:
    """
    Calcula el índice H3 por fila a partir de lat/lon usando h3.latlng_to_cell.

    - Si inplace=False (default): devuelve una Series (1D) con los H3.
    - Si inplace=True: agrega la columna al DataFrame y devuelve el DataFrame.

    out_col:
      - Si None, usa f"h3_res{resolution}"
    """
    if out_col is None:
        out_col = f"h3_res{resolution}"

    if lat_col not in df.columns or lon_col not in df.columns:
        raise KeyError(f"Faltan columnas requeridas: {lat_col=} {lon_col=}")

    lat = df[lat_col]
    lon = df[lon_col]
    mask = lat.notna() & lon.notna()

    h3_series = pd.Series(index=df.index, dtype="object", name=out_col)
    if mask.any():
        # Más rápido que df.apply(axis=1)
        cells = [
            h3.latlng_to_cell(float(la), float(lo), resolution)
            for la, lo in zip(lat[mask].to_numpy(), lon[mask].to_numpy())
        ]
        h3_series.loc[mask] = cells

    if inplace:
        df[out_col] = h3_series
        return df

    return h3_series

def h3_parent_mapping(h3_index: str, parent_res: int) -> Optional[str]:
    """Obtiene el hexágono padre de una resolución menor."""
    try:
        return h3.cell_to_parent(h3_index, parent_res)
    except:
        return None


def join_with_admin_layer(
    df_points: pd.DataFrame, 
    gdf_admin: gpd.GeoDataFrame, 
    lat_col: str = 'lat', 
    lon_col: str = 'long'
) -> pd.DataFrame:
    """
    Realiza un Spatial Join entre puntos (DataFrame normal) y polígonos (GeoDataFrame).
    Devuelve el DataFrame original enriquecido con las columnas del polígono.
    """
    # Filtrar registros con coordenadas válidas
    valid_mask = df_points[lat_col].notna() & df_points[lon_col].notna()
    
    if not valid_mask.any():
        return df_points
    
    # Convertir DataFrame de puntos a GeoDataFrame
    gdf_points = gpd.GeoDataFrame(
        df_points[valid_mask].copy(),
        geometry=gpd.points_from_xy(
            df_points.loc[valid_mask, lon_col], 
            df_points.loc[valid_mask, lat_col]
        ),
        crs="EPSG:4326"
    )

    # Asegurar que ambos tengan el mismo CRS
    if gdf_admin.crs != gdf_points.crs:
        gdf_admin = gdf_admin.to_crs(gdf_points.crs)

    # Spatial Join (left join para no perder puntos que caigan fuera)
    gdf_joined = gpd.sjoin(gdf_points, gdf_admin, how="left", predicate="within")

    # Eliminar columna geometry y index_right generada por sjoin
    columns_to_drop = ['geometry', 'index_right']
    df_result = pd.DataFrame(gdf_joined.drop(columns=[c for c in columns_to_drop if c in gdf_joined.columns]))
    
    return df_result



# Helper para reparar geometrías inválidas en GeoDataFrames
def _repair_geometries(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Intenta reparar geometrías problemáticas en el GeoDataFrame:
    1) usa shapely.ops.make_valid si está disponible (mejor opción);
    2) fallback a geom.buffer(0) para arreglos topológicos comunes;
    3) elimina filas sin geometría válida al final.
    Devuelve el GeoDataFrame con la columna 'geometry' reparada.
    """
    if gdf is None or gdf.empty or "geometry" not in gdf.columns:
        return gdf

    try:
        from shapely.ops import make_valid
    except Exception:
        make_valid = None

    def _repair(geom):
        if geom is None:
            return None
        try:
            if make_valid is not None:
                repaired = make_valid(geom)
                if repaired is not None:
                    return repaired
            return geom.buffer(0)
        except Exception:
            # devolver geom original si todo falla
            return geom

    try:
        gdf = gdf.copy()
        gdf["geometry"] = gdf["geometry"].apply(_repair)
        # quitar filas sin geometría válida
        gdf = gdf[~gdf["geometry"].isna()].copy()
    except Exception:
        logger.exception("No fue posible aplicar reparación automática de geometrías.")
    return gdf

def _safe_read_shapefile(shp_path: str) -> gpd.GeoDataFrame:
    """
    Intenta leer un shapefile con geopandas. Si falla por errores de ring/LinearRing,
    intenta ejecutar `ogr2ogr` para "reparar" y convierte a GeoJSON temporal, luego leerlo.
    Si `ogr2ogr` no está disponible, relanza la excepción con mensaje instructivo.
    """
    try:
        return gpd.read_file(shp_path)
    except Exception as e:
        msg = str(e).lower()
        # detectar errores típicos relacionados con anillos no cerrados/winding
        if "linearring" in msg or "linear ring" in msg or "closed" in msg or "ring" in msg:
            import shutil
            import subprocess
            from pathlib import Path
            tmp_dir = None

            # verificar si ogr2ogr está disponible
            if shutil.which("ogr2ogr") is None:
                raise RuntimeError(
                    "gpd.read_file falló por geometrías inválidas y 'ogr2ogr' no está disponible. "
                    "Instalá 'gdal-bin' en el sistema/imagen Docker o ejecutá manualmente ogr2ogr para reparar el shapefile. "
                    "Mensaje original: " + str(e)
                ) from e

            # intentar reparar con ogr2ogr a GeoJSON temporal
            try:
                tmp_dir = tempfile.TemporaryDirectory()
                out_path = Path(tmp_dir.name) / "repaired.geojson"
                # usar -skipfailures para omitir features que no se puedan convertir
                cmd = [
                    "ogr2ogr",
                    "-f", "GeoJSON",
                    str(out_path),
                    str(shp_path),
                    "-nlt", "MULTIPOLYGON",
                    "-skipfailures"
                ]
                subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                # leer el geojson reparado
                gdf = gpd.read_file(str(out_path))
                return gdf
            except subprocess.CalledProcessError as cpe:
                raise RuntimeError(
                    "ogr2ogr falló intentando reparar el shapefile. "
                    "Salida: " + (cpe.stderr.decode(errors="ignore") if hasattr(cpe, 'stderr') else str(cpe))
                ) from e
            except Exception as e2:
                raise RuntimeError("Error al intentar reparar shapefile con ogr2ogr: " + str(e2)) from e
            finally:
                if tmp_dir is not None:
                    try:
                        tmp_dir.cleanup()
                    except Exception:
                        pass
        # si no parece un error de LinearRing, relanzar original
        raise