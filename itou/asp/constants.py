# For some birth places (in Nouvelle-Calédonie, Polynésie, etc.), ASP
# expects us to send the INSEE code of the commune in the country
# field (instead of the code for "France"). This is the full list of
# these communes, extracted with:
#
#   dict(
#       Country.objects
#       .filter(group=Country.Group.FRANCE)
#       .exclude(name="FRANCE")
#       .order_by("name")
#       .values_list("name", "code")
#   )
#
# ... with the following adaptations:
# [1] Some countries have a dash in their name (e.g. "FATU-HIVA")
#     while the corresponding communes do not ("FATU HIVA").
#
# WARNING: if you update `ASP_COMMUNES_AS_COUNTRIES`, you must run
# `pytest tests/asp/test_utils.py --runslow` to check consistency.
#
ASP_COMMUNES_AS_COUNTRIES = {
    "ALO": "611",
    "ANAA": "711",
    "ARCHIPEL DES CROZET": "413",
    "ARCHIPEL DES KERGUELEN": "412",
    "ARUE": "712",
    "ARUTUA": "713",
    "BELEP": "801",
    "BORA BORA": "714",  # [1]
    "BOULOUPARI": "802",
    "BOURAIL": "803",
    "CANALA": "804",
    "DUMBEA": "805",
    "FAAA": "715",
    "FAKARAVA": "716",
    "FANGATAU": "717",
    "FARINO": "806",
    "FATU HIVA": "718",  # [1]
    "GAMBIER": "719",
    "HAO": "720",
    "HIENGHENE": "807",
    "HIKUERU": "721",
    "HITIAA O TE RA": "722",
    "HIVA OA": "723",  # [1]
    "HOUAILOU": "808",
    "HUAHINE": "724",
    "ILE DE CLIPPERTON": "901",
    "ILE-DES-PINS (L')": "809",
    "ILES EPARSES DE L'OCEAN INDIEN": "415",
    "ILES SAINT-PAUL ET NOUVELLE-AMSTERDAM": "411",
    "KAALA GOMEN": "810",  # [1]
    "KONE": "811",
    "KOUAOUA": "833",
    "KOUMAC": "812",
    "LA FOA": "813",
    "LA TERRE-ADELIE": "414",
    "LIFOU": "814",
    "MAHINA": "725",
    "MAKEMO": "726",
    "MANIHI": "727",
    "MARE": "815",
    "MAUPITI": "728",
    "MOINDOU": "816",
    "MONT DORE": "817",  # [1]
    "MOOREA MAIAO": "729",  # [1]
    "NAPUKA": "730",
    "NOUMEA": "818",
    "NUKU HIVA": "731",  # [1]
    "NUKUTAVAKE": "732",
    "OUEGOA": "819",
    "OUVEA": "820",
    "PAEA": "733",
    "PAITA": "821",
    "PAPARA": "734",
    "PAPEETE": "735",
    "PIRAE": "736",
    "POINDIMIE": "822",
    "PONERIHOUEN": "823",
    "POUEBO": "824",
    "POUEMBOUT": "825",
    "POUM": "826",
    "POYA": "827",
    "PUKAPUKA": "737",
    "PUNAAUIA": "738",
    "RAIVAVAE": "739",
    "RANGIROA": "740",
    "RAPA": "741",
    "REAO": "742",
    "RIMATARA": "743",
    "RURUTU": "744",
    "SARRAMEA": "828",
    "SIGAVE": "612",
    "TAHAA": "745",
    "TAHUATA": "746",
    "TAIARAPU EST": "747",  # [1]
    "TAIARAPU OUEST": "748",  # [1]
    "TAKAROA": "749",
    "TAPUTAPUATEA": "750",
    "TATAKOTO": "751",
    "TEVA I UTA": "752",
    "THIO": "829",
    "TOUHO": "830",
    "TUBUAI": "753",
    "TUMARAA": "754",
    "TUREIA": "755",
    "UA HUKA": "756",  # [1]
    "UA POU": "757",  # [1]
    "UTUROA": "758",
    "UVEA": "613",
    "VOH": "831",
    "YATE": "832",
}

# Some communes have changed their INSEE code and our code uses the INSEE code to deduce the
# department: prefer the more recent codes that match their department.
IGNORED_COMMUNES_TARGET_CODES = {
    ("97520", "POINTE-A-PITRE"): "97120",
    ("97811", "SAINT-DENIS"): "97411",
    ("97816", "SAINT-PIERRE"): "97416",
    # 97824 seems unknown to INSEE
    ("97824", "CILAOS"): "97424",
    # Mayotte's communes changed from 985xx INSEE codes to 976xx INSEE codes
    ("98501", "ACOUA"): "97601",
    ("98502", "BANDRABOUA"): "97602",
    ("98503", "BANDRELE"): "97603",
    ("98504", "BOUENI"): "97604",
    ("98505", "CHICONI"): "97605",
    ("98506", "CHIRONGUI"): "97606",
    ("98507", "DEMBENI"): "97607",
    ("98508", "DZAOUDZI"): "97608",
    ("98509", "KANI KELI"): "97609",  # Renamed as KANI-KELI
    ("98510", "KOUNGOU"): "97610",
    ("98511", "MAMOUDZOU"): "97611",
    ("98512", "MTSAMBORO"): "97612",
    ("98513", "MTSANGAMOUJI"): None,  # New INSEE code is 97613 but it doesn't seem to exist in ASP
    ("98514", "OUANGANI"): None,  # New INSEE code is 97614 but it doesn't seem to exist in ASP
    ("98515", "PAMANDZI"): "97615",
    ("98516", "SADA"): "97616",
    ("98517", "TSINGONI"): "97617",
    # For Wallis et Futuna, users should choose one of the 3 customary kingdoms (Uvea, Alo & Sigave)
    ("98600", "WALLIS ET FUTUNA"): None,
    ("98609", "WALLIS ET FUTUNA"): None,
    ("98701", "ST PIERRE ET MIQUELON"): None,  # Users should choose St Pierre (97502) or Miquelon-Langlade (97501)
    ("98402", "ARCHIPEL DES COMORES"): None,  # User should use the country COMORES or one of Mayotte's communes
}
