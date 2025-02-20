# Generated by Django 5.0.8 on 2024-09-06 09:38

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("eligibility", "0005_alter_administrativecriteria_created_by_and_more"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="administrativecriteria",
            name="certifiable",
        ),
        migrations.RemoveField(
            model_name="geiqadministrativecriteria",
            name="certifiable",
        ),
        migrations.AddField(
            model_name="administrativecriteria",
            name="kind",
            field=models.CharField(
                choices=[
                    ("RSA", "Bénéficiaire du RSA"),
                    ("AAH", "Allocation aux adultes handicapés"),
                    ("ASS", "Allocataire ASS"),
                    ("CAP_BEP", "Niveau d'étude 3 (CAP, BEP) ou infra"),
                    ("SENIOR", "Senior (+ de 50 ans)"),
                    ("JEUNE", "Jeune (- de 26 ans)"),
                    ("ASE", "Aide sociale à l'enfance"),
                    ("DELD", "Demandeur d'emploi de longue durée (12-24 mois)"),
                    ("DETLD", "Demandeur d'emploi de très longue durée (+24 mois)"),
                    ("TH", "Travailleur handicapé"),
                    ("PI", "Parent isolé"),
                    ("PSH_PR", "Personne sans hébergement ou hébergée ou ayant un parcours de rue"),
                    (
                        "REF_DA",
                        "Réfugié statutaire, bénéficiaire d'une protection temporaire, protégé subsidiaire ou "
                        "demandeur d'asile",
                    ),
                    ("ZRR", "Résident ZRR"),
                    ("QPV", "Résident QPV"),
                    ("DETENTION_MJ", "Sortant de détention ou personne placée sous main de justice"),
                    ("FLE", "Maîtrise de la langue française"),
                    ("PM", "Problème de mobilité"),
                    ("JEUNE_SQ", "Jeune de moins de 26 ans sans qualification (niveau 4 maximum)"),
                    ("MINIMA", "Bénéficiaire des minima sociaux"),
                    ("DELD_12", "Demandeur d'emploi inscrit depuis moins de 12 mois"),
                    ("DE_45", "Demandeur d’emploi de 45 ans et plus"),
                    ("RECONVERSION", "Personne en reconversion professionnelle contrainte"),
                    ("SIAE_CUI", "Personne bénéficiant ou sortant d’un dispositif d’insertion"),
                    ("RS_PS_DA", "Demandeur d'asile"),
                    ("AUTRE_MINIMA", "Autre minima social"),
                    ("FT", "Personne inscrite à France Travail"),
                    ("SANS_TRAVAIL_12", "Personne éloignée du marché du travail (> 1 an)"),
                ],
                default="",
                verbose_name="type",
            ),
        ),
        migrations.AddField(
            model_name="geiqadministrativecriteria",
            name="kind",
            field=models.CharField(
                choices=[
                    ("RSA", "Bénéficiaire du RSA"),
                    ("AAH", "Allocation aux adultes handicapés"),
                    ("ASS", "Allocataire ASS"),
                    ("CAP_BEP", "Niveau d'étude 3 (CAP, BEP) ou infra"),
                    ("SENIOR", "Senior (+ de 50 ans)"),
                    ("JEUNE", "Jeune (- de 26 ans)"),
                    ("ASE", "Aide sociale à l'enfance"),
                    ("DELD", "Demandeur d'emploi de longue durée (12-24 mois)"),
                    ("DETLD", "Demandeur d'emploi de très longue durée (+24 mois)"),
                    ("TH", "Travailleur handicapé"),
                    ("PI", "Parent isolé"),
                    ("PSH_PR", "Personne sans hébergement ou hébergée ou ayant un parcours de rue"),
                    (
                        "REF_DA",
                        "Réfugié statutaire, bénéficiaire d'une protection temporaire, protégé subsidiaire ou "
                        "demandeur d'asile",
                    ),
                    ("ZRR", "Résident ZRR"),
                    ("QPV", "Résident QPV"),
                    ("DETENTION_MJ", "Sortant de détention ou personne placée sous main de justice"),
                    ("FLE", "Maîtrise de la langue française"),
                    ("PM", "Problème de mobilité"),
                    ("JEUNE_SQ", "Jeune de moins de 26 ans sans qualification (niveau 4 maximum)"),
                    ("MINIMA", "Bénéficiaire des minima sociaux"),
                    ("DELD_12", "Demandeur d'emploi inscrit depuis moins de 12 mois"),
                    ("DE_45", "Demandeur d’emploi de 45 ans et plus"),
                    ("RECONVERSION", "Personne en reconversion professionnelle contrainte"),
                    ("SIAE_CUI", "Personne bénéficiant ou sortant d’un dispositif d’insertion"),
                    ("RS_PS_DA", "Demandeur d'asile"),
                    ("AUTRE_MINIMA", "Autre minima social"),
                    ("FT", "Personne inscrite à France Travail"),
                    ("SANS_TRAVAIL_12", "Personne éloignée du marché du travail (> 1 an)"),
                ],
                default="",
                verbose_name="type",
            ),
        ),
    ]
