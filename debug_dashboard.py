import duckdb
import os

# Configuration
FILE_PATH = "data/processed/tablero_anuncios_consolidado.parquet"

def inspect_parquet():
    print(f"--- Debugging {FILE_PATH} ---")

    # 1. Verify existence
    if not os.path.exists(FILE_PATH):
        print(f"ERROR: File {FILE_PATH} not found.")
        return

    print("File exists.")
    
    con = duckdb.connect()
    
    # 2. Schema
    print("\n--- Schema ---")
    try:
        schema = con.execute(f"DESCRIBE SELECT * FROM '{FILE_PATH}'").fetchall()
        for col in schema:
            print(f"{col[0]}: {col[1]}")
    except Exception as e:
        print(f"Error reading schema: {e}")
        return
        
    # 3. Total Rows
    print("\n--- Total Rows ---")
    total_rows = con.execute(f"SELECT COUNT(*) FROM '{FILE_PATH}'").fetchone()[0]
    print(f"Rows: {total_rows}")
    
    # 4. Distinct needs_geocoding
    print("\n--- Needs Geocoding Distribution ---")
    dist = con.execute(f"SELECT needs_geocoding, COUNT(*) FROM '{FILE_PATH}' GROUP BY needs_geocoding").fetchall()
    for val, count in dist:
        print(f"Value: {val} (Type: {type(val)}), Count: {count}")
        
    # 5. Min/Max Lat/Long
    print("\n--- Lat/Long Stats ---")
    stats = con.execute(f"SELECT MIN(lat), MAX(lat), MIN(long), MAX(long) FROM '{FILE_PATH}'").fetchone()
    print(f"Lat: [{stats[0]}, {stats[1]}]")
    print(f"Long: [{stats[2]}, {stats[3]}]")
    
    # 6. APP Logic Simulation
    print("\n--- App Logic Filter Simulation ---")
    
    # Get options (excluding nulls, mimicking load_filter_options)
    options = [r[0] for r in con.execute(f"SELECT DISTINCT needs_geocoding FROM '{FILE_PATH}' WHERE needs_geocoding IS NOT NULL").fetchall()]
    print(f"Options for needs_geocoding: {options}")
    
    where_clauses = [
        "lat IS NOT NULL", 
        "long IS NOT NULL",
        "lat != 0",
        "long != 0",
        "lat BETWEEN -35 AND -34", 
        "long BETWEEN -59 AND -58"
    ]
    
    # Run spatial only
    sql_spatial = f"SELECT COUNT(*) FROM '{FILE_PATH}' WHERE {' AND '.join(where_clauses)}"
    count_spatial = con.execute(sql_spatial).fetchone()[0]
    print(f"Rows satisfying spatial filter: {count_spatial}")
    
    # Add needs_geocoding filter
    # Logic: OR condition for selected values
    # Simulating ALL options selected
    geo_conditions = []
    for val in options:
        if isinstance(val, bool):
             geo_conditions.append(f"needs_geocoding = {str(val).upper()}")
        elif str(val).lower() == 'true':
            geo_conditions.append("needs_geocoding = TRUE")
        elif str(val).lower() == 'false':
            geo_conditions.append("needs_geocoding = FALSE")
        else:
            geo_conditions.append(f"needs_geocoding = '{val}'")
            
    if geo_conditions:
        full_clauses = where_clauses + [f"({' OR '.join(geo_conditions)})"]
        sql_full = f"SELECT COUNT(*) FROM '{FILE_PATH}' WHERE {' AND '.join(full_clauses)}"
        
        print(f"Full Query WHERE snippet: ... AND ({' OR '.join(geo_conditions)})")
        
        count_full = con.execute(sql_full).fetchone()[0]
        print(f"Rows satisfying spatial AND needs_geocoding: {count_full}")
    else:
        print("No options available for needs_geocoding (effectively 0 results if filter applied).")

    # Check mandatory filters (Clase/Tipo)
    print("\n--- Check Mandatory Columns ---")
    n_clase = con.execute(f"SELECT COUNT(DISTINCT clase) FROM '{FILE_PATH}'").fetchone()[0]
    n_tipo = con.execute(f"SELECT COUNT(DISTINCT tipo) FROM '{FILE_PATH}'").fetchone()[0]
    print(f"Distinct Clase: {n_clase}")
    print(f"Distinct Tipo: {n_tipo}")

    # Check Cluster Columns
    print("\n--- Check Cluster Columns ---")
    target_cols = ['cluster_global', 'cluster_tematico', 'macro_category']
    existing_col_names = [s[0] for s in schema]
    
    for col in target_cols:
        if col in existing_col_names:
            print(f"✅ {col} exists.")
            # Print stats
            try:
                stats = con.execute(f"SELECT COUNT(*), COUNT({col}), COUNT(DISTINCT {col}) FROM '{FILE_PATH}'").fetchone()
                print(f"   Total: {stats[0]}, Non-Null: {stats[1]}, Distinct: {stats[2]}")
            except Exception as e:
                print(f"   Error analyzing {col}: {e}")
        else:
            print(f"❌ {col} is MISSING.")
    
    con.close()

if __name__ == "__main__":
    inspect_parquet()