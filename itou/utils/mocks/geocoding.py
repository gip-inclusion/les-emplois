# https://api-adresse.data.gouv.fr/search/?q=10+PL+5+MARTYRS+LYCEE+BUFFON&limit=1&postcode=75015
BAN_GEOCODING_API_RESULT_MOCK = {
    "type": "Feature",
    "geometry": {"type": "Point", "coordinates": [2.316754, 48.838411]},
    "properties": {
        "label": "10 Place des Cinq Martyrs du Lycée Buffon 75015 Paris",
        "score": 0.5197687103594081,
        "housenumber": "10",
        "id": "75115_2048_00010",
        "name": "10 Place des Cinq Martyrs du Lycée Buffon",
        "postcode": "75015",
        "citycode": "75115",
        "x": 649850.81,
        "y": 6860034.75,
        "city": "Paris",
        "district": "Paris 15e Arrondissement",
        "context": "75, Paris, Île-de-France",
        "type": "housenumber",
        "importance": 0.6942,
        "street": "Place des Cinq Martyrs du Lycée Buffon",
    },
}
BAN_GEOCODING_API_WITH_RESULT_RESPONSE = {
    "type": "FeatureCollection",
    "version": "draft",
    "features": [BAN_GEOCODING_API_RESULT_MOCK],
    "attribution": "BAN",
    "licence": "ETALAB-2.0",
    "query": "10 PL 5 MARTYRS LYCEE BUFFON",
    "filters": {"postcode": "75015"},
    "limit": 1,
}

# https://api-adresse.data.gouv.fr/search/?q=10+PL+5+ANATOLE&limit=1&postcode=75010
BAN_GEOCODING_API_NO_RESULT_MOCK = {
    "type": "FeatureCollection",
    "version": "draft",
    "features": [],
    "attribution": "BAN",
    "licence": "ETALAB-2.0",
    "query": "10 PL 5 ANATOLE",
    "filters": {"postcode": "75010"},
    "limit": 1,
}
