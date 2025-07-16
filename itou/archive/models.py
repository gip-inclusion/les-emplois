import uuid

from django.db import models


class AnonymizedProfessional(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # from User model
    date_joined = models.DateField(verbose_name="année et mois d'inscription")
    first_login = models.DateField(verbose_name="année et mois de première connexion", blank=True, null=True)
    last_login = models.DateField(verbose_name="année et mois de dernière connexion", blank=True, null=True)
    anonymized_at = models.DateTimeField(auto_now_add=True, verbose_name="anonymisé le")
    department = models.CharField(max_length=3, verbose_name="département", blank=True, null=True)
    title = models.CharField(
        max_length=3,
        verbose_name="civilité",
        blank=True,
        null=True,
    )
    kind = models.CharField(max_length=50, verbose_name="type de professionnel", blank=True, null=True)
    number_of_memberships = models.PositiveIntegerField(verbose_name="nombre d'adhésions", default=0)
    number_of_active_memberships = models.PositiveIntegerField(verbose_name="nombre d'adhésions actives", default=0)
    number_of_memberships_as_administrator = models.PositiveIntegerField(
        verbose_name="nombre d'adhésions en tant qu'administrateur", default=0
    )
    had_memberships_in_authorized_organization = models.BooleanField(
        verbose_name="adhésion à au moins une organisation habilitée", default=False
    )
    identity_provider = models.CharField(max_length=20, verbose_name="fournisseur d'identité (SSO)")

    class Meta:
        verbose_name = "professionnel anonymisé"
        verbose_name_plural = "professionnels anonymisés"
        ordering = ["-anonymized_at"]


class AnonymizedJobSeeker(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # from User model
    date_joined = models.DateField(verbose_name="année et mois d'inscription")
    first_login = models.DateField(verbose_name="année et mois de première connexion", blank=True, null=True)
    last_login = models.DateField(verbose_name="année et mois de dernière connexion", blank=True, null=True)
    anonymized_at = models.DateTimeField(auto_now_add=True, verbose_name="anonymisé le")
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
        verbose_name = "candidat anonymisé"
        verbose_name_plural = "candidats anonymisés"
        ordering = ["-anonymized_at"]

    def __str__(self):
        return f"candidat {self.id} anonymisé le {self.anonymized_at.strftime('%Y-%m-%d %H:%M:%S')}"


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
    anonymized_at = models.DateTimeField(auto_now_add=True, verbose_name="anonymisé le")
    applied_at = models.DateField(verbose_name="année et mois de la candidature")
    processed_at = models.DateField(verbose_name="année et mois de traitement", blank=True, null=True)
    last_transition_at = models.DateField(
        verbose_name="année et mois de la dernière transition", blank=True, null=True
    )
    had_resume = models.BooleanField(verbose_name="candidature avec un CV", default=False)
    origin = models.CharField(verbose_name="origine de la candidature")
    state = models.CharField(verbose_name="état de la candidature")
    refusal_reason = models.CharField(verbose_name="raison du refus", blank=True, null=True)
    had_been_transferred = models.BooleanField(verbose_name="avait été transférée", default=False)
    number_of_jobs_applied_for = models.PositiveIntegerField(
        verbose_name="nombre d'offres d'emploi pour lesquelles le candidat a postulé", default=0
    )
    had_diagoriente_invitation = models.BooleanField(
        verbose_name="avait reçu une invitation à un diagnostic d'orientation", default=False
    )

    # hiring
    hiring_rome = models.CharField(verbose_name="code ROME de l'embauche", blank=True, null=True)
    hiring_contract_type = models.CharField(verbose_name="type de contrat de l'embauche", blank=True, null=True)
    hiring_contract_nature = models.CharField(verbose_name="nature du contrat de l'embauche", blank=True, null=True)
    hiring_start_date = models.DateField(verbose_name="année et mois de début de l'embauche", blank=True, null=True)

    class Meta:
        verbose_name = "candidature anonymisée"
        verbose_name_plural = "candidatures anonymisées"
        ordering = ["-anonymized_at"]

    def __str__(self):
        return f"candidature {self.id} anonymisée le {self.anonymized_at.strftime('%Y-%m-%d %H:%M:%S')}"
