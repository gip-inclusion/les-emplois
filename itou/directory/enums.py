from django.db import models


class ContactMethod(models.TextChoices):
    PHONE = "phone", "Téléphone"
    EMAIL = "email", "Courriel"
    FORM = "form", "Formulaire de contact"
