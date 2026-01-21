import pytest
import pandas as pd
import geopandas as gpd
import numpy as np
import h3
from shapely.geometry import Polygon, Point
from src.utils.utils_spatial import add_h3_index, join_with_admin_layer

# ==========================================
# Fixtures
# ==========================================

@pytest.fixture
def df_points_fixture():
    """
    Creates a DataFrame with:
    - ID 1: Valid (Obelisco, BA) -> Should match San Nicolas
    - ID 2: Valid (Palermo, BA)  -> Should match Palermo
    - ID 3: Invalid (NaN lat)
    - ID 4: Invalid (NaN long)
    """
    data = {
        'id': [1, 2, 3, 4],
        'lat': [-34.6037, -34.5711, np.nan, -34.6000], 
        'long': [-58.3816, -58.4233, -58.0000, np.nan],
        'extra_col': ['A', 'B', 'C', 'D']
    }
    return pd.DataFrame(data)

@pytest.fixture
def gdf_admin_fixture():
    """
    Creates a GeoDataFrame with 2 Polygons:
    1. San Nicolas (contains Obelisco)
    2. Palermo (contains Palermo point)
    """
    # Square roughly around Obelisco (-34.6037, -58.3816)
    poly1 = Polygon([
        (-58.39, -34.61), (-58.37, -34.61), 
        (-58.37, -34.60), (-58.39, -34.60), 
        (-58.39, -34.61)
    ])
    
    # Square roughly around Palermo (-34.5711, -58.4233)
    poly2 = Polygon([
        (-58.43, -34.58), (-58.41, -34.58), 
        (-58.41, -34.56), (-58.43, -34.56), 
        (-58.43, -34.58)
    ])

    data = {
        'barrio': ['San Nicolas', 'Palermo'],
        'comuna': [1, 14],
        'geometry': [poly1, poly2]
    }
    return gpd.GeoDataFrame(data, crs="EPSG:4326")

# ==========================================
# Tests: add_h3_index
# ==========================================

def test_add_h3_index_series(df_points_fixture):
    """Test default behavior returns a Series and handles NaNs correctly."""
    result = add_h3_index(
        df_points_fixture, 
        lat_col='lat', 
        lon_col='long', 
        resolution=9, 
        inplace=False
    )
    
    assert isinstance(result, pd.Series)
    assert len(result) == len(df_points_fixture)
    assert result.name == "h3_res9"
    
    # Valid coordinates should have H3 index
    assert result.iloc[0] is not None
    assert isinstance(result.iloc[0], str)
    
    # Invalid coordinates should be None/NaN
    assert pd.isna(result.iloc[2])
    assert pd.isna(result.iloc[3])

def test_add_h3_index_inplace(df_points_fixture):
    """Test inplace modification of the DataFrame."""
    df_res = add_h3_index(
        df_points_fixture.copy(), 
        lat_col='lat', 
        lon_col='long', 
        resolution=9, 
        inplace=True, 
        out_col='h3_idx'
    )
    
    assert isinstance(df_res, pd.DataFrame)
    assert 'h3_idx' in df_res.columns
    assert df_res.iloc[0]['h3_idx'] is not None

def test_add_h3_index_missing_cols(df_points_fixture):
    """Test error raised when columns are missing."""
    with pytest.raises(KeyError):
        add_h3_index(df_points_fixture, lat_col='non_existent_lat', lon_col='long')

# ==========================================
# Tests: join_with_admin_layer
# ==========================================

def test_join_with_admin_layer_basic(df_points_fixture, gdf_admin_fixture):
    """
    Test basic spatial join logic.
    Note: The function implicitly drops rows with invalid coordinates.
    """
    res = join_with_admin_layer(
        df_points_fixture, 
        gdf_admin_fixture, 
        lat_col='lat', 
        lon_col='long'
    )
    
    # Should only contain the 2 valid rows (ID 1 and 2), filtered by valid_mask
    assert len(res) == 2
    
    # Validate spatial match
    row1 = res[res['id'] == 1].iloc[0]
    assert row1['barrio'] == 'San Nicolas'
    assert row1['comuna'] == 1
    
    row2 = res[res['id'] == 2].iloc[0]
    assert row2['barrio'] == 'Palermo'
    assert row2['comuna'] == 14
    
    # Ensure geometry column was dropped from result
    assert 'geometry' not in res.columns
    assert 'index_right' not in res.columns

def test_join_with_admin_layer_crs_mismatch(df_points_fixture, gdf_admin_fixture):
    """Test that function handles CRS mismatch by reprojecting admin layer."""
    # Convert admin to Web Mercator (meters)
    gdf_admin_3857 = gdf_admin_fixture.to_crs("EPSG:3857")
    
    res = join_with_admin_layer(
        df_points_fixture, 
        gdf_admin_3857, 
        lat_col='lat', 
        lon_col='long'
    )
    
    assert len(res) == 2
    # Verify spatial join still works after internal reprojection
    assert res[res['id'] == 1].iloc[0]['barrio'] == 'San Nicolas'

def test_join_with_admin_layer_outside_points(df_points_fixture, gdf_admin_fixture):
    """Test valid points that fall outside any polygon (Left Join logic filtered by valid mask)."""
    # Create a point far away (0, 0)
    df_far = pd.DataFrame({'id': [99], 'lat': [0.0], 'long': [0.0]})
    
    res = join_with_admin_layer(df_far, gdf_admin_fixture)
    
    assert len(res) == 1
    # Should be preserved but with NaN admin attributes
    assert pd.isna(res.iloc[0]['barrio'])
    assert pd.isna(res.iloc[0]['comuna'])

def test_join_with_admin_layer_empty_input():
    """Test behavior with empty input DataFrame."""
    df_empty = pd.DataFrame(columns=['lat', 'long', 'id'])
    # Minimal valid admin gdf
    gdf_admin = gpd.GeoDataFrame({'col': [1], 'geometry': [Point(0,0)]}, crs="EPSG:4326")
    
    res = join_with_admin_layer(df_empty, gdf_admin)
    assert res.empty
    assert 'col' in res.columns or len(res.columns) == 3 # Depends if merge happens on empty

def test_join_with_admin_layer_bad_geoms(df_points_fixture, gdf_admin_fixture):
    """Test resilience against None geometries in admin layer."""
    # Add a row with None geometry
    new_row = gpd.GeoDataFrame({
        'barrio': ['Void'], 
        'comuna': [99], 
        'geometry': [None]
    }, crs=gdf_admin_fixture.crs)
    
    gdf_admin_with_nan = pd.concat([gdf_admin_fixture, new_row], ignore_index=True)
    
    # Should not crash and still process valid points
    res = join_with_admin_layer(df_points_fixture, gdf_admin_with_nan)
    
    assert len(res) == 2
    assert res[res['id'] == 1].iloc[0]['barrio'] == 'San Nicolas'
