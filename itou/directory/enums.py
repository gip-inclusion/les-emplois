from django.db import models


class ContactMethod(models.TextChoices):
    PHONE = "phone", "Téléphone"
    EMAIL = "email", "Courriel"
    FORM = "form", "Formulaire de contact"


class ContactSubject(models.TextChoices):
    SUPPORT = "support", "Demande d'information sur un accompagnement"
    SCHEME = "scheme", "Demande d'information sur un dispositif"
    ORIENTATION = "orientation", "Orientation d'une personne"
    COORDINATION = "coordination", "Coordination / suivi conjoint"
    ORIENTATION_FEEDBACK = "orientation_feedback", "Retour sur une orientation"
    PARTNERSHIP = "partnership", "Proposition de partenariat"
    MEETING = "meeting", "Proposition de rencontre"
    EVENT = "event", "Participation à un événement"
    PUBLIC_INTERVENTION = "public_intervention", "Intervention auprès de nos publics"
    OTHER = "other", "Autre (préciser)"
