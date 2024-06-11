from django.db import models


class ReviewState(models.TextChoices):
    ACCEPTED = "ACCEPTED", "La totalité de l’aide conventionnée est accordée"
    PARTIAL_ACCEPTED = "PARTIAL_ACCEPTED", "Le solde de l’aide est partiellement accordé"
    REMAINDER_REFUSED = "REMAINDER_REFUSED", "Le solde de l’aide est refusé"
    PARTIAL_REFUND = (
        "PARTIAL_REFUND",
        "Le solde de l’aide est refusé et une demande de remboursement partiel sera demandée",
    )
    FULL_REFUND = (
        "FULL_REFUND",
        "Le solde de l’aide est refusé et une demande de remboursement total sera demandée",
    )
