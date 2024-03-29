from django.conf import settings
from django.db import models

from itou.approvals.models import Suspension
from itou.companies.models import Company
from itou.job_applications.models import JobApplication


class Customer(models.Model):
    company = models.OneToOneField(
        Company,
        on_delete=models.CASCADE,
        related_name="premium_customer",
        verbose_name="entreprise",
    )
    end_subscription_date = models.DateField(verbose_name="date de fin d'abonnement")
    last_synced_at = models.DateTimeField(verbose_name="dernière synchronisation")

    class Meta:
        verbose_name = "client"
        verbose_name_plural = "clients"

    def __str__(self):
        return self.company.name


class SyncedJobApplication(models.Model):
    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name="synced_job_applications",
        verbose_name="client",
    )
    job_application = models.OneToOneField(
        JobApplication,
        on_delete=models.CASCADE,
        related_name="synced_job_application",
        verbose_name="candidature",
    )
    last_in_progress_suspension = models.ForeignKey(
        Suspension,
        on_delete=models.SET_NULL,
        related_name="synced_job_applications",
        verbose_name="dernière suspension en cours",
        null=True,
        blank=True,
    )
    beneficiaire_du_rsa = models.BooleanField(default=False, verbose_name="bénéficiaire du RSA")
    allocataire_ass = models.BooleanField(default=False, verbose_name="allocataire ASS")
    allocataire_aah = models.BooleanField(default=False, verbose_name="allocataire AAH")
    detld_24_mois = models.BooleanField(default=False, verbose_name="detld (+ 24 mois)")
    niveau_detude_3 = models.BooleanField(default=False, verbose_name="niveau d'étude 3 (CAP, BEP) ou infra")
    senior_50_ans = models.BooleanField(default=False, verbose_name="senior (+50 ans)")
    jeune_26_ans = models.BooleanField(default=False, verbose_name="jeune (-26 ans)")
    sortant_de_lase = models.BooleanField(default=False, verbose_name="sortant de l'ASE")
    deld_12_24_mois = models.BooleanField(default=False, verbose_name="detld (12-24 mois)")
    travailleur_handicape = models.BooleanField(default=False, verbose_name="travailleur handicapé")
    parent_isole = models.BooleanField(default=False, verbose_name="parent isolé")
    personne_sans_hebergement = models.BooleanField(
        default=False, verbose_name="personne sans hébergement ou hébergée ou ayant un parcours de rue"
    )
    refugie_statutaire = models.BooleanField(
        default=False,
        verbose_name="réfugié statutaire, bénéficiaire d'une protection temporaire,"
        " protégé subsidiaire ou demandeur d'asile",
    )
    resident_zrr = models.BooleanField(default=False, verbose_name="résident ZRR")
    resident_qpv = models.BooleanField(default=False, verbose_name="résident QPV")
    sortant_de_detention = models.BooleanField(
        default=False, verbose_name="sortant de détention ou personne placée sous main de justice"
    )
    maitrise_de_la_langue_francaise = models.BooleanField(
        default=False, verbose_name="maîtrise de la langue française"
    )
    mobilite = models.BooleanField(default=False, verbose_name="mobilité")

    class Meta:
        verbose_name = "candidature synchronisée"
        verbose_name_plural = "candidatures synchronisées"

    def __str__(self):
        return str(self.job_application.pk)


class Note(models.Model):
    synced_job_application = models.OneToOneField(
        SyncedJobApplication,
        on_delete=models.CASCADE,
        related_name="notes",
        verbose_name="synced_job_application",
    )
    content = models.TextField(default=None, blank=True, null=True, verbose_name="content")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="date de création")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="date de modification")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="créé par",
        on_delete=models.SET_NULL,
        related_name="job_seeker_informations_created_by",
        null=True,
        blank=True,
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="modifié par",
        on_delete=models.SET_NULL,
        related_name="job_seeker_informations_updated_by",
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "note sur la candidature"
        verbose_name_plural = "notes sur les candidatures"
