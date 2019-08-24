"""
Result for a call to:
https://api-adresse.data.gouv.fr/search/?q=10+PL+5+MARTYRS+LYCEE+BUFFON&limit=1&postcode=75015
"""

BAN_GEOCODING_API_RESULT_MOCK = {
    "type": "Feature",
    "geometry": {"type": "Point", "coordinates": [2.316754, 48.838411]},
    "properties": {
        "label": "10 Pl des Cinq Martyrs du Lycee Buffon 75015 Paris",
        "score": 0.587663373207207,
        "housenumber": "10",
        "id": "75115_2048_00010",
        "type": "housenumber",
        "name": "10 Pl des Cinq Martyrs du Lycee Buffon",
        "postcode": "75015",
        "citycode": "75115",
        "x": 649850.81,
        "y": 6860034.74,
        "city": "Paris",
        "district": "Paris 15e Arrondissement",
        "context": "75, Paris, Île-de-France",
        "importance": 0.6950663360485076,
        "street": "Pl des Cinq Martyrs du Lycee Buffon",
    },
}
