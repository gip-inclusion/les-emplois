import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
from django_xworkflows import models as xwf_models

from itou.common_apps.address.departments import department_from_postcode
from itou.companies.enums import CompanyKind
from itou.companies.models import Company
from itou.files.models import File
from itou.geiq_assessments.enums import (
    AllowanceJustificationReason,
    AllowanceRefusalReason,
    AssessmentState,
    AssessmentTransition,
)
from itou.institutions.enums import InstitutionKind
from itou.institutions.models import Institution
from itou.users.enums import Title
from itou.utils.date import nb_days_in_year
from itou.utils.models import check_nullable_date_order_constraint
from itou.utils.templatetags.str_filters import pluralizefr


# Roughly equivalent to 3 months
MIN_DAYS_IN_YEAR_FOR_ALLOWANCE = 90


class AssessmentCampaign(models.Model):
    year = models.IntegerField(verbose_name="année", unique=True)
    opening_date = models.DateField(verbose_name="date de début de la campagne")
    submission_deadline = models.DateField(verbose_name="date limite de transmission du bilan d’exécution")
    review_deadline = models.DateField(verbose_name="date limite de contrôle du bilan d’exécution")

    class Meta:
        verbose_name = "campagne de bilan d’exécution"
        verbose_name_plural = "campagnes de bilan d’exécution"
        constraints = [
            models.CheckConstraint(
                name="geiq_review_after_submission",
                violation_error_message=(
                    "Impossible d'avoir une date de contrôle antérieure à la date de transmission"
                ),
                condition=(models.Q(review_deadline__gte=models.F("submission_deadline"))),
            ),
            models.CheckConstraint(
                name="geiq_opening_before_submission",
                violation_error_message=(
                    "Impossible d'avoir une date de transmission antérieure à la date de début de campagne"
                ),
                condition=(models.Q(opening_date__lte=models.F("submission_deadline"))),
            ),
        ]

    def __str__(self):
        return f"Campagne des bilans d’exécution GEIQ de {self.year}"

    @property
    def is_open(self):
        """Whether reviews can currently be submitted (by GEIQ users) for this campaign."""
        return self.opening_date <= timezone.localdate() <= self.submission_deadline


class LabelInfos(models.Model):
    campaign = models.OneToOneField(AssessmentCampaign, on_delete=models.CASCADE, related_name="label_infos")
    data = models.JSONField(verbose_name="données label")
    synced_at = models.DateTimeField(verbose_name="données label récupérées le", auto_now=True)

    class Meta:
        verbose_name = "liste des GEIQ récupérée de label"
        verbose_name_plural = "listes des GEIQ récupérées de label"

    def __str__(self):
        return f"Liste récupérée le {timezone.localdate(self.synced_at).isoformat()}"


class AssessmentWorkflow(xwf_models.Workflow):
    states = AssessmentState.choices
    initial_state = AssessmentState.NEW

    transitions = (
        (AssessmentTransition.SUBMIT, AssessmentState.NEW, AssessmentState.SUBMITTED),
        (AssessmentTransition.REVIEW, AssessmentState.SUBMITTED, AssessmentState.REVIEWED),
        (
            AssessmentTransition.FINAL_REVIEW,
            [AssessmentState.SUBMITTED, AssessmentState.REVIEWED],
            AssessmentState.FINAL_REVIEWED,
        ),
        (AssessmentTransition.ASK_FOR_INSTITUTION_FIX, AssessmentState.REVIEWED, AssessmentState.SUBMITTED),
        (
            AssessmentTransition.ASK_FOR_GEIQ_FIX,
            [AssessmentState.SUBMITTED, AssessmentState.REVIEWED],
            AssessmentState.NEW,
        ),
    )

    log_model = "geiq_assessments.AssessmentTransitionLog"


class Assessment(xwf_models.WorkflowEnabled, models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField("créé le", auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="créé par",
        related_name="created_assessments",
        on_delete=models.RESTRICT,  # For traceability and accountability
    )
    state = xwf_models.StateField(AssessmentWorkflow, verbose_name="état")
    campaign = models.ForeignKey(AssessmentCampaign, related_name="assessments", on_delete=models.PROTECT)
    companies = models.ManyToManyField(
        Company,
        verbose_name="entreprises",
        related_name="assessments",
        limit_choices_to={"kind": CompanyKind.GEIQ},
    )
    institutions = models.ManyToManyField(
        Institution,
        verbose_name="institutions",
        related_name="implementation_assessments",
        through="AssessmentInstitutionLink",
        through_fields=("assessment", "institution"),
        limit_choices_to={
            "kind__in": [InstitutionKind.DDETS_GEIQ, InstitutionKind.DREETS_GEIQ],
        },
    )
    label_geiq_id = models.IntegerField(verbose_name="identifiant label du GEIQ principal")
    label_geiq_name = models.CharField(verbose_name="nom du GEIQ principal dans label")
    label_geiq_post_code = models.CharField(verbose_name="code postal du GEIQ principal dans label", db_default="")
    with_main_geiq = models.BooleanField(verbose_name="avec les contrats du GEIQ principal", default=False)
    label_antennas = models.JSONField(verbose_name="antennes label concernées par le bilan")

    summary_document_file = models.OneToOneField(
        File,
        verbose_name="document de synthèse généré par label",
        related_name="+",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    structure_financial_assessment_file = models.OneToOneField(
        File,
        verbose_name="bilan financier de la structure",
        related_name="+",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    action_financial_assessment_file = models.OneToOneField(
        File,
        verbose_name="bilan financier de l’action",
        related_name="+",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    label_rates = models.JSONField(verbose_name="taux récupérés sur l'API label", null=True)
    employee_nb = models.PositiveSmallIntegerField("nombre d'employés", default=0)
    contracts_synced_at = models.DateTimeField("données de contrats label récupérées le", blank=True, null=True)
    # GEIQ actions
    contracts_selection_validated_at = models.DateTimeField("sélection des contrats validée le", blank=True, null=True)
    geiq_comment = models.TextField("commentaire général du GEIQ", blank=True)

    submitted_at = models.DateTimeField("transmis le", blank=True, null=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="transmis par",
        related_name="submitted_assessments",
        null=True,
        blank=True,
        on_delete=models.RESTRICT,  # For traceability and accountability
    )
    # Institution actions
    review_comment = models.TextField("commentaire accompagnant la décision", blank=True)
    convention_amount = models.PositiveIntegerField("montant conventionné", default=0)
    granted_amount = models.PositiveIntegerField("montant total accordé", default=0)
    advance_amount = models.PositiveIntegerField("montant déjà versé", default=0)

    decision_validated_at = models.DateTimeField("décision saisie le", blank=True, null=True)
    grants_selection_validated_at = models.DateTimeField("aides accordées validées le", blank=True, null=True)
    reviewed_at = models.DateTimeField("contrôlé le", blank=True, null=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="contrôlé par",
        related_name="reviewed_assessments",
        null=True,
        blank=True,
        on_delete=models.RESTRICT,  # For traceability and accountability
    )
    reviewed_by_institution = models.ForeignKey(
        Institution,
        verbose_name="institution ayant effectué le contrôle",
        related_name="reviewed_assessments",
        null=True,
        limit_choices_to={
            "kind__in": [InstitutionKind.DDETS_GEIQ, InstitutionKind.DREETS_GEIQ],
        },
        on_delete=models.PROTECT,
    )
    final_reviewed_at = models.DateTimeField("contrôlé le (DREETS)", blank=True, null=True)
    final_reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="contrôlé par (DREETS)",
        related_name="final_reviewed_assessments",
        null=True,
        blank=True,
        on_delete=models.RESTRICT,  # For traceability and accountability
    )
    final_reviewed_by_institution = models.ForeignKey(
        Institution,
        verbose_name="institution ayant effectué le contrôle (DREETS)",
        related_name="final_reviewed_assessments",
        null=True,
        limit_choices_to={
            "kind__in": [InstitutionKind.DDETS_GEIQ, InstitutionKind.DREETS_GEIQ],
        },
        on_delete=models.PROTECT,
    )

    class Meta:
        verbose_name = "bilan d’exécution"
        verbose_name_plural = "bilans d’exécution"
        constraints = [
            check_nullable_date_order_constraint(
                "created_at",
                "contracts_synced_at",
                name="geiq_assessment_created_before_contracts_synced",
                violation_error_message=(
                    "Impossible d'avoir une date de synchronisation antérieure à la date de création"
                ),
            ),
            check_nullable_date_order_constraint(
                "contracts_synced_at",
                "contracts_selection_validated_at",
                name="geiq_assessment_contracts_synced_before_validation",
                violation_error_message=(
                    "Impossible d'avoir une date de validation de la sélection de contrats présentés "
                    "antérieure à la date de synchronisation"
                ),
            ),
            check_nullable_date_order_constraint(
                "contracts_selection_validated_at",
                "submitted_at",
                name="geiq_assessment_contracts_validated_before_submission",
                violation_error_message=(
                    "Impossible d'avoir une date de soumission antérieure à la date de validation de "
                    "la sélection de contrats présentés"
                ),
            ),
            check_nullable_date_order_constraint(
                "submitted_at",
                "grants_selection_validated_at",
                name="geiq_assessment_submission_before_grants_validated",
                violation_error_message=(
                    "Impossible d'avoir une date de validation de sélection des aides accordées antérieure à la "
                    "date de soumission"
                ),
            ),
            check_nullable_date_order_constraint(
                "grants_selection_validated_at",
                "decision_validated_at",
                name="geiq_assessment_grants_validated_before_decision",
                violation_error_message=(
                    "Impossible d'avoir une date de décision antérieure à la date de validation de la sélection des "
                    "aides accordées"
                ),
            ),
            check_nullable_date_order_constraint(
                "decision_validated_at",
                "reviewed_at",
                name="geiq_assessment_decision_before_review",
                violation_error_message=("Impossible d'avoir une date de contrôle antérieure à la date de décision"),
            ),
            check_nullable_date_order_constraint(
                "reviewed_at",
                "final_reviewed_at",
                name="geiq_assessment_review_before_final_review",
                violation_error_message=(
                    "Impossible d'avoir une date de contrôle DREETS antérieure à la date de contrôle"
                ),
            ),
            models.CheckConstraint(
                name="geiq_assessment_full_or_no_submission",
                violation_error_message="Impossible d'avoir un envoi partiel",
                condition=(
                    models.Q(submitted_at__isnull=True)
                    | (
                        models.Q(
                            submitted_at__isnull=False,
                            submitted_by__isnull=False,
                        )
                        & ~models.Q(
                            geiq_comment="",
                            summary_document_file=None,
                            structure_financial_assessment_file=None,
                            action_financial_assessment_file=None,
                        )
                    )
                ),
            ),
            models.CheckConstraint(
                name="geiq_assessment_state_submitted_at",
                violation_error_message="Impossible d'avoir de date de soumission si le statut est "
                f"{AssessmentState.NEW.label}.",
                condition=models.Q(submitted_at=None, state=AssessmentState.NEW)
                | (models.Q(submitted_at__isnull=False) & ~models.Q(state=AssessmentState.NEW)),
            ),
            models.CheckConstraint(
                name="geiq_assessment_full_or_no_review",
                violation_error_message="Impossible d'avoir un contrôle partiel",
                condition=(
                    models.Q(reviewed_at__isnull=True)
                    | (
                        models.Q(
                            reviewed_at__isnull=False,
                            reviewed_by__isnull=False,
                            reviewed_by_institution__isnull=False,
                        )
                        & ~models.Q(review_comment="")
                    )
                ),
            ),
            models.CheckConstraint(
                name="geiq_assessment_state_reviewed_at",
                violation_error_message="Impossible d'avoir de date de contrôle si le statut est "
                f"{AssessmentState.NEW.label} ou {AssessmentState.SUBMITTED.label}.",
                condition=models.Q(reviewed_at=None, state__in=[AssessmentState.NEW, AssessmentState.SUBMITTED])
                | (
                    models.Q(
                        reviewed_at__isnull=False, state__in=[AssessmentState.REVIEWED, AssessmentState.FINAL_REVIEWED]
                    )
                ),
            ),
            models.CheckConstraint(
                name="geiq_assessment_full_or_no_final_review",
                violation_error_message="Impossible d'avoir un contrôle DREETS partiel",
                condition=(
                    models.Q(final_reviewed_at__isnull=True)
                    | models.Q(
                        final_reviewed_at__isnull=False,
                        final_reviewed_by__isnull=False,
                        final_reviewed_by_institution__isnull=False,
                    )
                ),
            ),
            models.CheckConstraint(
                name="geiq_assessment_state_final_reviewed_at",
                violation_error_message="Impossible d'avoir de date de contrôle DREETS si le statut n'est "
                f"pas {AssessmentState.FINAL_REVIEWED.label}.",
                condition=(models.Q(final_reviewed_at=None) & ~models.Q(state=AssessmentState.FINAL_REVIEWED))
                | (models.Q(final_reviewed_at__isnull=False, state=AssessmentState.FINAL_REVIEWED)),
            ),
            models.UniqueConstraint(
                fields=["campaign", "label_geiq_id"],
                name="geiq_assessment_unique_label_geiq_id_with_main_geiq",
                condition=models.Q(with_main_geiq=True),
            ),
        ]

    def action_financial_assessment_filename(self):
        return f"Bilan financier action {self.campaign.year}.pdf"

    def structure_financial_assessment_filename(self):
        return f"Bilan financier structure {self.campaign.year}.pdf"

    def summary_document_filename(self):
        return f"Synthèse {self.campaign.year}.pdf"

    def missing_actions_to_submit(self):
        actions = []
        if not self.summary_document_file_id:
            actions.append("Récupérer le document de synthèse de label")
        if not self.structure_financial_assessment_file_id:
            actions.append("Récupérer le bilan financier de la structure de label")
        if not self.action_financial_assessment_file_id:
            actions.append("Transmettre le bilan financier de l’action")
        if not self.contracts_selection_validated_at:
            actions.append("Détail et sélection des contrats à présenter")
        if not self.geiq_comment:
            actions.append("Commentaire")
        return actions

    def missing_actions_to_review(self):
        actions = []
        if not self.grants_selection_validated_at:
            actions.append("Contrôler la sélection")
        if not self.decision_validated_at:
            actions.append("Saisir la décision")
        return actions

    def conventionned_institutions(self):
        return sorted(
            [
                institution_link.institution
                for institution_link in self.institution_links.all()
                if institution_link.with_convention
            ],
            key=lambda institution: (institution.kind, institution.name),
        )

    def name_for_geiq(self):
        return " / ".join(institution.name for institution in self.conventionned_institutions())

    def label_antenna_names(self):
        # A missing department should never happen, but just in case Label API does not return a proper post code
        # or provide an invalid one, we handle it gracefully and alert the user.
        MISSING_DEPARTMENT = "département non disponible"
        antenna_names = (
            [f"Siège ({department_from_postcode(self.label_geiq_post_code) or MISSING_DEPARTMENT})"]
            if self.with_main_geiq
            else []
        )

        if self.label_antennas:
            antenna_names.extend(
                [
                    f"{antenna['name']} ({department_from_postcode(antenna.get('post_code')) or MISSING_DEPARTMENT})"
                    for antenna in self.label_antennas
                ]
            )
        return antenna_names

    @xwf_models.transition()
    def submit(self, *, user):
        self.submitted_at = timezone.now()
        self.submitted_by = user

    @xwf_models.transition()
    def review(self, *, user, institution):
        self.reviewed_at = timezone.now()
        self.reviewed_by = user
        self.reviewed_by_institution = institution

    @xwf_models.transition()
    def final_review(self, *, user, institution):
        now = timezone.now()
        if self.reviewed_at is None:
            self.reviewed_at = now
            self.reviewed_by = user
            self.reviewed_by_institution = institution
        self.final_reviewed_at = now
        self.final_reviewed_by = user
        self.final_reviewed_by_institution = institution

    @xwf_models.transition()
    def ask_for_institution_fix(self, *, user, institution):
        self.reviewed_at = None
        self.reviewed_by = None
        self.reviewed_by_institution = None

    @xwf_models.transition()
    def ask_for_geiq_fix(self, *, user, institution, comment):
        self.submitted_at = None
        self.submitted_by = None

        self.reviewed_at = None
        self.reviewed_by = None
        self.reviewed_by_institution = None
        self.decision_validated_at = None
        self.grants_selection_validated_at = None

        self.final_reviewed_at = None
        self.final_reviewed_by = None
        self.final_reviewed_by_institution = None

        # Unselect all contracts for institution validation
        EmployeeContract.objects.filter(employee__assessment=self).update(allowance_granted=False)


class AssessmentTransitionLog(xwf_models.BaseTransitionLog):
    MODIFIED_OBJECT_FIELD = "assessment"
    EXTRA_LOG_ATTRIBUTES = (("user", "user", None), ("institution", "institution", None), ("comment", "comment", ""))

    assessment = models.ForeignKey(Assessment, related_name="logs", on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.RESTRICT)
    institution = models.ForeignKey(Institution, null=True, on_delete=models.RESTRICT)
    comment = models.TextField("commentaire pour expliquer la correction attendue", blank=True)

    class Meta:
        verbose_name = "log des transitions du bilan d'exécution"
        verbose_name_plural = "logs des transitions du bilan d'exécution"
        ordering = ["-timestamp"]
        constraints = [
            models.CheckConstraint(
                name="ask_for_geiq_fix_transition_with_comment",
                violation_error_message=("Une demande de correction GEIQ doit être accompagnée d'un commentaire"),
                condition=(models.Q(transition=AssessmentTransition.ASK_FOR_GEIQ_FIX) & ~models.Q(comment=""))
                | (~models.Q(transition=AssessmentTransition.ASK_FOR_GEIQ_FIX) & models.Q(comment="")),
            ),
        ]

    @classmethod
    def log_transition(cls, transition, from_state, to_state, modified_object, **kwargs):
        """Override to make timestamps between the assessment and the transition match."""
        kwargs.update(
            {
                "transition": transition,
                "from_state": from_state,
                "to_state": to_state,
                cls.MODIFIED_OBJECT_FIELD: modified_object,
            }
        )

        if transition in AssessmentTransition.with_timestamp_match():
            timestamp_attribute = {
                AssessmentState.SUBMITTED: "submitted_at",
                AssessmentState.REVIEWED: "reviewed_at",
                AssessmentState.FINAL_REVIEWED: "final_reviewed_at",
            }[to_state]

            kwargs.update({"timestamp": getattr(modified_object, timestamp_attribute)})
        return cls.objects.create(**kwargs)

    def __str__(self):
        return str(self.id)


class AssessmentInstitutionLink(models.Model):
    assessment = models.ForeignKey(
        Assessment, verbose_name="bilan lié", related_name="institution_links", on_delete=models.CASCADE
    )
    institution = models.ForeignKey(
        Institution,
        verbose_name="institution liée",
        related_name="assessment_links",
        limit_choices_to={
            "kind__in": [InstitutionKind.DDETS_GEIQ, InstitutionKind.DREETS_GEIQ],
        },
        on_delete=models.PROTECT,
    )
    with_convention = models.BooleanField(verbose_name="avec une convention", default=False)

    class Meta:
        verbose_name = "institution liée"
        verbose_name_plural = "institutions liées"
        constraints = [
            models.UniqueConstraint(fields=["assessment", "institution"], name="assessment_institution_unique"),
        ]


class Employee(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    assessment = models.ForeignKey(
        Assessment, verbose_name="bilan d’exécution", on_delete=models.CASCADE, related_name="employees"
    )
    label_id = models.IntegerField(verbose_name="ID label")
    last_name = models.CharField(verbose_name="nom de famille")
    first_name = models.CharField(verbose_name="prénom")
    birthdate = models.DateField(verbose_name="date de naissance")
    title = models.CharField(
        max_length=3,
        verbose_name="civilité",
        blank=True,
        default="",
        choices=Title.choices,
    )
    allowance_amount = models.IntegerField(verbose_name="aide potentielle")

    other_data = models.JSONField(verbose_name="autres données")

    class Meta:
        verbose_name = "employé"
        unique_together = [
            ("assessment", "label_id"),
        ]

    def get_full_name(self):
        """
        Return the last_name plus the first_name, with a space in between.
        """
        full_name = f"{self.last_name.strip().upper()} {self.first_name.title().strip()}"
        return full_name.strip()

    @property
    def display_with_pii(self):
        return self.get_full_name()

    def get_prior_actions(self):
        actions = []
        # Sorted in python to leverage prefetch_related field
        for prequalification in sorted(self.prequalifications.all(), key=lambda prequal: prequal.end_at, reverse=True):
            if prequalification.other_data.get("action_pre_qualification", {}).get("libelle_abr") != "AUTRE":
                action = prequalification.other_data.get("action_pre_qualification", {}).get("libelle")
            elif other_action := prequalification.other_data.get("autre_type_prequalification_action"):
                action = other_action
            else:
                action = "Autre"
            hour_nb = prequalification.other_data.get("nombre_heure_formation", 0)
            actions.append(
                f"{action} ({hour_nb} heure{pluralizefr(hour_nb)} "
                f"du {prequalification.start_at:%d/%m/%Y} au {prequalification.end_at:%d/%m/%Y})"
            )
        return actions

    def sex_display(self):
        if self.title == Title.M:
            return "H"
        elif self.title == Title.MME:
            return "F"
        else:
            return ""


class EmployeeContract(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    label_id = models.IntegerField(verbose_name="ID label")
    employee = models.ForeignKey(Employee, verbose_name="salarié", on_delete=models.CASCADE, related_name="contracts")

    start_at = models.DateField(verbose_name="date de début")
    planned_end_at = models.DateField(verbose_name="date de fin prévisionnelle")
    end_at = models.DateField(verbose_name="date de fin", null=True)

    nb_days_in_campaign_year = models.PositiveSmallIntegerField(verbose_name="nombre de jours dans l'année du bilan")

    allowance_requested = models.BooleanField(verbose_name="aide demandée par le GEIQ")
    allowance_granted = models.BooleanField(verbose_name="aide acceptée par l'institution")
    allowance_request_justification_reason = models.CharField(
        verbose_name="motif de la demande d'aide (GEIQ)",
        max_length=30,
        choices=AllowanceJustificationReason,
        blank=True,
    )
    allowance_request_justification_details = models.TextField(
        verbose_name="commentaire associé à la demande d'aide (GEIQ)",
        blank=True,
    )

    allowance_refusal_reason = models.CharField(
        verbose_name="motif du refus de l’aide (institution)",
        max_length=30,
        choices=AllowanceRefusalReason,
        blank=True,
    )
    allowance_refusal_details = models.TextField(
        verbose_name="commentaire associé au refus de l’aide (institution)",
        blank=True,
    )

    other_data = models.JSONField(verbose_name="autres données")

    class Meta:
        verbose_name = "contrat"
        constraints = [
            models.CheckConstraint(
                name="geiq_allowance_requested_or_not_granted",
                violation_error_message="Impossible d'accorder une aide non-sollicitée",
                condition=~models.Q(allowance_requested=False, allowance_granted=True),
            ),
            models.CheckConstraint(
                name="geiq_allowance_request_justification_set",
                violation_error_message="Le motif et le commentaire de justification doivent être renseignés ensemble",
                condition=(
                    models.Q(
                        allowance_request_justification_reason="",
                        allowance_request_justification_details="",
                    )
                    | (
                        models.Q(
                            allowance_request_justification_reason__isnull=False,
                        )
                        & ~models.Q(allowance_request_justification_details="")
                    )
                ),
            ),
            models.CheckConstraint(
                name="geiq_allowance_refusal_set",
                violation_error_message="Le motif et le commentaire de refus doivent être renseignés ensemble",
                condition=(
                    models.Q(allowance_refusal_reason="", allowance_refusal_details="")
                    | ~(models.Q(allowance_refusal_reason="") | models.Q(allowance_refusal_details=""))
                ),
            ),
        ]

    def planned_duration(self):
        return self.planned_end_at - self.start_at + timezone.timedelta(days=1)

    def real_duration(self):
        if self.end_at is None:
            return None
        return self.end_at - self.start_at + timezone.timedelta(days=1)

    def nb_days_in_previous_year(self):
        # In the year before the campaign year
        return nb_days_in_year(
            self.start_at,
            self.end_at or self.planned_end_at,
            year=self.employee.assessment.campaign.year - 1,
        )

    def nb_days_in_following_year(self):
        # In the year following the campaign year
        return nb_days_in_year(
            self.start_at,
            self.end_at or self.planned_end_at,
            year=self.employee.assessment.campaign.year + 1,
        )

    def antenna_department(self):
        antenna = self.other_data.get("antenne")
        if antenna:
            if antenna.get("id"):
                postcode = antenna.get("cp")
            else:
                postcode = self.employee.assessment.label_geiq_post_code
            return department_from_postcode(postcode)
        return None

    def rupture_kind_display(self):
        rupture = self.other_data.get("rupture")
        if rupture is None:
            return ""
        elif rupture:
            return "Hors période d’essai"
        else:
            return "En période d’essai"

    @property
    def requires_justification(self):
        return self.allowance_requested and self.nb_days_in_campaign_year < MIN_DAYS_IN_YEAR_FOR_ALLOWANCE


class EmployeePrequalification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    label_id = models.IntegerField(verbose_name="ID label")
    employee = models.ForeignKey(
        Employee, verbose_name="salarié", on_delete=models.CASCADE, related_name="prequalifications"
    )

    start_at = models.DateField(verbose_name="date de début")
    end_at = models.DateField(verbose_name="date de fin")

    other_data = models.JSONField(verbose_name="autres données")

    class Meta:
        verbose_name = "préqualification"
