from itou.utils.apis.geocoding import get_geocoding_data, detailed_geocoding_data
import unicodedata
import Enum

from itou.siaes.models import Siae
from itou.prescribers.models import PrescriberOrganization
from itou.users.models import User


class LaneType(Enum):
    AER = "Aérodrome"
    AGL = "Agglomération"
    AIRE = "Aire"
    ALL = "Allée"
    ACH = "Ancien chemin"
    ART = "Ancienne route"
    AV = "Avenue"
    BEGI = "Beguinage"
    BD = "Boulevard"
    BRG = "Bourg"
    CPG = "Camping"
    CAR = "Carrefour"
    CTRE = "Centre"
    CCAL = "Centre commercial"
    CHT = "Chateau"
    CHS = "Chaussee"
    CHEM = "Chemin"
    CHV = "Chemin vicinal"
    CITE = "Cité"
    CLOS = "Clos"
    CTR = "Contour"
    COR = "Corniche"
    COTE = "Coteaux"
    COUR = "Cour"
    CRS = "Cours"
    DSC = "Descente"
    DOM = "Domaine"
    ECL = "Ecluse"
    ESC = "Escalier"
    ESPA = "Espace"
    ESP = "Esplanade"
    FG = "Faubourg"
    FRM = "Ferme"
    FON = "Fontaine"
    GAL = "Galerie"
    GARE = "Gare"
    GBD = "Grand boulevard"
    GPL = "Grande place"
    GR = "Grande rue"
    GRI = "Grille"
    HAM = "Hameau"
    IMM = "Immeuble(s)"
    IMP = "Impasse"
    JARD = "Jardin"
    LD = "Lieu-dit"
    LOT = "Lotissement"
    MAIL = "Mail"
    MAIS = "Maison"
    MAS = "Mas"
    MTE = "Montee"
    PARC = "Parc"
    PRV = "Parvis"
    PAS = "Passage"
    PLE = "Passerelle"
    PCH = "Petit chemin"
    PRT = "Petite route"
    PTR = "Petite rue"
    PL = "Place"
    PTTE = "Placette"
    PLN = "Plaine"
    PLAN = "Plan"
    PLT = "Plateau"
    PONT = "Pont"
    PORT = "Port"
    PROM = "Promenade"
    QUAI = "Quai"
    QUAR = "Quartier"
    RPE = "Rampe"
    REMP = "Rempart"
    RES = "Residence"
    ROC = "Rocade"
    RPT = "Rond-point"
    RTD = "Rotonde"
    RTE = "Route"
    RUE = "Rue"
    RLE = "Ruelle"
    SEN = "Sente"
    SENT = "Sentier"
    SQ = "Square"
    TPL = "Terre plein"
    TRAV = "Traverse"
    VEN = "Venelle"
    VTE = "Vieille route"
    VCHE = "Vieux chemin"
    VILL = "Villa"
    VLGE = "Village"
    VOIE = "Voie"
    ZONE = "Zone"
    ZA = "Zone d'activite"
    ZAC = "Zone d'amenagement concerte"
    ZAD = "Zone d'amenagement differe"
    ZI = "Zone industrielle"
    ZUP = "Zone urbanisation prio"


def strip_accents(s):
    nfkd_form = unicodedata.normalize("NFKD", s)
    return "".join([c for c in nfkd_form if not unicodedata.combining(c)])


class ASPFormatAddress:
    """
    ASP formatted address

    ASP expects an address to have the following fields:
    - number
    - number extension (Bis, Ter ...)
    - type (street, avenue, road ...)
    - address complement (optionnal)
    - a postal code and the matching INSEE commune code
    - department code
    - city name
    - country INSEE code and country group (within EU or not, and France itself)
    """

    # These are the extensions defined in ASP ref file: ref_extension_voie_v1.csv
    street_extensions = {"bis": "B", "ter": "T", "quater": "Q", "quinqies": "C"}
    revert = {strip_accents(lt.value.lower()): lt.name for lt in LaneType}
    lane_type_keys = [k.name.lower() for k in LaneType]

    # Sometimes the geo API does not give a correct lane type
    # Here are some common aliases
    lane_type_aliases = {
        "r": LaneType.RUE,
        "che": LaneType.CHEM,
        "grand rue": LaneType.RUE,
        "grande rue": LaneType.RUE,
        "grand'rue": LaneType.RUE,
        "qu": LaneType.QUAI,
        "voies": LaneType.VOIE,
    }

    @classmethod
    def from_address(cls, obj, update_coords=False):
        if type(obj) not in [Siae, PrescriberOrganization, User]:
            return None, "This type has no address"

        # Do we have enough data to make an extraction?
        if not obj.post_code or not obj.address_line_1:
            return None, "Incomplete address data"

        print(f"FMT: {obj.address_line_1}, {obj.post_code}")

        # first we use geo API to get a 'lane' and a number
        address = get_geocoding_data(obj.address_line_1, post_code=obj.post_code, fmt=detailed_geocoding_data)
        if not address:
            return None, "Geocoding error, unable to get result"

        result = {}

        # Get street extension (bis, ter ...)
        # It's included in the resulting streetnumber geo API field
        number_plus_ext = address.get("number")
        if number_plus_ext:
            number, *extension = number_plus_ext.split()

            if number:
                result["number"] = number

            if extension:
                extension = extension[0]
                if extension.lower() not in cls.street_extensions.keys():
                    result["non_std_extension"] = extension
                    # return None, f"Unknown lane extension: {extension}"
                else:
                    result["std_extension"] = cls.street_extensions.get(extension)

        lane = None
        if not address.get("lane") and not address.get("address"):
            print(address)
            return None, "Unable to get address lane"
        else:
            lane = address.get("lane") or address.get("address")
            lane = strip_accents(lane)
            result["lane"] = lane

        # Lane type processing
        lane_type = lane.split(maxsplit=1)[0]
        lane_type = lane_type.lower()

        if cls.revert.get(lane_type):
            result["lane_type"] = cls.revert.get(lane_type)
        elif cls.lane_type_aliases.get(lane_type):
            result["lane_type"] = cls.lane_type_aliases.get(lane_type).name
        elif lane_type in cls.lane_type_keys:
            result["lane_type"] = lane_type.upper()
        else:
            return None, f"Can't find lane type: {lane_type}"

        # INSEE code:
        # must double check with ASP ref file
        result["insee_code"] = address.get("insee_code")
        # TODO check with ASP data

        if update_coords and address.get("coords", None) and address.get("score", -1) > obj.get("geocoding_score", 0):
            # User, Siae and PrescribersOrganisation all have score and coords
            obj.coords = address["coords"]
            obj.geocoding_score = address["score"]
            obj.save()

        return result, None
