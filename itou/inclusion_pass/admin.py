from django.contrib import admin

from itou.inclusion_pass import models


for model in (
    models.Offreur,
    models.OffreurMembership,
    models.Accompagnement,
    models.Consentement,
    models.DonneePartagee,
    models.AccesDonnee,
    models.SituationSuivi,
    models.NotificationPrescripteur,
):
    admin.site.register(model)
