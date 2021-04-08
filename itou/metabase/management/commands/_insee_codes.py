TABLE_COLUMNS = [
    {
        "name": "nom",
        "type": "varchar",
        "comment": "Nom",
        "lambda": lambda o: o.name,
    },
    {
        "name": "code_insee",
        "type": "varchar",
        "comment": "Code INSEE",
        "lambda": lambda o: o.code_insee,
    },
    {
        "name": "latitude",
        "type": "float",
        "comment": "Latitude",
        "lambda": lambda o: o.latitude,
    },
    {
        "name": "longitude",
        "type": "float",
        "comment": "Longitude",
        "lambda": lambda o: o.longitude,
    },
]
