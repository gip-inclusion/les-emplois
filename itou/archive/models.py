import uuid

from django.db import models
from django.utils import timezone


def current_year_month():
    return timezone.localdate().replace(day=1)


class AbstractAnonymizedModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    anonymized_at = models.DateField(
        verbose_name="anonymisé en année-mois", default=current_year_month, editable=False
    )

    class Meta:
        abstract = True


class AnonymizedProfessional(AbstractAnonymizedModel):
    # from User model
    date_joined = models.DateField(verbose_name="année et mois d'inscription")
    first_login = models.DateField(verbose_name="année et mois de première connexion", blank=True, null=True)
    last_login = models.DateField(verbose_name="année et mois de dernière connexion", blank=True, null=True)
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
        ordering = ["-anonymized_at", "-date_joined"]

    def __str__(self):
        return f"professionnel {self.id} anonymisé en {self.anonymized_at.strftime('%Y-%m')}"


class AnonymizedJobSeeker(AbstractAnonymizedModel):
    # from User model
    date_joined = models.DateField(verbose_name="année et mois d'inscription")
    first_login = models.DateField(verbose_name="année et mois de première connexion", blank=True, null=True)
    last_login = models.DateField(verbose_name="année et mois de dernière connexion", blank=True, null=True)
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
    count_approvals = models.PositiveIntegerField(verbose_name="nombre de PASS IAE accordés", default=0)
    first_approval_start_at = models.DateField(
        verbose_name="année et mois de début du premier PASS IAE accordé", blank=True, null=True
    )
    last_approval_end_at = models.DateField(
        verbose_name="année et mois de fin du dernier PASS IAE accordé", blank=True, null=True
    )
    count_eligibility_diagnoses = models.PositiveIntegerField(
        verbose_name="nombre de diagnostics d'éligibilité", default=0
    )

    class Meta:
        verbose_name = "candidat anonymisé"
        verbose_name_plural = "candidats anonymisés"
        ordering = ["-anonymized_at", "-date_joined"]

    def __str__(self):
        return f"candidat {self.id} anonymisé en {self.anonymized_at.strftime('%Y-%m')}"


class AnonymizedApplication(AbstractAnonymizedModel):
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
    had_approval = models.BooleanField(verbose_name="avait un PASS IAE", default=False)

    # hiring
    hiring_rome = models.CharField(verbose_name="code ROME de l'embauche", blank=True, null=True)
    hiring_contract_type = models.CharField(verbose_name="type de contrat de l'embauche", blank=True, null=True)
    hiring_start_date = models.DateField(verbose_name="année et mois de début de l'embauche", blank=True, null=True)

    class Meta:
        verbose_name = "candidature anonymisée"
        verbose_name_plural = "candidatures anonymisées"
        ordering = ["-anonymized_at", "-applied_at"]

    def __str__(self):
        return f"candidature {self.id} anonymisée en {self.anonymized_at.strftime('%Y-%m')}"


class AnonymizedApproval(AbstractAnonymizedModel):
    origin = models.CharField(verbose_name="origine du PASS")
    origin_company_kind = models.CharField(verbose_name="type d'entreprise à l'origine du PASS", blank=True, null=True)
    origin_sender_kind = models.CharField(
        verbose_name="type d'emetteur de la candidature à l'origine du PASS", blank=True, null=True
    )
    origin_prescriber_organization_kind = models.CharField(
        verbose_name="typologie du prescripteur à l'origine du PASS", blank=True, null=True
    )
    start_at = models.DateField(verbose_name="année et mois de début du PASS", blank=True, null=True)
    end_at = models.DateField(verbose_name="année et mois de fin du PASS", blank=True, null=True)
    had_eligibility_diagnosis = models.BooleanField(verbose_name="a eu un diagnostic d'éligibilité", default=False)
    number_of_prolongations = models.PositiveIntegerField(verbose_name="nombre de prolongations", default=0)
    duration_of_prolongations = models.PositiveIntegerField(
        verbose_name="durée totale des prolongations en jours", default=0
    )
    number_of_suspensions = models.PositiveIntegerField(verbose_name="nombre de suspensions", default=0)
    duration_of_suspensions = models.PositiveIntegerField(
        verbose_name="durée totale des suspensions en jours", default=0
    )
    number_of_job_applications = models.PositiveIntegerField(
        verbose_name="nombre de candidatures pour lesquelles le PASS a été utilisé", default=0
    )
    number_of_accepted_job_applications = models.PositiveIntegerField(
        verbose_name="nombre de candidatures acceptées pour lesquelles le PASS a été utilisé", default=0
    )

    class Meta:
        verbose_name = "PASS IAE anonymisé"
        verbose_name_plural = "PASS IAE anonymisés"
        ordering = ["-anonymized_at", "-start_at"]

    def __str__(self):
        return f"PASS IAE {self.id} anonymisé en {self.anonymized_at.strftime('%Y-%m')}"


class AbstractAnonymizedEligibilityDiagnosis(AbstractAnonymizedModel):
    created_at = models.DateField(verbose_name="année et mois de création du diagnostic")
    expired_at = models.DateField(verbose_name="année et mois d'expiration du diagnostic", blank=True, null=True)
    # job seeker
    job_seeker_birth_year = models.PositiveSmallIntegerField(
        verbose_name="année de naissance du candidat", blank=True, null=True
    )
    job_seeker_department = models.CharField(
        verbose_name="département du candidat", max_length=3, blank=True, null=True
    )
    # author
    author_kind = models.CharField(verbose_name="type de l'auteur du diagnostic")
    author_prescriber_organization_kind = models.CharField(
        verbose_name="type de l'organisation prescriptrice de l'auteur du diagnostic", blank=True, null=True
    )
    # administrative criteria
    # some GEIQ adminsistrative criteria have no level, so we need to keep track of them
    number_of_administrative_criteria = models.PositiveIntegerField(
        verbose_name="nombre de critères administratifs selectionnés", default=0
    )

    number_of_administrative_criteria_level_1 = models.PositiveIntegerField(
        verbose_name="nombre de critères administratifs de niveau 1", default=0
    )
    number_of_administrative_criteria_level_2 = models.PositiveIntegerField(
        verbose_name="nombre de critères administratifs de niveau 2", default=0
    )
    number_of_certified_administrative_criteria = models.PositiveIntegerField(
        verbose_name="nombre de critères administratifs certifiés", default=0
    )
    selected_administrative_criteria = models.JSONField(
        verbose_name="critères administratifs sélectionnés", default=list
    )
    # job applications
    number_of_job_applications = models.PositiveIntegerField(
        verbose_name="nombre de candidatures pour lesquelles le diagnostic a été utilisé", default=0
    )
    number_of_accepted_job_applications = models.PositiveIntegerField(
        verbose_name="nombre de candidatures acceptées pour lesquelles le diagnostic a été utilisé", default=0
    )

    class Meta:
        abstract = True


class AnonymizedSIAEEligibilityDiagnosis(AbstractAnonymizedEligibilityDiagnosis):
    author_siae_kind = models.CharField(verbose_name="type de SIAE de l'auteur du diagnostic", blank=True, null=True)
    # approvals
    number_of_approvals = models.PositiveIntegerField(
        verbose_name="nombre de PASS IAE accordés suite au diagnostic", default=0
    )
    first_approval_start_at = models.DateField(
        verbose_name="année et mois de début du premier PASS IAE accordé suite au diagnostic", blank=True, null=True
    )
    last_approval_end_at = models.DateField(
        verbose_name="année et mois de fin du dernier PASS IAE accordé suite au diagnostic", blank=True, null=True
    )

    class Meta:
        verbose_name = "diagnostic d'éligibilité SIAE anonymisé"
        verbose_name_plural = "diagnostics d'éligibilité SIAE anonymisés"
        ordering = ["-anonymized_at", "-created_at"]

    def __str__(self):
        return f"diagnostic d'éligibilité SIAE {self.id} anonymisé en {self.anonymized_at.strftime('%Y-%m')}"


class AnonymizedGEIQEligibilityDiagnosis(AbstractAnonymizedEligibilityDiagnosis):
    class Meta:
        verbose_name = "diagnostic d'éligibilité GEIQ anonymisé"
        verbose_name_plural = "diagnostics d'éligibilité GEIQ anonymisés"
        ordering = ["-anonymized_at", "-created_at"]

    def __str__(self):
        return f"diagnostic d'éligibilité GEIQ {self.id} anonymisé en {self.anonymized_at.strftime('%Y-%m')}"
