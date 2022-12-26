from django.utils.safestring import mark_safe

from itou.utils import constants as global_constants
from itou.utils.urls import get_external_link_markup


ERROR_CANNOT_OBTAIN_NEW_FOR_USER = mark_safe(
    "Vous avez terminé un parcours il y a moins de deux ans.<br>"
    "Pour prétendre à nouveau à un parcours en structure d'insertion "
    "par l'activité économique vous devez rencontrer un prescripteur "
    "habilité : Pôle emploi, Mission Locale, CAP Emploi, etc."
)

_doc_link = get_external_link_markup(
    url=f"{global_constants.ITOU_COMMUNITY_URL }/doc/emplois/derogation-au-delai-de-carence/",
    text="En savoir plus sur la dérogation du délai de carence",
)

ERROR_CANNOT_OBTAIN_NEW_FOR_PROXY = mark_safe(
    "Le candidat a terminé un parcours il y a moins de deux ans.<br>"
    "Pour prétendre à nouveau à un parcours en structure d'insertion "
    "par l'activité économique il doit rencontrer un prescripteur "
    "habilité : Pôle emploi, Mission Locale, CAP Emploi, etc."
    f"<br>{_doc_link}"  # Display doc link only for proxies.
)
