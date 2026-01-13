import pandas as pd
from pathlib import Path


PROCESSED_DATA_DIR = Path("data/processed")

df = pd.read_csv(PROCESSED_DATA_DIR / "osm_pois_unique_subtags.csv")

mapping_rules = {
    'gastronomy': [
        'restaurant', 'cafe', 'fast_food', 'ice_cream', 'food_court', 'canteen', 'biergarten', 'tea'
    ],
    'tourism_and_entertainment': [
        'hotel','hostel','guest_house', 'motel', 'travel_agent','bar', 'pub', 'nightclub', 'cinema', 'theatre', 'casino', 'arts_centre', 'gambling', 'stripclub', 'events_venue','gallery','viewpoint', 'zoo', 'theme_park', 'video_games'
    ],
    'fashion_and_clothes': [
        'clothes', 'shoes', 'jewelry', 'fashion', 'gift', 'bag', 'watches', 'leather', 'tailor', 'second_hand', 'fabric', 'baby_goods','women','toys','sports','mall'
    ],
    'health_and_beauty': [
        'pharmacy', 'hairdresser', 'clinic', 'dentist', 'doctors', 'hospital', 'beauty', 'optician', 'cosmetics', 'massage', 'tattoo', 'spa', 'physiotherapist'
    ],
    'daily_supply_services': [
        'supermarket', 'convenience', 'bakery', 'butcher', 'greengrocer', 'kiosk', 'laundry', 'dry_cleaning', 'pet', 'veterinary', 'beverages', 'seafood', 'deli', 'health_food', 'lottery', 'florist', 'photo','cheese', 'pasta','confectionery','general'
    ],
    'education_and_culture': [
        'school', 'college', 'university', 'kindergarten', 'library', 'museum', 'books', 'stationery', 'music_school', 'language_school', 'tuition', 'art_school','place_of_worship','artwork', 'memorial','monument','musical_instrument', 'ticket'
    ],
    'finance_and_corporate': [
        'bank', 'estate_agent', 'insurance', 'lawyer', 'company', 'office', 'coworking', 'travel_agency', 'post_office', 'employment_agency', 'architect', 'notary', 'money_lender','government', 'trade','payment_centre','diplomatic'
    ],
    'automotive_and_transport': [
        'car_repair', 'car', 'fuel', 'parking', 'car_parts', 'motorcycle', 'bicycle', 'bicycle_rental', 'bicycle_repair', 'taxi', 'car_wash', 'charging_station', 'boat','tyres'
    ],
    'home_and_construction': [
        'hardware', 'furniture', 'paint', 'electronics', 'mobile_phone', 'locksmith', 'glaziery', 'doityourself', 'interior_decoration', 'garden_centre', 'carpet', 'curtain', 'flooring', 'kitchen', 'lighting', 'bed', 'computer', 'hifi', 'appliance','houseware'
    ],
    'sports_and_outdoor': [
        'park', 'fitness_centre', 'sports_centre', 'playground', 'stadium', 'pitch', 'swimming_pool', 'dance', 'yoga', 'dog_park', 'gym', 'picnic_site'
    ]
}


# Invertir el diccionario para mapeo directo tag -> categoria
tag_to_category = {}
for category, tags in mapping_rules.items():
    for tag in tags:
        tag_to_category[tag] = category

# Función para aplicar la categoría
def get_category(tag):
    # Busqueda directa
    if tag in tag_to_category:
        return tag_to_category[tag]
    
    # Busqueda parcial si no es exacto (heurística simple)
    for key_tag, category in tag_to_category.items():
        if key_tag in str(tag):
            return category
            
    return 'Otros'


# Aplicar al dataframe
df['macro_category'] = df['sub_tag'].apply(get_category)

mapping_param = {
0:'Otros',
1:['education_and_culture', 'health_and_beauty', 'sports_and_outdoor','finance_and_corporate','home_and_construction','automotive_and_transport' ],
2:['daily_supply_services', 'gastronomy', 'fashion_and_clothes', 'tourism_and_entertainment']
}

# Crear la columna param_type mapeando macro_category con las reglas de mapping_param
def get_param_type(macro_category):
    for param_type, categories in mapping_param.items():
        if macro_category in categories:
            return param_type
    return 0  # Si no coincide, asignar 'Otros' (0)

df['param_type'] = df['macro_category'].apply(get_param_type)


# Verificar resultados contando por categoría
summary = df.groupby('macro_category')['count'].sum().sort_values(ascending=False)
print(summary)

# Guardar resultado
df.to_csv(PROCESSED_DATA_DIR / "osm_pois_categorized.csv", index=False)

