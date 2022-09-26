# These fake SIRET and financial annex numbers must be used when sending
# employee record batches to ASP.
# No other SIRET or annex number will be accepted by ASP test platform.
# Fields:
# SIRET, SIAE name, Primary financial annex, antenna annex
# ---
# 78360196601442 ITOUUN      ACI087207431A0M0  AI087207432A0M0
# 33055039301440 ITOUDEUX    AI59L209512A0M0   EI59L209512A0M0
# 42366587601449 ITOUTROIS   EI033207523A0M0   ETTI033208541A0M0
# 77562703701448 ITOUQUATRE  ETTI087203159A0M0 AI087207461A0M0
# 80472537201448 ITOUCINQ    ACI59L207462A0M0  EI59L208541A0M0
# 21590350101445 ITOUSIX     ACI033207853A0M0  EI033208436A0M0
# 41173709101444 ITOUSEPT    EI087209478A0M0   ACI087201248A0M0
# 83533318801446 ITOUHUIT    ETTI59L201836A0M0 AI59L208471A0M0
# 50829034301441 ITOUNEUF    ACI033203185A0M0  EI033206315A0M0
# 80847781401440 ITOUDIX     AI087202486A0M0   ACI087203187A0M0
# ---
# Update as needed during ASP tests sessions


# ASP ID -> TEST SIRET + data
ASP_ID_TO_SIRET_MAPPING = {
    2719: {"siret": "33055039301440", "mesure": "EI_DC", "numeroAnnexe": "ACI023201111A0M0"},
    1343: {"siret": "83533318801446", "mesure": "ETTI_DC", "numeroAnnexe": "ETTI59L201836A0M0"},
    2062: {"siret": "21590350101445", "mesure": "ACI_DC", "numeroAnnexe": "ACI033207853A0M0"},
    1516: {"siret": "33055039301440", "mesure": "EI_DC", "numeroAnnexe": "ACI023201111A0M0"},
    1060: {"siret": "33055039301440", "mesure": "AI_DC", "numeroAnnexe": "AI59L209512A0M0"},
    3411: {"siret": "83533318801446", "mesure": "EITI_DC", "numeroAnnexe": ""},
}


def asp_to_siret_from_fixtures(asp_id):
    assert (
        asp_id in ASP_ID_TO_SIRET_MAPPING.keys()
    ), f"No such test ASP_ID entry: {asp_id}. Check SIRET number mapping for ASP test platform."

    return ASP_ID_TO_SIRET_MAPPING[asp_id]
