TABLE_COLUMNS = [
    {
        "name": "nom",
        "type": "varchar",
        "comment": "Nom",
        "fn": lambda o: o.name,
    },
    {
        "name": "code_insee",
        "type": "varchar",
        "comment": "Code INSEE",
        "fn": lambda o: o.code_insee,
    },
    {
        "name": "latitude",
        "type": "float",
        "comment": "Latitude",
        "fn": lambda o: o.latitude,
    },
    {
        "name": "longitude",
        "type": "float",
        "comment": "Longitude",
        "fn": lambda o: o.longitude,
    },
]
