from django.db import models


class NotebookOrderKind(models.TextChoices):
    DISCOVERY = "2 - Commande decouverte"
    HIGH_PRIORITY = "3 - Commande dpt prio"
    QUOTATION_REQUEST = "4 - Demande de devis"
    DIAG_KO = "5 - Diag ko"
