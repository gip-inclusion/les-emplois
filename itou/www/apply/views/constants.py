from django.utils.safestring import mark_safe

from itou.utils import constants as global_constants
from itou.utils.urls import get_external_link_markup


ERROR_CANNOT_OBTAIN_NEW_FOR_USER = mark_safe(
    "Vous avez terminé un parcours il y a moins de deux ans.<br>"
    "Pour prétendre à nouveau à un parcours en structure d'insertion "
    "par l'activité économique vous devez rencontrer un prescripteur "
    "habilité : France Travail, Mission Locale, Cap emploi, etc."
)

_doc_link = get_external_link_markup(
    url=(
        f"{global_constants.ITOU_HELP_CENTER_URL }/articles/"
        "14733589920913--Dérogation-au-délai-de-carence-d-un-parcours-IAE"
    ),
    text="En savoir plus sur la dérogation du délai de carence",
)

ERROR_CANNOT_OBTAIN_NEW_FOR_PROXY = mark_safe(
    "Le candidat a terminé un parcours il y a moins de deux ans.<br>"
    "Pour prétendre à nouveau à un parcours en structure d'insertion "
    "par l'activité économique il doit rencontrer un prescripteur "
    "habilité : France Travail, Mission Locale, Cap emploi, etc."
    f"<br>{_doc_link}"  # Display doc link only for proxies.
)
