import re

import unidecode


REGIONS = {
    "Auvergne-Rhône-Alpes": ["01", "03", "07", "15", "26", "38", "42", "43", "63", "69", "73", "74"],
    "Bourgogne-Franche-Comté": ["21", "25", "39", "58", "70", "71", "89", "90"],
    "Bretagne": ["35", "22", "56", "29"],
    "Centre-Val de Loire": ["18", "28", "36", "37", "41", "45"],
    "Corse": ["2A", "2B"],
    "Grand Est": ["08", "10", "51", "52", "54", "55", "57", "67", "68", "88"],
    "Guadeloupe": ["971"],
    "Guyane": ["973"],
    "Hauts-de-France": ["02", "59", "60", "62", "80"],
    "Île-de-France": ["75", "77", "78", "91", "92", "93", "94", "95"],
    "La Réunion": ["974"],
    "Martinique": ["972"],
    "Mayotte": ["976"],
    "Normandie": ["14", "27", "50", "61", "76"],
    "Nouvelle-Aquitaine": ["16", "17", "19", "23", "24", "33", "40", "47", "64", "79", "86", "87"],
    "Occitanie": ["09", "11", "12", "30", "31", "32", "34", "46", "48", "65", "66", "81", "82"],
    "Pays de la Loire": ["44", "49", "53", "72", "85"],
    "Provence-Alpes-Côte d'Azur": ["04", "05", "06", "13", "83", "84"],
    "Collectivités d'outre-mer": ["975", "977", "978"],
    "Anciens territoires d'outre-mer": ["986", "987", "988"],
}


def get_department_to_region():
    department_to_region = {}
    for region, dpts in REGIONS.items():
        for dpt in dpts:
            department_to_region[dpt] = region
    return department_to_region


DEPARTMENT_TO_REGION = get_department_to_region()

DEPARTMENTS = {
    "01": "01 - Ain",
    "02": "02 - Aisne",
    "03": "03 - Allier",
    "04": "04 - Alpes-de-Haute-Provence",
    "05": "05 - Hautes-Alpes",
    "06": "06 - Alpes-Maritimes",
    "07": "07 - Ardèche",
    "08": "08 - Ardennes",
    "09": "09 - Ariège",
    "10": "10 - Aube",
    "11": "11 - Aude",
    "12": "12 - Aveyron",
    "13": "13 - Bouches-du-Rhône",
    "14": "14 - Calvados",
    "15": "15 - Cantal",
    "16": "16 - Charente",
    "17": "17 - Charente-Maritime",
    "18": "18 - Cher",
    "19": "19 - Corrèze",
    "2A": "2A - Corse-du-Sud",
    "2B": "2B - Haute-Corse",
    "21": "21 - Côte-d'Or",
    "22": "22 - Côtes-d'Armor",
    "23": "23 - Creuse",
    "24": "24 - Dordogne",
    "25": "25 - Doubs",
    "26": "26 - Drôme",
    "27": "27 - Eure",
    "28": "28 - Eure-et-Loir",
    "29": "29 - Finistère",
    "30": "30 - Gard",
    "31": "31 - Haute-Garonne",
    "32": "32 - Gers",
    "33": "33 - Gironde",
    "34": "34 - Hérault",
    "35": "35 - Ille-et-Vilaine",
    "36": "36 - Indre",
    "37": "37 - Indre-et-Loire",
    "38": "38 - Isère",
    "39": "39 - Jura",
    "40": "40 - Landes",
    "41": "41 - Loir-et-Cher",
    "42": "42 - Loire",
    "43": "43 - Haute-Loire",
    "44": "44 - Loire-Atlantique",
    "45": "45 - Loiret",
    "46": "46 - Lot",
    "47": "47 - Lot-et-Garonne",
    "48": "48 - Lozère",
    "49": "49 - Maine-et-Loire",
    "50": "50 - Manche",
    "51": "51 - Marne",
    "52": "52 - Haute-Marne",
    "53": "53 - Mayenne",
    "54": "54 - Meurthe-et-Moselle",
    "55": "55 - Meuse",
    "56": "56 - Morbihan",
    "57": "57 - Moselle",
    "58": "58 - Nièvre",
    "59": "59 - Nord",
    "60": "60 - Oise",
    "61": "61 - Orne",
    "62": "62 - Pas-de-Calais",
    "63": "63 - Puy-de-Dôme",
    "64": "64 - Pyrénées-Atlantiques",
    "65": "65 - Hautes-Pyrénées",
    "66": "66 - Pyrénées-Orientales",
    "67": "67 - Bas-Rhin",
    "68": "68 - Haut-Rhin",
    "69": "69 - Rhône",
    "70": "70 - Haute-Saône",
    "71": "71 - Saône-et-Loire",
    "72": "72 - Sarthe",
    "73": "73 - Savoie",
    "74": "74 - Haute-Savoie",
    "75": "75 - Paris",
    "76": "76 - Seine-Maritime",
    "77": "77 - Seine-et-Marne",
    "78": "78 - Yvelines",
    "79": "79 - Deux-Sèvres",
    "80": "80 - Somme",
    "81": "81 - Tarn",
    "82": "82 - Tarn-et-Garonne",
    "83": "83 - Var",
    "84": "84 - Vaucluse",
    "85": "85 - Vendée",
    "86": "86 - Vienne",
    "87": "87 - Haute-Vienne",
    "88": "88 - Vosges",
    "89": "89 - Yonne",
    "90": "90 - Territoire de Belfort",
    "91": "91 - Essonne",
    "92": "92 - Hauts-de-Seine",
    "93": "93 - Seine-Saint-Denis",
    "94": "94 - Val-de-Marne",
    "95": "95 - Val-d'Oise",
    "971": "971 - Guadeloupe",
    "972": "972 - Martinique",
    "973": "973 - Guyane",
    "974": "974 - La Réunion",
    "975": "975 - Saint-Pierre-et-Miquelon",
    "976": "976 - Mayotte",
    "977": "977 - Saint-Barthélémy",
    "978": "978 - Saint-Martin",
    "986": "986 - Wallis-et-Futuna",
    "987": "987 - Polynésie française",
    "988": "988 - Nouvelle-Calédonie",
}

# Marseille, Lyon and Paris
# The "max" value is the maximum postal code of the districts of the department
DEPARTMENTS_WITH_DISTRICTS = {
    "13": {"city": "Marseille", "max": 13016},
    "69": {"city": "Lyon", "max": 69009},
    "75": {"city": "Paris", "max": 75020},
}


def department_from_postcode(post_code):
    """
    Extract the department from the postal code (if possible)
    """
    department = ""
    if post_code:
        if post_code.startswith("20"):
            a_post_codes = ("200", "201", "207")
            b_post_codes = ("202", "204", "206")
            if post_code.startswith(a_post_codes):
                department = "2A"
            elif post_code.startswith(b_post_codes):
                department = "2B"
        elif post_code.startswith("97") or post_code.startswith("98"):
            department = post_code[:3]
        else:
            department = post_code[:2]

    return department


def format_district(post_code, department):
    # Could use ordinal from humanize but it would be overkill
    number = int(post_code) - (int(department) * 1000)
    return "1er" if number == 1 else f"{number}e"


def format_region_for_matomo(region):
    if not region:
        return "Region-inconnue"
    # E.g. `Provence-Alpes-Côte d&#x27;Azur` becomes `Provence-Alpes-Cote-d-Azur`.
    return re.sub("[^A-Za-z0-9-]+", "-", unidecode.unidecode(region))


def format_department_for_matomo(department):
    if not department or department not in DEPARTMENTS:
        return "Departement-inconnu"
    # E.g. `13 - Bouches-du-Rhône` becomes `13---Bouches-du-Rhone`.
    return re.sub("[^A-Za-z0-9-]+", "-", unidecode.unidecode(DEPARTMENTS[department]))


def format_region_and_department_for_matomo(department):
    formatted_department = format_department_for_matomo(department)
    region = DEPARTMENT_TO_REGION.get(department)
    formatted_region = format_region_for_matomo(region)
    # E.g. `Provence-Alpes-Cote-d-Azur/04---Alpes-de-Haute-Provence`
    return f"{formatted_region}/{formatted_department}"
