import uuid

from django.db import models


class AnonymizedJobSeeker(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # from User model
    date_joined = models.DateField(verbose_name="année et mois d'inscription")
    first_login = models.DateField(verbose_name="année et mois de première connexion", blank=True, null=True)
    last_login = models.DateField(verbose_name="année et mois de dernière connexion", blank=True, null=True)
    anonymized_at = models.DateTimeField(auto_now_add=True, verbose_name="archivé le")
    user_signup_kind = models.CharField(
        max_length=50, verbose_name="créé par un utilisateur de type", blank=True, null=True
    )
    department = models.CharField(max_length=3, verbose_name="département", blank=True, null=True)
    title = models.CharField(
        max_length=3,
        verbose_name="civilité",
        blank=True,
        null=True,
    )
    identity_provider = models.CharField(max_length=20, verbose_name="fournisseur d'identité (SSO)")

    # from JobSeekerProfile model
    had_pole_emploi_id = models.BooleanField(verbose_name="ID Pôle emploi", default=False)
    had_nir = models.BooleanField(verbose_name="NIR", default=False)
    lack_of_nir_reason = models.CharField(verbose_name="raison de l'absence de NIR", blank=True, null=True)
    nir_sex = models.PositiveSmallIntegerField(verbose_name="sexe du NIR", blank=True, null=True)
    nir_year = models.PositiveSmallIntegerField(verbose_name="année du NIR", blank=True, null=True)
    birth_year = models.PositiveSmallIntegerField(verbose_name="année de naissance", blank=True, null=True)
    count_accepted_applications = models.PositiveIntegerField(
        verbose_name="nombre de candidatures acceptées", default=0
    )
    count_IAE_applications = models.PositiveIntegerField(verbose_name="nombre de candidatures dans l'IAE", default=0)
    count_total_applications = models.PositiveIntegerField(verbose_name="nombre de candidatures totales", default=0)

    class Meta:
        verbose_name = "candidat archivé"
        verbose_name_plural = "candidats archivés"
        ordering = ["-anonymized_at"]


class AnonymizedApplication(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # job_seeker
    job_seeker_birth_year = models.PositiveSmallIntegerField(
        verbose_name="année de naissance du candidat", blank=True, null=True
    )
    job_seeker_department_same_as_company_department = models.BooleanField(
        verbose_name="le candidat a le même département que celui l'entreprise", default=False
    )

    # sender
    sender_kind = models.CharField(verbose_name="type de l'émetteur")
    sender_company_kind = models.CharField(verbose_name="type de l'entreprise émettrice", blank=True, null=True)
    sender_prescriber_organization_kind = models.CharField(
        verbose_name="type de l'organisation prescriptrice de l'émetteur", blank=True, null=True
    )
    sender_prescriber_organization_authorization_status = models.CharField(
        verbose_name="état de l'habilitation de l'organisme prescripteur de l'émetteur", blank=True, null=True
    )

    # company
    company_kind = models.CharField(verbose_name="type d'entreprise")
    company_department = models.CharField(verbose_name="département de l'entreprise")
    company_naf = models.CharField(verbose_name="code NAF de l'entreprise")
    company_has_convention = models.BooleanField(verbose_name="l'entreprise a une convention", default=False)

    # application
    anonymized_at = models.DateTimeField(auto_now_add=True, verbose_name="archivé le")
    applied_at = models.DateField(verbose_name="année et mois de la candidature")
    processed_at = models.DateField(verbose_name="année et mois de traitement", blank=True, null=True)
    last_transition_at = models.DateField(
        verbose_name="année et mois de la dernière transition", blank=True, null=True
    )
    had_resume = models.BooleanField(verbose_name="candidature avec un CV", default=False)
    origin = models.CharField(verbose_name="origine de la candidature")
    state = models.CharField(verbose_name="état de la candidature")
    refusal_reason = models.CharField(verbose_name="raison du refus", blank=True, null=True)
    has_been_transferred = models.BooleanField(verbose_name="a été transférée", default=False)
    number_of_jobs_applied_for = models.PositiveIntegerField(
        verbose_name="nombre d'offres d'emploi pour lesquelles le candidat a postulé", default=0
    )
    has_diagoriente_invitation = models.BooleanField(
        verbose_name="a reçu une invitation à un diagnostic d'orientation", default=False
    )

    # hiring
    hiring_rome = models.CharField(verbose_name="code ROME de l'embauche", blank=True, null=True)
    hiring_contract_type = models.CharField(verbose_name="type de contrat de l'embauche", blank=True, null=True)
    hiring_contract_nature = models.CharField(verbose_name="nature du contrat de l'embauche", blank=True, null=True)
    hiring_start_date = models.DateField(verbose_name="année et mois de début de l'embauche", blank=True, null=True)
    hiring_without_approval = models.BooleanField(verbose_name="embauche sans PASS IAE", default=False)

    class Meta:
        verbose_name = "candidature archivée"
        verbose_name_plural = "candidatures archivées"
        ordering = ["-anonymized_at"]
