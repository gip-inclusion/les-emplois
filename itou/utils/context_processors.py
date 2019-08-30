# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.conf import settings


def get_current_organization(request):
    """
    Every RequestContext will contain these two variables:
        - current_siaes_views: an itou.siaes.Siae instance
        - current_prescriber: an itou.prescribers.Prescriber instance
    """

    siae = None
    prescriber = None

    if request.user.is_authenticated:

        siae_siret = request.session.get(settings.ITOU_SESSION_CURRENT_SIAE_KEY)
        if siae_siret:
            siae = request.user.siae_set.get(siret=siae_siret)

        prescriber_siret = request.session.get(
            settings.ITOU_SESSION_CURRENT_PRESCRIBER_KEY
        )
        if prescriber_siret:
            prescriber = request.user.prescriber_set.get(siret=prescriber_siret)

    return {"current_siae": siae, "current_prescriber": prescriber}
