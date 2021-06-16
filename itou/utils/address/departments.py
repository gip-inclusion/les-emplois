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
    "01": "Ain (01)",
    "02": "Aisne (02)",
    "03": "Allier (03)",
    "04": "Alpes-de-Haute-Provence (04)",
    "05": "Hautes-Alpes (05)",
    "06": "Alpes-Maritimes (06)",
    "07": "Ardèche (07)",
    "08": "Ardennes (08)",
    "09": "Ariège (09)",
    "10": "Aube (10)",
    "11": "Aude (11)",
    "12": "Aveyron (12)",
    "13": "Bouches-du-Rhône (13)",
    "14": "Calvados (14)",
    "15": "Cantal (15)",
    "16": "Charente (16)",
    "17": "Charente-Maritime (17)",
    "18": "Cher (18)",
    "19": "Corrèze (19)",
    "2A": "Corse-du-Sud (2A)",
    "2B": "Haute-Corse (2B)",
    "21": "Côte-d'Or (21)",
    "22": "Côtes-d'Armor (22)",
    "23": "Creuse (23)",
    "24": "Dordogne (24)",
    "25": "Doubs (25)",
    "26": "Drôme (26)",
    "27": "Eure (27)",
    "28": "Eure-et-Loir (28)",
    "29": "Finistère (29)",
    "30": "Gard (30)",
    "31": "Haute-Garonne (31)",
    "32": "Gers (32)",
    "33": "Gironde (33)",
    "34": "Hérault (34)",
    "35": "Ille-et-Vilaine (35)",
    "36": "Indre (36)",
    "37": "Indre-et-Loire (37)",
    "38": "Isère (38)",
    "39": "Jura (39)",
    "40": "Landes (40)",
    "41": "Loir-et-Cher (41)",
    "42": "Loire (42)",
    "43": "Haute-Loire (43)",
    "44": "Loire-Atlantique (44)",
    "45": "Loiret (45)",
    "46": "Lot (46)",
    "47": "Lot-et-Garonne (47)",
    "48": "Lozère (48)",
    "49": "Maine-et-Loire (49)",
    "50": "Manche (50)",
    "51": "Marne (51)",
    "52": "Haute-Marne (52)",
    "53": "Mayenne (53)",
    "54": "Meurthe-et-Moselle (54)",
    "55": "Meuse (55)",
    "56": "Morbihan (56)",
    "57": "Moselle (57)",
    "58": "Nièvre (58)",
    "59": "Nord (59)",
    "60": "Oise (60)",
    "61": "Orne (61)",
    "62": "Pas-de-Calais (62)",
    "63": "Puy-de-Dôme (63)",
    "64": "Pyrénées-Atlantiques (64)",
    "65": "Hautes-Pyrénées (65)",
    "66": "Pyrénées-Orientales (66)",
    "67": "Bas-Rhin (67)",
    "68": "Haut-Rhin (68)",
    "69": "Rhône (69)",
    "70": "Haute-Saône (70)",
    "71": "Saône-et-Loire (71)",
    "72": "Sarthe (72)",
    "73": "Savoie (73)",
    "74": "Haute-Savoie (74)",
    "75": "Paris (75)",
    "76": "Seine-Maritime (76)",
    "77": "Seine-et-Marne (77)",
    "78": "Yvelines (78)",
    "79": "Deux-Sèvres (79)",
    "80": "Somme (80)",
    "81": "Tarn (81)",
    "82": "Tarn-et-Garonne (82)",
    "83": "Var (83)",
    "84": "Vaucluse (84)",
    "85": "Vendée (85)",
    "86": "Vienne (86)",
    "87": "Haute-Vienne (87)",
    "88": "Vosges (88)",
    "89": "Yonne (89)",
    "90": "Territoire de Belfort (90)",
    "91": "Essonne (91)",
    "92": "Hauts-de-Seine (92)",
    "93": "Seine-Saint-Denis (93)",
    "94": "Val-de-Marne (94)",
    "95": "Val-d'Oise (95)",
    "971": "Guadeloupe (971)",
    "972": "Martinique (972)",
    "973": "Guyane (973)",
    "974": "La Réunion (974)",
    "975": "Saint-Pierre-et-Miquelon (975)",
    "976": "Mayotte (976)",
    "977": "Saint-Barthélémy (977)",
    "978": "Saint-Martin (978)",
    "986": "Wallis-et-Futuna (986)",
    "987": "Polynésie française (987)",
    "988": "Nouvelle-Calédonie (988)",
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
