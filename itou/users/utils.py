import re


# https://fr.wikipedia.org/wiki/Num%C3%A9ro_de_s%C3%A9curit%C3%A9_sociale_en_France#Signification_des_chiffres_du_NIR
NIR_RE = re.compile(
    """
    ^
    [0-9]      # sexe
    [0-9]{2}   # année de naissance
    [0-9]{2}   # mois de naissance
    [0-9]      # premier chiffre du département
    [0-9AB]  # deuxième chiffre du département
    [0-9]{3}   # lieu de naissance
    [0-9]{3}   # numéro d’ordre de naissance
    [0-9]{2}   # clé
    $""",
    re.IGNORECASE | re.VERBOSE,
)
