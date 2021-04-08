TABLE_COLUMNS = [
    {
        "name": "code_rome",
        "type": "varchar",
        "comment": "Code ROME",
        "lambda": lambda o: o.code,
    },
    {
        "name": "description_code_rome",
        "type": "varchar",
        "comment": "Description du code ROME",
        "lambda": lambda o: o.name,
    },
]
