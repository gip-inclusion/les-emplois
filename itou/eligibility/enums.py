from django.db import models

from itou.users.enums import KIND_EMPLOYER, KIND_PRESCRIBER


class AdministrativeCriteriaAnnex(models.TextChoices):
    NO_ANNEX = "0", "Aucune annexe associée"
    ANNEX_1 = "1", "Annexe 1"
    ANNEX_2 = "2", "Annexe 2"
    BOTH_ANNEXES = "1+2", "Annexes 1 et 2"


class AdministrativeCriteriaLevel(models.TextChoices):
    LEVEL_1 = "1", "Niveau 1"
    LEVEL_2 = "2", "Niveau 2"


class AdministrativeCriteriaLevelPrefix(models.TextChoices):
    LEVEL_1_PREFIX = "level_1_"
    LEVEL_2_PREFIX = "level_2_"


class AuthorKind(models.TextChoices):
    PRESCRIBER = KIND_PRESCRIBER, "Prescripteur habilité"
    EMPLOYER = KIND_EMPLOYER, "Employeur"
    GEIQ = "geiq", "GEIQ"


class AdministrativeCriteriaKind(models.TextChoices):
    # IAE / GEIQ
    RSA = "RSA", "Bénéficiaire du RSA"
    AAH = "AAH", "Allocation aux adultes handicapés"
    ASS = "ASS", "Allocataire ASS"
    CAP_BEP = "CAP_BEP", "Niveau d'étude 3 (CAP, BEP) ou infra"
    SENIOR = "SENIOR", "Senior (+ de 50 ans)"
    JEUNE = "JEUNE", "Jeune (- de 26 ans)"
    ASE = "ASE", "Aide sociale à l'enfance"
    DELD = "DELD", "Demandeur d'emploi de longue durée (12-24 mois)"
    DETLD = "DETLD", "Demandeur d'emploi de très longue durée (+24 mois)"
    TH = "TH", "Travailleur handicapé"
    PI = "PI", "Parent isolé"
    PSH_PR = "PSH_PR", "Personne sans hébergement ou hébergée ou ayant un parcours de rue"
    REF_DA = (
        "REF_DA",
        "Réfugié statutaire, bénéficiaire d'une protection temporaire, protégé subsidiaire ou demandeur d'asile",
    )
    ZRR = "ZRR", "Résident ZRR"
    QPV = "QPV", "Résident QPV"
    DETENTION_MJ = "DETENTION_MJ", "Sortant de détention ou personne placée sous main de justice"
    FLE = "FLE", "Maîtrise de la langue française"
    PM = "PM", "Problème de mobilité"

    # GEIQ only
    JEUNE_SQ = "JEUNE_SQ", "Jeune de moins de 26 ans sans qualification (niveau 4 maximum)"
    MINIMA = "MINIMA", "Bénéficiaire des minima sociaux"
    DELD_12 = "DELD_12", "Demandeur d'emploi inscrit depuis moins de 12 mois"
    DE_45 = "DE_45", "Demandeur d’emploi de 45 ans et plus"
    RECONVERSION = "RECONVERSION", "Personne en reconversion professionnelle contrainte"
    SIAE_CUI = "SIAE_CUI", "Personne bénéficiant ou sortant d’un dispositif d’insertion"
    RS_PS_DA = "RS_PS_DA", "Demandeur d'asile"
    AUTRE_MINIMA = "AUTRE_MINIMA", "Autre minima social"
    FT = "FT", "Personne inscrite à France Travail"
    SANS_TRAVAIL_12 = "SANS_TRAVAIL_12", "Personne éloignée du marché du travail (> 1 an)"
