import datetime
import logging
import uuid

import pgtrigger
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import ArrayField, RangeBoundary, RangeOperators
from django.core.exceptions import ValidationError
from django.core.validators import MinLengthValidator
from django.db import models, transaction
from django.db.models import Case, Count, F, OuterRef, Q, Subquery, When
from django.db.models.functions import Now, TruncDate
from django.utils import timezone
from django.utils.functional import cached_property
from django.utils.safestring import mark_safe
from django.utils.timesince import timeuntil
from unidecode import unidecode

from itou.approvals import enums, notifications
from itou.approvals.constants import PROLONGATION_REPORT_FILE_REASONS
from itou.approvals.enums import Origin
from itou.approvals.utils import get_user_last_accepted_siae_job_application, last_hire_was_made_by_siae
from itou.companies import enums as companies_enums
from itou.employee_record.enums import Status
from itou.files.models import File
from itou.job_applications import enums as job_application_enums
from itou.prescribers import enums as prescribers_enums
from itou.users.enums import IdentityCertificationAuthorities
from itou.users.models import IdentityCertification
from itou.utils.apis import enums as api_enums, pole_emploi_partenaire_api_client
from itou.utils.apis.pole_emploi import DATE_FORMAT, PoleEmploiAPIBadResponse, PoleEmploiAPIException
from itou.utils.db import or_queries
from itou.utils.models import DateRange
from itou.utils.templatetags.str_filters import pluralizefr
from itou.utils.validators import alphanumeric, validate_siret


logger = logging.getLogger(__name__)

SUSPENSION_DURATION_BEFORE_APPROVAL_DELETABLE = datetime.timedelta(days=365)


class CommonApprovalMixin(models.Model):
    """
    Abstract model for fields and methods common to both `Approval`
    and `PoleEmploiApproval` models.
    """

    # Default duration of an approval.
    DEFAULT_APPROVAL_DAYS = 2 * 365
    # `Période de carence` in French.
    # A period after expiry of an Approval during which a person cannot
    # obtain a new one except from an "authorized prescriber".
    WAITING_PERIOD_YEARS = 2

    start_at = models.DateField(verbose_name="date de début", default=timezone.localdate, db_index=True)
    end_at = models.DateField(verbose_name="date de fin", default=timezone.localdate, db_index=True)
    created_at = models.DateTimeField(verbose_name="date de création", default=timezone.now)

    number = models.CharField(
        verbose_name="numéro",
        max_length=12,
        help_text="12 caractères alphanumériques.",
        validators=[alphanumeric, MinLengthValidator(12)],
        unique=True,
    )

    class Meta:
        abstract = True
        constraints = [
            # Prevent start == end because:
            # - it was the behavior implemented in clean()
            # - when sent to pole emploi, start == end is interpreted as a cancelled approval
            models.CheckConstraint(
                name="%(app_label)s_%(class)s_start_before_end",
                condition=models.Q(start_at__lt=models.F("end_at")),
            ),
        ]

    def is_valid(self):
        return timezone.localdate() <= self.end_at

    @classmethod
    def last_number(cls):
        # Lock the table's first row until the end of the transaction, effectively acting as a
        # poor man's semaphore.
        cls.objects.order_by("pk").select_for_update(of=("self",), no_key=True).first()
        # Now we can do a whole new SELECT that will take into account eventual new rows.
        number = (
            cls.objects.filter(number__startswith=Approval.ASP_ITOU_PREFIX)
            .order_by("number")
            .values_list("number", flat=True)
            .last()
        )
        if number:
            return int(number.removeprefix(Approval.ASP_ITOU_PREFIX))
        return 0

    @property
    def is_in_progress(self):
        return self.start_at <= timezone.localdate() <= self.end_at

    @property
    def waiting_period_end(self):
        return self.end_at + relativedelta(years=self.WAITING_PERIOD_YEARS)

    @property
    def is_in_waiting_period(self):
        return self.end_at < timezone.localdate() <= self.waiting_period_end

    @property
    def waiting_period_has_elapsed(self):
        return timezone.localdate() > self.waiting_period_end

    @property
    def is_pass_iae(self):
        """
        Returns True if the approval has been issued by Itou, False otherwise.
        """
        return isinstance(self, Approval)

    @property
    def duration(self):
        return self.end_at - self.start_at + datetime.timedelta(days=1)

    def _get_obj_remainder(self, obj):
        """
        Return the remaining time on an object with start_at and end_at dete fields
        A.k.a an Approval, a Suspension or a Prolongation
        """
        return max(
            obj.end_at
            - timezone.localdate()
            # end_at is inclusive.
            + datetime.timedelta(days=1),
            datetime.timedelta(0),
        ) - max(obj.start_at - timezone.localdate(), datetime.timedelta(0))

    def _get_human_readable_estimate(self, delta: datetime.timedelta) -> str:
        any_day = timezone.localdate()  # It is not meaningful
        res = timeuntil(any_day + delta, now=any_day)
        res = res.replace("année", "an")
        res = res.split(", ")
        if any(v in res[0] for v in ["an", "mois"]):
            return "Environ " + " et ".join(res)
        return " et ".join(res)

    @cached_property
    def remainder(self):
        """
        Return the remaining time of an Approval, we don't count future suspended periods.
        """
        result = self._get_obj_remainder(self)

        if hasattr(self, "suspension_set"):
            # PoleEmploiApprovals don't have suspensions
            result -= sum(
                (self._get_obj_remainder(suspension) for suspension in self.suspension_set.all()),
                datetime.timedelta(0),
            )
        return result

    def get_remainder_display(self):
        remainder_display = f"{self.remainder.days} jour{pluralizefr(self.remainder.days)}"
        if self.remainder.days >= 7:  # Prevent displaying "2 jours (2 jours)"
            remainder_display += f" ({self._get_human_readable_estimate(self.remainder)})"
        return remainder_display

    get_remainder_display.short_description = "Reliquat"

    @property
    def remainder_as_date(self):
        """
        Return an estimated end date.
        Prolongations are taken into account but not suspensions as an approval can be unsuspended.
        """
        return min(
            max(self.start_at, timezone.localdate())  # Approval can start in the future
            + relativedelta(
                days=self.remainder.days
                # end_at is inclusive.
                - 1,
            ),
            self.end_at,
        )

    @property
    def is_suspended(self):
        # Only Approvals may be suspended, but it's required in state property
        return False

    @property
    def state(self):
        if not self.is_valid():
            return enums.ApprovalStatus.EXPIRED
        if self.is_suspended:
            return enums.ApprovalStatus.SUSPENDED
        if self.is_in_progress:
            return enums.ApprovalStatus.VALID
        # When creating an approval, it usually starts in the future.
        # That's why the default "valid" state is future.
        return enums.ApprovalStatus.FUTURE

    def get_state_display(self):
        return self.state.label


class CommonApprovalQuerySet(models.QuerySet):
    """
    A QuerySet shared by both `Approval` and `PoleEmploiApproval` models.
    """

    @property
    def valid_lookup(self):
        return Q(end_at__gte=timezone.localdate())

    def valid(self):
        return self.filter(self.valid_lookup)

    def invalid(self):
        return self.exclude(self.valid_lookup)

    def starts_in_the_past(self):
        return self.filter(Q(start_at__lt=timezone.localdate()))

    def starts_today(self):
        return self.filter(start_at=timezone.localdate())

    def starts_in_the_future(self):
        return self.filter(Q(start_at__gt=timezone.localdate()))


class ApprovalQuerySet(CommonApprovalQuerySet):
    def delete(self, enable_mass_delete=False):
        # NOTE(vperron): Deleting through a queryset method would not leave us the opportunity to
        # create a CancelledApproval object for each deleted Approval.
        # NOTE(vincentporte): Mass deletion is needed for jobseekers anonymization, so we make it possible only if
        # the approvals ended at least 2 years ago.
        recent_exists = self.filter(end_at__gt=timezone.localdate() - relativedelta(years=2)).exists()
        if not enable_mass_delete or recent_exists:
            raise NotImplementedError(
                "Supprimer en masse des PASS IAE non échus depuis au moins 2 ans est interdit,"
                " veuillez les annuler un par un."
            )
        #
        return super().delete()

    def with_assigned_company(self):
        job_application_model = self.model._meta.get_field("jobapplication").related_model
        return self.annotate(
            assigned_company=Subquery(
                job_application_model.objects.accepted()
                .with_accepted_at()
                .filter(job_seeker=OuterRef("user"))
                .order_by("-accepted_at", "-hiring_start_at")
                .values("to_company")[:1],
            )
        )

    def is_assigned_to(self, company_id):
        from itou.job_applications.models import JobApplication

        return (
            self.filter(pk__in=JobApplication.objects.filter(to_company=company_id).values_list("approval"))
            .with_assigned_company()
            .filter(assigned_company=company_id)
        )

    def inconsistent_eligibility_diagnosis_job_seeker(self):
        return self.filter(eligibility_diagnosis__isnull=False).exclude(eligibility_diagnosis__job_seeker=F("user"))


class PENotificationMixin(models.Model):
    pe_notification_status = models.CharField(
        verbose_name="état de la notification à PE",
        max_length=32,
        default=api_enums.PEApiNotificationStatus.PENDING,
        choices=api_enums.PEApiNotificationStatus.choices,
    )
    pe_notification_time = models.DateTimeField(verbose_name="date de notification à PE", null=True, blank=True)
    pe_notification_endpoint = models.CharField(
        verbose_name="dernier endpoint de l'API PE contacté",
        max_length=32,
        choices=api_enums.PEApiEndpoint.choices,
        blank=True,
        null=True,
    )
    pe_notification_exit_code = models.CharField(
        max_length=64,
        # remember that those choices are mostly for documentation purposes but do not
        # constrain the code to actually be among those, which is fortunate since
        # we don't want the app to break if PE suddenly adds a code.
        choices=list(api_enums.PEApiRechercheIndividuExitCode.choices)
        + list(api_enums.PEApiMiseAJourPassExitCode.choices),
        verbose_name="dernier code de sortie constaté",
        blank=True,
        null=True,
    )

    class Meta:
        abstract = True

    def get_pe_end_at(self):
        return self.end_at.strftime(DATE_FORMAT)

    def _pe_notification_update(
        self, status: api_enums.PEApiNotificationStatus, at: datetime.datetime, endpoint=None, exit_code=None
    ) -> api_enums.PEApiNotificationStatus:
        """A helper method to update the fields of the mixin:
        - whatever the destination class (Approval, PoleEmploiApproval)
        - without triggering the model's save() method which usually is quite computation intensive

        This will become useless when we will stop managing the PoleEmploiApproval that much.
        """
        self.__class__.objects.filter(pk=self.pk).update(
            pe_notification_status=status,
            pe_notification_time=at,
            pe_notification_endpoint=endpoint,
            pe_notification_exit_code=exit_code,
        )

        return status

    def pe_save_pending(self, at, *, reason):
        return self._pe_notification_update(api_enums.PEApiNotificationStatus.PENDING, at, None, reason)

    def pe_save_error(self, at, *, endpoint, exit_code):
        return self._pe_notification_update(api_enums.PEApiNotificationStatus.ERROR, at, endpoint, exit_code)

    def pe_save_should_retry(self, at):
        return self._pe_notification_update(api_enums.PEApiNotificationStatus.SHOULD_RETRY, at)

    def pe_save_success(self, at):
        return self._pe_notification_update(api_enums.PEApiNotificationStatus.SUCCESS, at)

    def _pe_log(self, prefix, fmt, *args, **kwargs):
        logger.info(
            "%s notify_pole_emploi %s=%s %s",
            prefix,
            self._meta.model_name,
            self,
            fmt.format(*args, **kwargs),
        )

    def pe_log_info(self, fmt, *args, **kwargs):
        self._pe_log(">", fmt, *args, **kwargs)

    def pe_log_err(self, fmt, *args, **kwargs):
        self._pe_log("!", fmt, *args, **kwargs)

    def pe_maj_pass(self, *, id_national_pe, siae_siret, siae_kind, sender_kind, prescriber_kind, at):
        pe_client = pole_emploi_partenaire_api_client()

        typologie_prescripteur = None
        if prescriber_kind:
            typologie_prescripteur = prescribers_enums.PrescriberOrganizationKind(
                prescriber_kind
            ).to_PE_typologie_prescripteur()

        origine_candidature = job_application_enums.sender_kind_to_pe_origine_candidature(sender_kind)

        try:
            pe_client.mise_a_jour_pass_iae(
                self,
                id_national_pe,
                siae_siret,
                companies_enums.siae_kind_to_ft_type_siae(siae_kind),
                origine_candidature=origine_candidature,
                typologie_prescripteur=typologie_prescripteur,
            )
        except PoleEmploiAPIException:
            self.pe_log_err("got a recoverable error in maj_pass_iae")
            return self.pe_save_should_retry(at)
        except PoleEmploiAPIBadResponse as exc:
            self.pe_log_err("got an unrecoverable error={} in maj_pass_iae", exc.response_code)
            return self.pe_save_error(
                at, endpoint=api_enums.PEApiEndpoint.MISE_A_JOUR_PASS_IAE, exit_code=exc.response_code
            )
        else:
            self.pe_log_info("got success in maj_pass_iae")
            return self.pe_save_success(at)


class CancelledApproval(PENotificationMixin, CommonApprovalMixin):
    user_last_name = models.CharField(verbose_name="nom demandeur d'emploi")
    user_first_name = models.CharField(verbose_name="prénom demandeur d'emploi")
    user_nir = models.CharField(verbose_name="NIR demandeur d'emploi", blank=True)
    user_birthdate = models.DateField(
        verbose_name="date de naissance demandeur d'emploi",
        null=True,
        blank=True,
    )
    user_id_national_pe = models.CharField(verbose_name="identifiant national PE", blank=True, null=True)

    origin_siae_siret = models.CharField(verbose_name="siret siae", max_length=14)
    origin_siae_kind = models.CharField(verbose_name="type siae", choices=companies_enums.CompanyKind.choices)

    origin_sender_kind = models.CharField(
        verbose_name="origine de la candidature",
        choices=job_application_enums.SenderKind.choices,
    )
    origin_prescriber_organization_kind = models.CharField(
        verbose_name="typologie prescripteur",
        choices=prescribers_enums.PrescriberOrganizationKind.choices,
    )

    class Meta:
        verbose_name = "PASS IAE annulé"
        verbose_name_plural = "PASS IAE annulés"
        ordering = ["-created_at"]
        constraints = CommonApprovalMixin.Meta.constraints

    def __str__(self):
        return self.number

    def get_pe_end_at(self):
        # For cancelled approval, we send start_at == end_at
        return self.start_at.strftime(DATE_FORMAT)

    def notify_pole_emploi(self) -> api_enums.PEApiNotificationStatus:
        at = timezone.now()
        today = timezone.localdate(at)
        if self.start_at > today:
            self.pe_log_err("start_at={} starts after today={}", self.start_at, today)
            return self.pe_save_pending(
                at,
                reason=api_enums.PEApiPreliminaryCheckFailureReason.STARTS_IN_FUTURE,
            )

        type_siae = companies_enums.siae_kind_to_ft_type_siae(self.origin_siae_kind)
        if not type_siae:
            self.pe_log_err(
                "could not find PE type for siae_siret={} siae_kind={}", self.origin_siae_siret, self.origin_siae_kind
            )
            return self.pe_save_error(
                at,
                endpoint=None,
                exit_code=api_enums.PEApiPreliminaryCheckFailureReason.INVALID_SIAE_KIND,
            )

        if not all(
            [
                self.user_first_name,
                self.user_last_name,
                self.user_nir,
                self.user_birthdate,
            ]
        ):
            self.pe_log_err(
                "had an invalid user_first_name={} user_last_name={} nir={}",
                self.user_first_name,
                self.user_last_name,
                self.user_nir,
            )
            # we save those as pending since the cron will ignore those cases anyway and thus has
            # no chance to block itself.
            return self.pe_save_pending(
                at,
                reason=api_enums.PEApiPreliminaryCheckFailureReason.MISSING_USER_DATA,
            )

        if not self.user_id_national_pe:
            pe_client = pole_emploi_partenaire_api_client()
            try:
                id_national = pe_client.recherche_individu_certifie(
                    first_name=self.user_first_name,
                    last_name=self.user_last_name,
                    nir=self.user_nir,
                    birthdate=self.user_birthdate,
                )
            except PoleEmploiAPIException:
                self.pe_log_err("got a recoverable error in recherche_individu")
                return self.pe_save_should_retry(at)
            except PoleEmploiAPIBadResponse as exc:
                self.pe_log_err("got an unrecoverable error={} in recherche_individu", exc.response_code)
                return self.pe_save_error(
                    at, endpoint=api_enums.PEApiEndpoint.RECHERCHE_INDIVIDU, exit_code=exc.response_code
                )
            self.user_id_national_pe = id_national
            self.save(update_fields=["user_id_national_pe"])
        return self.pe_maj_pass(
            id_national_pe=self.user_id_national_pe,
            siae_siret=self.origin_siae_siret,
            siae_kind=self.origin_siae_kind,
            sender_kind=self.origin_sender_kind,
            prescriber_kind=self.origin_prescriber_organization_kind,
            at=at,
        )


class Approval(PENotificationMixin, CommonApprovalMixin):
    """
    Store "PASS IAE" whose former name was "approval" ("agréments" in French)
    issued by Itou.

    A number starting with `ASP_ITOU_PREFIX` means it has been created by Itou.

    Otherwise, it was previously created by Pôle emploi (and initially found
    in `PoleEmploiApproval`) and re-issued by Itou as a PASS IAE.
    """

    # This prefix is used by the ASP system to identify itou as the issuer of a number.
    ASP_ITOU_PREFIX = settings.ASP_ITOU_PREFIX

    # The period of time during which it is possible to prolong a PASS IAE.
    IS_OPEN_TO_PROLONGATION_BOUNDARIES_MONTHS_BEFORE_END = 7

    # Error messages.
    ERROR_PASS_IAE_SUSPENDED_FOR_USER = (
        "Votre PASS IAE est suspendu. Vous ne pouvez pas postuler pendant la période de suspension."
    )
    ERROR_PASS_IAE_SUSPENDED_FOR_PROXY = (
        "Le PASS IAE du candidat est suspendu. Vous ne pouvez pas postuler pour lui pendant la période de suspension."
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="demandeur d'emploi",
        on_delete=models.PROTECT,  # 2-step deletion, first the Approval to create a CancelledApproval then the User
        related_name="approvals",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="créé par",
        null=True,
        blank=True,
        on_delete=models.RESTRICT,  # For traceability and accountability
    )
    origin = models.CharField(
        verbose_name="origine du pass",
        max_length=30,
        choices=Origin.choices,
        default=Origin.DEFAULT,
    )
    # The job seeker's eligibility diagnosis used for the job application
    # that created this Approval
    eligibility_diagnosis = models.ForeignKey(
        "eligibility.EligibilityDiagnosis",
        verbose_name="diagnostic d'éligibilité",
        null=True,
        blank=True,
        on_delete=models.RESTRICT,  # To not mess with the `approval_eligibility_diagnosis` constraint
    )

    updated_at = models.DateTimeField(verbose_name="date de modification", auto_now=True)

    # 2023-08-17: An experiment to add a denormalized field “last_suspension_ended_at” did not exhibit large
    # performance improvements, nor huge readability boons. https://github.com/betagouv/itou/pull/2746

    # Origin fields stored to enable
    origin_siae_siret = models.CharField(verbose_name="siret siae à l'origine du PASS IAE", max_length=14, null=True)
    origin_siae_kind = models.CharField(
        verbose_name="type siae à l'origine du PASS IAE", choices=companies_enums.CompanyKind.choices, null=True
    )
    origin_sender_kind = models.CharField(
        verbose_name="origine de la candidature à l'origine du PASS IAE",
        choices=job_application_enums.SenderKind.choices,
        null=True,
    )
    origin_prescriber_organization_kind = models.CharField(
        verbose_name="typologie prescripteur à l'origine du PASS IAE",
        choices=prescribers_enums.PrescriberOrganizationKind.choices,
    )

    public_id = models.UUIDField(
        verbose_name="identifiant public",
        help_text="identifiant opaque, pour les API et les URLs publiques",
        default=uuid.uuid4,
        unique=True,
    )

    objects = ApprovalQuerySet.as_manager()

    class Meta:
        verbose_name = "PASS IAE"
        verbose_name_plural = "PASS IAE"
        ordering = ["-created_at"]
        constraints = CommonApprovalMixin.Meta.constraints + [
            models.CheckConstraint(
                name="approval_eligibility_diagnosis",
                condition=models.Q(origin__in=[Origin.ADMIN, Origin.DEFAULT], eligibility_diagnosis__isnull=False)
                | models.Q(origin__in=[Origin.PE_APPROVAL, Origin.AI_STOCK], eligibility_diagnosis=None),
                violation_error_message="Incohérence entre l'origine du PASS IAE "
                "et la présence d'un diagnostic d'éligibilité",
            )
        ]
        permissions = [
            ("export_ft_api_rejections", "Can export PASS IAE rejected by FT's API"),
            ("handle_manual_approval_requests", "Can handle manual PASS IAE requests"),
        ]
        triggers = [
            pgtrigger.Trigger(
                name="create_employee_record_notification",
                when=pgtrigger.After,
                operation=pgtrigger.UpdateOf("start_at", "end_at"),
                condition=pgtrigger.Q(old__end_at__df=pgtrigger.F("new__end_at"))
                | pgtrigger.Q(old__start_at__df=pgtrigger.F("new__start_at")),
                func=f"""
                    -- If there is an "UPDATE" action on 'approvals_approval' table (Approval model object):
                    -- create an `EmployeeRecordUpdateNotification` object for each PROCESSED `EmployeeRecord`
                    -- linked to this approval
                    IF (TG_OP = 'UPDATE') THEN
                        -- Only for update operations:
                        -- iterate through processed employee records linked to this approval
                        FOR current_employee_record_id IN
                            SELECT id FROM employee_record_employeerecord
                            WHERE approval_number = NEW.number
                            AND status IN (
                                '{Status.PROCESSED.value}', '{Status.SENT.value}', '{Status.DISABLED.value}'
                            )
                            LOOP
                                -- Create `EmployeeRecordUpdateNotification` object
                                -- with the correct type and status
                                INSERT INTO employee_record_employeerecordupdatenotification
                                    (employee_record_id, created_at, updated_at, status)
                                SELECT current_employee_record_id, NOW(), NOW(), '{Status.NEW.value}'
                                -- Update it if already created (UPSERT)
                                -- On partial indexes conflict, the where clause of the index must be added here
                                ON conflict(employee_record_id) WHERE status = '{Status.NEW.value}'
                                DO
                                -- Not exactly the same syntax as a standard update op
                                UPDATE SET updated_at = NOW();
                            END LOOP;
                    END IF;
                    RETURN NULL;
                """,
                declare=[("current_employee_record_id", "INT")],
            ),
            pgtrigger.Trigger(
                name="plan_pe_notification_on_date_updates",
                when=pgtrigger.Before,
                operation=pgtrigger.UpdateOf("start_at", "end_at"),
                condition=pgtrigger.Q(old__end_at__df=pgtrigger.F("new__end_at"))
                | pgtrigger.Q(old__start_at__df=pgtrigger.F("new__start_at")),
                func=f"""
                    -- If there is an "UPDATE" action on 'approvals_approval' table (Approval model object)
                    -- and dates are modified then reset pe_notification_status field to PENDING status
                    IF (TG_OP = 'UPDATE') THEN
                        IF NEW.pe_notification_status IS DISTINCT FROM OLD.pe_notification_status THEN
                            RAISE EXCEPTION 'Modification de pe_notification_status en même temps que les dates';
                        END IF;
                        NEW.pe_notification_status := '{api_enums.PEApiNotificationStatus.PENDING}';
                    END IF;
                    RETURN NEW;
                """,
            ),
        ]

    def __str__(self):
        return self.number

    def save(self, *args, **kwargs):
        self.clean()
        if not self.number:
            # `get_next_number` will lock rows until the end of the transaction.
            self.number = self.get_next_number()
        if not self.number.startswith(Approval.ASP_ITOU_PREFIX):
            # Override any existing origin as a PE Approval converted from the admin is still a PE Approval
            self.origin = Origin.PE_APPROVAL
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        sender_kind = self.origin_sender_kind
        prescriber_organization_kind = self.origin_prescriber_organization_kind
        siae_siret = self.origin_siae_siret
        siae_kind = self.origin_siae_kind
        if not all((sender_kind, siae_siret, siae_kind)):
            job_application = self.jobapplication_set.accepted().order_by("-created_at").first()
            if not job_application:
                # This should only happen for historical approvals and we'll have to find the root cause and fix it
                raise ValueError("Cannot delete an approval without an accepted job application.")
            if prescriber_org := job_application.sender_prescriber_organization:
                prescriber_organization_kind = prescriber_org.kind
            else:
                prescriber_organization_kind = ""
            siae_siret = job_application.to_company.siret
            siae_kind = job_application.to_company.kind
            sender_kind = job_application.sender_kind
        CancelledApproval(
            start_at=self.start_at,
            end_at=self.end_at,
            number=self.number,
            user_last_name=self.user.last_name,
            user_first_name=self.user.first_name,
            user_nir=self.user.jobseeker_profile.nir,
            user_birthdate=self.user.jobseeker_profile.birthdate,
            user_id_national_pe=self.user.jobseeker_profile.pe_obfuscated_nir,
            origin_siae_siret=siae_siret,
            origin_siae_kind=siae_kind,
            origin_sender_kind=sender_kind,
            origin_prescriber_organization_kind=prescriber_organization_kind,
        ).save()
        self.jobapplication_set.update(approval=None)
        super().delete()

    def clean(self):
        try:
            if self.end_at <= self.start_at:
                raise ValidationError("La date de fin doit être postérieure à la date de début.")
        except TypeError:
            # This can happen if `end_at` or `start_at` are empty or malformed
            # (e.g. when data comes from a form).
            pass
        already_exists = bool(self.pk)
        if not already_exists and hasattr(self, "user") and self.user.approvals.valid().exists():
            raise ValidationError(
                f"Un agrément dans le futur ou en cours de validité existe déjà "
                f"pour {self.user.get_full_name()} ({self.user.email})."
            )
        super().clean()

    @property
    def number_with_spaces(self):
        """
        Insert spaces to format the number.
        """
        return f"{self.number[:5]} {self.number[5:7]} {self.number[7:]}"

    def can_be_deleted(self):
        JobApplication = self.jobapplication_set.model
        try:
            return self.jobapplication_set.filter(state=job_application_enums.JobApplicationState.ACCEPTED).get()
        except (JobApplication.DoesNotExist, JobApplication.MultipleObjectsReturned):
            return False

    @cached_property
    def is_last_for_user(self):
        """
        Returns True if the current Approval is the most recent for the user, False otherwise.
        """
        return self == self.user.approvals.order_by("start_at").last()

    # Suspension.

    @property
    def ongoing_suspension(self):
        # Don't make a query if suspensions were prefetched
        if hasattr(self, "_prefetched_objects_cache") and "suspension_set" in self._prefetched_objects_cache:
            today = timezone.localdate()
            for suspension in self._prefetched_objects_cache["suspension_set"]:
                if suspension.start_at <= today <= suspension.end_at:
                    return suspension
            return None
        return self.suspension_set.in_progress().first()

    @cached_property
    def is_suspended(self):
        # Don't make a query if suspensions were prefetched
        if hasattr(self, "_prefetched_objects_cache") and "suspension_set" in self._prefetched_objects_cache:
            return self.ongoing_suspension is not None

        return self.suspension_set.in_progress().exists()

    @property
    def suspensions_for_status_card(self):
        suspensions = self.suspension_set.all().order_by("-start_at")
        if not suspensions:
            return

        older_suspensions = suspensions
        last_in_progress_suspension = None
        # Suspensions cannot start in the future.
        if suspensions[0].is_in_progress:
            [last_in_progress_suspension, *older_suspensions] = suspensions

        return {"last_in_progress": last_in_progress_suspension, "older": older_suspensions}

    def last_old_suspension(self, exclude_pk=None):
        return self.suspension_set.old().exclude(pk=exclude_pk).order_by("start_at").last()

    @cached_property
    def can_be_suspended(self):
        return self.is_in_progress and not self.is_suspended

    def can_be_suspended_by_siae(self, siae):
        # Only the SIAE currently hiring the job seeker can suspend a PASS IAE.
        return self.can_be_suspended and last_hire_was_made_by_siae(self.user, siae)

    @cached_property
    def last_in_progress_suspension(self):
        return self.suspension_set.in_progress().order_by("start_at").last()

    @cached_property
    def can_be_unsuspended(self):
        if self.is_suspended:
            return self.last_in_progress_suspension.reason in Suspension.REASONS_ALLOWING_UNSUSPEND
        return False

    def unsuspend(self, hiring_start_at):
        """
        When a job application is accepted, the approval is "unsuspended":
        we do it by setting its end_date to JobApplication.hiring_start_at - 1 day,
        or deleting if JobApplication.hiring starts the day suspension starts.
        """
        active_suspension = self.last_in_progress_suspension
        if active_suspension and self.can_be_unsuspended:
            if active_suspension.start_at == hiring_start_at:
                active_suspension.delete()
            else:
                active_suspension.end_at = hiring_start_at - relativedelta(days=1)
                active_suspension.save()

    # Postpone start date.

    @property
    def can_postpone_start_date(self):
        return self.start_at > timezone.localdate()

    def update_start_date(self, new_start_date):
        """
        An SIAE can postpone the start date of a job application if the contract has not begun yet.
        In this case, the approval start date must be updated with the start date of the hiring.

        Returns True if date has been updated, False otherwise
        """
        # Only approvals which are not started yet can be postponed.
        if self.can_postpone_start_date:
            self.start_at = new_start_date
            # At first, we computed the end date applying a delay like this:
            # delay = new_start_date - self.start_at
            # self.end_at = self.end_at + delay
            # But this is error-prone on leap years!
            # Instead, set the default end date.
            self.end_at = self.get_default_end_date(new_start_date)
            self.save()
            return True
        return False

    # Prolongation.

    @property
    def prolongations_for_status_card(self):
        # Code would be easier to read if we used QS filters like this:
        # in_progress_prolongations = self.prolongation_set.in_progress().order_by("-start_at")
        # but this would generate 2 queries instead of one.
        annotation = Case(When(Prolongation.objects._queryset_class().in_progress_lookup, then=True), default=False)
        prolongations = (
            self.prolongation_set.annotate(is_in_progress_lookup=annotation)
            .select_related("validated_by")
            .all()
            .order_by("-start_at")
        )
        if not prolongations:
            return

        in_progress_prolongations = list(filter(lambda p: p.is_in_progress_lookup, prolongations))
        not_in_progress_prolongations = list(filter(lambda p: not p.is_in_progress_lookup, prolongations))

        return {"in_progress": in_progress_prolongations, "not_in_progress": not_in_progress_prolongations}

    def prolongation_requests_for_status_card(self):
        # Don't show granted prolongation requests as they will have generated a proper prolongation
        return self.prolongationrequest_set.exclude(status=enums.ProlongationRequestStatus.GRANTED)

    def pending_prolongation_request(self):
        return self.prolongationrequest_set.filter(status=enums.ProlongationRequestStatus.PENDING).first()

    @property
    def is_open_to_prolongation(self):
        now = timezone.localdate()
        lower_bound = self.end_at - relativedelta(months=self.IS_OPEN_TO_PROLONGATION_BOUNDARIES_MONTHS_BEFORE_END)
        return lower_bound <= now <= self.end_at

    @cached_property
    def can_be_prolonged(self):
        # Since it is possible to prolong even 3 months after the end of a PASS IAE,
        # it is possible that another one has been issued in the meantime. Thus we
        # have to ensure that the current PASS IAE is the most recent for the user
        # before allowing a prolongation.
        return (
            self.is_last_for_user
            and self.is_open_to_prolongation
            and not self.is_suspended
            and not self.pending_prolongation_request()
        )

    @staticmethod
    def get_origin_kwargs(origin_job_application):
        return {
            "origin_siae_siret": origin_job_application.to_company.siret,
            "origin_siae_kind": origin_job_application.to_company.kind,
            "origin_sender_kind": origin_job_application.sender_kind,
            "origin_prescriber_organization_kind": (
                origin_job_application.sender_prescriber_organization.kind
                if origin_job_application.sender_prescriber_organization
                else ""
            ),
        }

    @staticmethod
    def get_next_number():
        """
        Find next "PASS IAE" number.

        Numbering scheme for a 12 chars "PASS IAE" number:
            - ASP_ITOU_PREFIX (5 chars) + NUMBER (7 chars)

        Old numbering scheme for PASS IAE <= `99999.21.35866`:
            - ASP_ITOU_PREFIX (5 chars) + YEAR WITHOUT CENTURY (2 chars) + NUMBER (5 chars)
            - YEAR WITHOUT CENTURY is equal to the start year of the `JobApplication.hiring_start_at`
            - A max of 99999 approvals could be issued by year
            - We would have gone beyond, we would never have thought we could go that far

        For future reference:
            An advisory lock would be safer than the dual select_for_update() performed here.
            Code sample (courtesy of @ffreitag):

            def acquire_lock(name):
                if not connection.in_atomic_block:
                    raise RuntimeError("Database is not in a transaction.")

                key = zlib.crc32(name.encode())
                with conn.cursor() as cursor:
                    cursor.execute("SELECT pg_try_advisory_xact_lock(%s)", (key,))
                    (acquired,) = cursor.fetchone()
                return acquired

            The difficult part would be to implement the tests properly, meaning to reproduce the
            problems met in production (namely, deadlocks or holes/duplicate numbers)

            Keep the "poor man's version" for now as it's probably enough (and tested) but keep an eye on:
            - deadlocks (cancelling an approval never finishes and eventually fails)
            - holes/duplicates in the combined sequence of Approval + CancelledApproval
        """
        next_number = max(Approval.last_number(), CancelledApproval.last_number()) + 1
        if next_number > 9999999:
            raise RuntimeError("The maximum number of PASS IAE has been reached.")
        return f"{Approval.ASP_ITOU_PREFIX}{next_number:07d}"

    @staticmethod
    def get_default_end_date(start_at):
        return (
            start_at
            + datetime.timedelta(days=Approval.DEFAULT_APPROVAL_DAYS)
            # end_at is inclusive.
            - datetime.timedelta(days=1)
        )

    def notify_pole_emploi(self) -> api_enums.PEApiNotificationStatus:
        # We do not send approvals that start in the future to PE, because their IS can't handle them.
        # In this case, do not mark them as "should retry" but leave them pending. The pending ones
        # will be caught by the second pass cron. The "should retry" then assumes:
        # - the approval was ready to be sent (user OK, dates OK)
        # - we had an actual issue.
        now = timezone.now()
        today = timezone.localdate(now)
        if self.start_at > today:
            self.pe_log_err("start_at={} starts after today={}", self.start_at, today)
            return self.pe_save_pending(
                now,
                reason=api_enums.PEApiPreliminaryCheckFailureReason.STARTS_IN_FUTURE,
            )

        sender_kind = self.origin_sender_kind
        prescriber_organization_kind = self.origin_prescriber_organization_kind
        siae_siret = self.origin_siae_siret
        siae_kind = self.origin_siae_kind
        if not all((sender_kind, siae_siret, siae_kind)):
            job_application = self.jobapplication_set.accepted().order_by("-created_at").first()
            if not job_application:
                self.pe_log_err("had no accepted job application")
                return self.pe_save_pending(
                    now,
                    reason=api_enums.PEApiPreliminaryCheckFailureReason.NO_JOB_APPLICATION,
                )

            siae_siret = job_application.to_company.siret
            siae_kind = job_application.to_company.kind
            sender_kind = job_application.sender_kind
            if prescriber_org := job_application.sender_prescriber_organization:
                prescriber_organization_kind = prescriber_org.kind

        type_siae = companies_enums.siae_kind_to_ft_type_siae(siae_kind)
        if not type_siae:
            self.pe_log_err("could not find PE type for siae_siret={} siae_kind={}", siae_siret, siae_kind)
            return self.pe_save_error(
                now,
                endpoint=None,
                exit_code=api_enums.PEApiPreliminaryCheckFailureReason.INVALID_SIAE_KIND,
            )

        if not all(
            [
                self.user.first_name,
                self.user.last_name,
                self.user.jobseeker_profile.nir,
                self.user.jobseeker_profile.birthdate,
            ]
        ):
            self.pe_log_err("had an invalid user={} nir={}", self.user, self.user.jobseeker_profile.nir)
            # we save those as pending since the cron will ignore those cases anyway and thus has
            # no chance to block itself.
            return self.pe_save_pending(
                now,
                reason=api_enums.PEApiPreliminaryCheckFailureReason.MISSING_USER_DATA,
            )

        if not self.user.jobseeker_profile.pe_obfuscated_nir:
            pe_client = pole_emploi_partenaire_api_client()
            try:
                id_national = pe_client.recherche_individu_certifie(
                    first_name=self.user.first_name,
                    last_name=self.user.last_name,
                    nir=self.user.jobseeker_profile.nir,
                    birthdate=self.user.jobseeker_profile.birthdate,
                )
            except PoleEmploiAPIException:
                self.pe_log_err("got a recoverable error in recherche_individu")
                return self.pe_save_should_retry(now)
            except PoleEmploiAPIBadResponse as exc:
                self.pe_log_err("got an unrecoverable error={} in recherche_individu", exc.response_code)
                return self.pe_save_error(
                    now, endpoint=api_enums.PEApiEndpoint.RECHERCHE_INDIVIDU, exit_code=exc.response_code
                )
            self.user.jobseeker_profile.pe_obfuscated_nir = id_national
            self.user.jobseeker_profile.pe_last_certification_attempt_at = timezone.now()
            IdentityCertification.objects.upsert_certifications(
                [
                    IdentityCertification(
                        certifier=IdentityCertificationAuthorities.API_FT_RECHERCHE_INDIVIDU_CERTIFIE,
                        jobseeker_profile=self.user.jobseeker_profile,
                        certified_at=now,
                    ),
                ]
            )
            self.user.jobseeker_profile.save(update_fields=["pe_obfuscated_nir", "pe_last_certification_attempt_at"])

        return self.pe_maj_pass(
            id_national_pe=self.user.jobseeker_profile.pe_obfuscated_nir,
            siae_siret=siae_siret,
            siae_kind=siae_kind,
            sender_kind=sender_kind,
            prescriber_kind=prescriber_organization_kind,
            at=now,
        )


class SuspensionQuerySet(models.QuerySet):
    @property
    def in_progress_lookup(self):
        today = timezone.localdate()
        return models.Q(start_at__lte=today, end_at__gte=today)

    def in_progress(self):
        return self.filter(self.in_progress_lookup)

    def not_in_progress(self):
        return self.exclude(self.in_progress_lookup)

    def old(self):
        return self.filter(end_at__lt=timezone.localdate())


class Suspension(models.Model):
    """
    A PASS IAE (or approval) issued by Itou can be directly suspended by an SIAE,
    without intervention of a prescriber or a posteriori control.

    When a suspension is saved/edited/deleted, the end date of its approval is
    automatically pushed back or forth with a PostgreSQL trigger:
    `trigger_update_approval_end_at`.
    """

    # Min duration: none.
    # Max duration: 36 months (could be adjusted according to user feedback).
    # 36-months suspensions can be consecutive and there can be any number of them.
    MAX_DURATION_MONTHS = 36
    # Temporary update for support team needs. operated on march. Target value should be 30.
    # More information on https://github.com/betagouv/itou/pull/1163
    MAX_RETROACTIVITY_DURATION_DAYS = 365

    class Reason(models.TextChoices):
        # Displayed choices
        SUSPENDED_CONTRACT = (
            "CONTRACT_SUSPENDED",
            "Contrat de travail suspendu depuis plus de 15 jours",
        )
        BROKEN_CONTRACT = "CONTRACT_BROKEN", "Contrat de travail rompu"
        FINISHED_CONTRACT = "FINISHED_CONTRACT", "Contrat de travail terminé"
        APPROVAL_BETWEEN_CTA_MEMBERS = (
            "APPROVAL_BETWEEN_CTA_MEMBERS",
            "Situation faisant l'objet d'un accord entre les acteurs membres du CTA (Comité technique d'animation)",
        )
        # The following choice must only be available for EI and ACI SIAE kinds
        CONTRAT_PASSERELLE = (
            "CONTRAT_PASSERELLE",
            "Bascule dans l'expérimentation contrat passerelle",
        )

        # Old reasons kept for history. See cls.displayed_choices
        SICKNESS = "SICKNESS", "Arrêt pour longue maladie"
        MATERNITY = "MATERNITY", "Congé de maternité"
        INCARCERATION = "INCARCERATION", "Incarcération"
        TRIAL_OUTSIDE_IAE = (
            "TRIAL_OUTSIDE_IAE",
            "Période d'essai auprès d'un employeur ne relevant pas de l'insertion par l'activité économique",
        )
        DETOXIFICATION = "DETOXIFICATION", "Période de cure pour désintoxication"
        FORCE_MAJEURE = (
            "FORCE_MAJEURE",
            (
                "Raison de force majeure conduisant le salarié à quitter son emploi ou toute autre "
                "situation faisant l'objet d'un accord entre les acteurs membres du CTA"
            ),
        )

        @staticmethod
        def displayed_choices_for_siae(siae):
            """
            Old reasons are not showed anymore but kept to let users still see
            a nice label in their dashboard instead of just the enum stored in the DB.
            If the given SIAE is an ACI or EI, it can now use the 'CONTRAT_PASSERELLE' suspension reason.
            """
            reasons = [
                Suspension.Reason.SUSPENDED_CONTRACT,
                Suspension.Reason.BROKEN_CONTRACT,
                Suspension.Reason.FINISHED_CONTRACT,
                Suspension.Reason.APPROVAL_BETWEEN_CTA_MEMBERS,
            ]
            if siae.kind in [companies_enums.CompanyKind.ACI, companies_enums.CompanyKind.EI]:
                reasons.append(Suspension.Reason.CONTRAT_PASSERELLE)
            return [(reason.value, reason.label) for reason in reasons]

    REASONS_ALLOWING_UNSUSPEND = [
        Reason.BROKEN_CONTRACT.value,
        Reason.FINISHED_CONTRACT.value,
        Reason.APPROVAL_BETWEEN_CTA_MEMBERS.value,
        Reason.CONTRAT_PASSERELLE.value,
        Reason.SUSPENDED_CONTRACT.value,
    ]

    approval = models.ForeignKey(Approval, verbose_name="PASS IAE", on_delete=models.CASCADE)
    start_at = models.DateField(verbose_name="date de début", default=timezone.localdate, db_index=True)
    end_at = models.DateField(verbose_name="date de fin", default=timezone.localdate, db_index=True)
    siae = models.ForeignKey(
        "companies.Company",
        verbose_name="SIAE",
        null=True,
        on_delete=models.RESTRICT,  # Prevent a soft lock, also for traceability and accountability
        related_name="approvals_suspended",
    )
    reason = models.CharField(
        verbose_name="motif",
        max_length=30,
        choices=Reason.choices,
        default=Reason.SUSPENDED_CONTRACT,
    )
    reason_explanation = models.TextField(verbose_name="explications supplémentaires", blank=True)
    created_at = models.DateTimeField(verbose_name="date de création", default=timezone.now)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="créé par",
        null=True,
        on_delete=models.RESTRICT,  # For traceability and accountability
        related_name="approvals_suspended_set",
    )
    updated_at = models.DateTimeField(verbose_name="date de modification", auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="mis à jour par",
        null=True,
        blank=True,
        on_delete=models.RESTRICT,  # For traceability and accountability, the dates can be edited
    )

    objects = SuspensionQuerySet.as_manager()

    class Meta:
        verbose_name = "suspension"
        ordering = ["-start_at"]
        # Use an exclusion constraint to prevent overlapping date ranges.
        # This requires the btree_gist extension on PostgreSQL.
        # See "Tip of the Week" https://postgresweekly.com/issues/289
        # https://docs.djangoproject.com/en/3.1/ref/contrib/postgres/constraints/
        constraints = [
            ExclusionConstraint(
                name="exclude_overlapping_suspensions",
                expressions=(
                    ("approval", RangeOperators.EQUAL),
                    (
                        DateRange(
                            "start_at",
                            "end_at",
                            RangeBoundary(inclusive_lower=True, inclusive_upper=True),
                        ),
                        RangeOperators.OVERLAPS,
                    ),
                ),
                violation_error_message="La période chevauche une suspension existante pour ce PASS IAE.",
            ),
            models.CheckConstraint(
                condition=Q(start_at__lte=TruncDate(Now())),
                name="%(class)s_cannot_start_in_the_future",
            ),
        ]
        triggers = [
            pgtrigger.Trigger(
                name="update_approval_end_at",
                when=pgtrigger.After,
                operation=pgtrigger.Insert | pgtrigger.Update | pgtrigger.Delete,
                func="""
                    --
                    -- When a suspension is inserted/updated/deleted, the end date
                    -- of its approval is automatically pushed back or forth.
                    --
                    -- See:
                    -- https://www.postgresql.org/docs/12/triggers.html
                    -- https://www.postgresql.org/docs/12/plpgsql-trigger.html#PLPGSQL-TRIGGER-AUDIT-EXAMPLE
                    --
                    IF (TG_OP = 'DELETE') THEN
                        -- At delete time, the approval's end date is pushed back.
                        UPDATE approvals_approval
                        SET end_at = end_at - (OLD.end_at - OLD.start_at), updated_at=NOW()
                        WHERE id = OLD.approval_id;
                    ELSIF (TG_OP = 'INSERT') THEN
                        -- At insert time, the approval's end date is pushed forward.
                        UPDATE approvals_approval
                        SET end_at = end_at + (NEW.end_at - NEW.start_at), updated_at=NOW()
                        WHERE id = NEW.approval_id;
                    ELSIF (TG_OP = 'UPDATE') THEN
                        -- At update time, the approval's end date is first reset before
                        -- being pushed forward, e.g.:
                        --     * step 1 "create new 90 days suspension":
                        --         * extend approval: approval.end_date + 90 days
                        --     * step 2 "edit 60 days instead of 90 days":
                        --         * reset approval: approval.end_date - 90 days
                        --         * extend approval: approval.end_date + 60 days
                        UPDATE approvals_approval
                        SET
                          end_at = end_at - (OLD.end_at - OLD.start_at) + (NEW.end_at - NEW.start_at),
                          updated_at=NOW()
                        WHERE id = NEW.approval_id;
                    END IF;
                    RETURN NULL;
                """,
            ),
        ]

    def __str__(self):
        return f"{self.pk} {self.start_at:%d/%m/%Y} - {self.end_at:%d/%m/%Y} [{self.approval.number}]"

    def clean(self):
        if self.reason == self.Reason.FORCE_MAJEURE and not self.reason_explanation:
            raise ValidationError({"reason_explanation": "En cas de force majeure, veuillez préciser le motif."})

        # This can happen in forms when no default/end date is entered
        if not self.end_at:
            raise ValidationError({"end_at": "La date de fin de la suspension est obligatoire."})

        # No min duration: a suspension may last only 1 day.
        if self.end_at < self.start_at:
            raise ValidationError({"end_at": "La date de fin doit être postérieure à la date de début."})

        # A suspension cannot exceed max duration.
        max_end_at = self.get_max_end_at(self.start_at)
        if self.end_at > max_end_at:
            raise ValidationError(
                {
                    "end_at": (
                        f"La durée totale ne peut excéder {self.MAX_DURATION_MONTHS} mois. "
                        f"Date de fin maximum: {max_end_at:%d/%m/%Y}."
                    )
                }
            )

        # Don't compate to approval if not present : it crashes.
        if self.approval_id:
            # The start of a suspension must be contained in its approval boundaries.
            if not self.start_in_approval_boundaries:
                raise ValidationError(
                    {
                        "start_at": (
                            "La suspension ne peut pas commencer en dehors des limites du PASS IAE "
                            f"{self.approval.start_at:%d/%m/%Y} - {self.approval.end_at:%d/%m/%Y}."
                        )
                    }
                )

            referent_date = self.created_at.date() if self.pk else None
            next_min_start_at = self.next_min_start_at(self.approval, self.pk, referent_date)
            if next_min_start_at and self.start_at < next_min_start_at:
                raise ValidationError({"start_at": (f"La date de début minimum est : {next_min_start_at:%d/%m/%Y}.")})

    @property
    def duration(self):
        return self.end_at - self.start_at

    @property
    def is_in_progress(self):
        return self.start_at <= timezone.localdate() <= self.end_at

    @property
    def start_in_approval_boundaries(self):
        return self.approval.start_at <= self.start_at <= self.approval.end_at

    def can_be_handled_by_siae(self, siae):
        """
        Only the SIAE currently hiring the job seeker can handle a suspension.
        """
        cached_result = getattr(self, "_can_be_handled_by_siae_cache", None)
        if cached_result:
            return cached_result
        self._can_be_handled_by_siae_cache = self.is_in_progress and last_hire_was_made_by_siae(
            self.approval.user, siae
        )
        return self._can_be_handled_by_siae_cache

    @staticmethod
    def get_max_end_at(start_at):
        """
        Returns the maximum date on which a suspension can end.
        """
        return start_at + relativedelta(months=Suspension.MAX_DURATION_MONTHS) - relativedelta(days=1)

    @staticmethod
    def next_min_start_at(
        approval,
        pk_suspension=None,
        referent_date=None,
    ):
        """
        Returns the minimum date on which a suspension can begin.
        """
        if referent_date is None:
            referent_date = timezone.localdate()

        start_at = None
        last_accepted_job_application = get_user_last_accepted_siae_job_application(approval.user)
        if last_accepted_job_application:
            start_at = last_accepted_job_application.hiring_start_at

        # Start at overrides to handle edge cases.
        if last_old_suspension := approval.last_old_suspension(pk_suspension):
            start_at = last_old_suspension.end_at + relativedelta(days=1)

        start_at_threshold = referent_date - datetime.timedelta(days=Suspension.MAX_RETROACTIVITY_DURATION_DAYS)
        # At this point, `start_at` can be None if:
        # - hiring start date has not been filled in last accepted job application,
        # - there is no previous suspension for this approval.
        # Hence a more defensive approach.
        if not start_at or start_at < start_at_threshold:
            return start_at_threshold
        return start_at


class CommonProlongation(models.Model):
    """
    Stores a prolongation made by an SIAE for a PASS IAE.

    When a prolongation is saved/edited/deleted, the end date of its approval
    is automatically pushed back or forth with a PostgreSQL trigger:
    `update_approval_end_at`.
    """

    # Max duration: 10 years but it depends on the `reason` field, see `get_max_end_at`.
    MAX_DURATION = datetime.timedelta(days=10 * 365)

    PROLONGATION_RULES = {
        enums.ProlongationReason.SENIOR_CDI: {
            "max_duration": MAX_DURATION,
            "max_duration_label": "10 ans",
            "max_cumulative_duration": None,
            "help_text": (
                "Pour le CDI Inclusion, jusqu’à la retraite "
                "(pour des raisons techniques, une durée de 10 ans (3650 jours) est appliquée par défaut)."
            ),
        },
        enums.ProlongationReason.COMPLETE_TRAINING: {
            "max_duration": datetime.timedelta(days=365),
            "max_duration_label": "12 mois",
            "max_cumulative_duration": None,
            "help_text": mark_safe(
                "12 mois (365 jours) maximum pour chaque demande.<br> "
                "Renouvellements possibles jusqu’à la fin de l’action de formation."
            ),
        },
        enums.ProlongationReason.RQTH: {
            "max_duration": datetime.timedelta(days=365),
            "max_duration_label": "12 mois",
            "max_cumulative_duration": datetime.timedelta(days=3 * 365),
            "help_text": mark_safe(
                "12 mois (365 jours) maximum pour chaque demande.<br> "
                "Renouvellements possibles dans la limite de 5 ans de parcours IAE "
                "(2 ans de parcours initial + 3 ans (1095 jours))."
            ),
        },
        enums.ProlongationReason.SENIOR: {
            "max_duration": datetime.timedelta(days=365),
            "max_duration_label": "12 mois",
            "max_cumulative_duration": datetime.timedelta(days=5 * 365),
            "help_text": mark_safe(
                "12 mois (365 jours) maximum pour chaque demande.<br> "
                "Renouvellements possibles dans la limite de 7 ans de parcours IAE "
                "(2 ans de parcours initial + 5 ans (1825 jours))."
            ),
        },
        enums.ProlongationReason.PARTICULAR_DIFFICULTIES: {
            "max_duration": datetime.timedelta(days=365),
            "max_duration_label": "12 mois",
            "max_cumulative_duration": datetime.timedelta(days=3 * 365),
            "help_text": mark_safe(
                "12 mois (365 jours) maximum pour chaque demande.<br> "
                "Renouvellements possibles dans la limite de 5 ans de parcours IAE "
                "(2 ans de parcours initial + 3 ans (1095 jours))."
            ),
        },
        enums.ProlongationReason.HEALTH_CONTEXT: {
            "max_duration": datetime.timedelta(days=365),
            "max_duration_label": "12 mois",
            "max_cumulative_duration": datetime.timedelta(days=365),
            "help_text": "NE PAS UTILISER",  # This value shouldn't appear anywhere but just in case
        },
    }

    REASONS_NOT_NEED_PRESCRIBER_OPINION = (
        enums.ProlongationReason.SENIOR_CDI,
        enums.ProlongationReason.COMPLETE_TRAINING,
    )

    approval = models.ForeignKey(Approval, verbose_name="PASS IAE", on_delete=models.CASCADE)
    start_at = models.DateField(verbose_name="date de début", default=timezone.localdate, db_index=True)
    end_at = models.DateField(verbose_name="date de fin", default=timezone.localdate, db_index=True)
    reason = models.CharField(
        verbose_name="motif",
        max_length=30,
        choices=enums.ProlongationReason.choices,
        default=enums.ProlongationReason.COMPLETE_TRAINING,
    )
    reason_explanation = models.TextField(verbose_name="explications supplémentaires", blank=True)

    declared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="déclarée par",
        null=True,
        on_delete=models.RESTRICT,  # For traceability and accountability
        related_name="%(class)ss_declared",
    )
    declared_by_siae = models.ForeignKey(
        "companies.Company",
        verbose_name="SIAE du déclarant",
        null=True,
        on_delete=models.RESTRICT,  # For traceability and accountability, people's organization can change
    )

    # It is assumed that an authorized prescriber has validated the prolongation beforehand.
    validated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="prescripteur habilité qui a autorisé cette prolongation",
        null=True,
        blank=True,
        on_delete=models.RESTRICT,  # For traceability and accountability
        related_name="%(class)ss_validated",
    )

    prescriber_organization = models.ForeignKey(
        "prescribers.PrescriberOrganization",
        verbose_name="organisation du prescripteur habilité",
        null=True,
        blank=True,
        on_delete=models.RESTRICT,  # For traceability and accountability, people's organization can change
    )

    # `created_by` can be different from `declared_by` when created in admin.
    created_at = models.DateTimeField(verbose_name="date de création", default=timezone.now)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="créé par",
        null=True,
        on_delete=models.RESTRICT,  # For traceability and accountability
        related_name="%(class)ss_created",
    )
    updated_at = models.DateTimeField(verbose_name="date de modification", auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="modifié par",
        null=True,
        blank=True,
        on_delete=models.RESTRICT,  # For traceability and accountability
        related_name="%(class)ss_updated",
    )

    # FIXME(rsebille): Those fields should only be used in ProlongationRequest(), but they are currently used by
    #  Prolongation() so keeping them here (while we move to the new process) to not break everything.
    # Optional fields needed for specific `reason` field values
    report_file = models.OneToOneField(
        File,
        verbose_name="fichier bilan",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    require_phone_interview = models.BooleanField(
        verbose_name="demande d'entretien téléphonique",
        default=False,
        blank=True,
    )
    contact_email = models.EmailField(
        verbose_name="e-mail de contact",
        blank=True,
    )
    contact_phone = models.CharField(
        verbose_name="numéro de téléphone de contact",
        max_length=20,
        blank=True,
    )

    class Meta:
        abstract = True
        constraints = [
            # Report file is not yet defined as mandatory for these reasons. May change though
            models.CheckConstraint(
                name="check_%(class)s_reason_and_report_file_coherence",
                violation_error_message="Incohérence entre le fichier de bilan et la raison de prolongation",
                # Must keep compatibility with old prolongations without report file
                condition=Q(report_file=None)
                | Q(report_file__isnull=False, reason__in=PROLONGATION_REPORT_FILE_REASONS),
            ),
        ]

    def __str__(self):
        return f"{self.pk} {self.start_at:%d/%m/%Y} - {self.end_at:%d/%m/%Y} [{self.approval.number}]"

    def clean(self):
        if not self.end_at:
            # Model.clean() is called by ModelForm.clean(), even if the form is invalid.
            return

        # Min duration == 1 day.
        if self.duration < datetime.timedelta(days=1):
            raise ValidationError({"end_at": "La durée minimale doit être d'au moins un jour."})

        # A prolongation cannot exceed max duration.
        max_end_at = self.get_max_end_at(self.approval_id, self.start_at, self.reason, ignore=[self.pk])
        if self.end_at > max_end_at:
            raise ValidationError(
                {
                    "end_at": (
                        f"La durée totale est trop longue pour le motif « {self.get_reason_display()} ». "
                        f"Date de fin maximum : {max_end_at:%d/%m/%Y}."
                    )
                }
            )

        if self.reason == enums.ProlongationReason.PARTICULAR_DIFFICULTIES.value:
            if not self.declared_by_siae or self.declared_by_siae.kind not in [
                companies_enums.CompanyKind.AI,
                companies_enums.CompanyKind.ACI,
            ]:
                raise ValidationError(f"Le motif « {self.get_reason_display()} » est réservé aux AI et ACI.")

        if (
            hasattr(self, "validated_by")
            and self.validated_by
            and not self.validated_by.is_prescriber_with_authorized_org_memberships
        ):
            raise ValidationError("Cet utilisateur n'est pas un prescripteur habilité.")

        # Avoid blocking updates in admin by limiting this check to only new instances.
        if not self.pk and self.start_at != self.approval.end_at:
            raise ValidationError(
                "La date de début doit être la même que la date de fin du PASS IAE "
                f"« {self.approval.end_at:%d/%m/%Y} »."
            )

        # Contact fields coherence: can't use constraints on these ones
        if self.reason in PROLONGATION_REPORT_FILE_REASONS:
            if self.require_phone_interview and not (self.contact_email and self.contact_phone):
                raise ValidationError("L'adresse email et le numéro de téléphone sont obligatoires pour ce motif")
        elif any([self.require_phone_interview, self.contact_email, self.contact_phone]):
            raise ValidationError("L'adresse email et le numéro de téléphone ne peuvent être saisis pour ce motif")

        # declared_by and declared_by_siae coherence
        if self.declared_by and not self.declared_by_siae.members.filter(pk=self.declared_by.pk).exists():
            raise ValidationError(
                "Le déclarant doit être un membre de la SIAE du déclarant. "
                f"Déclarant: {self.declared_by_id}, SIAE: {self.declared_by_siae_id}."
            )

    def notify_authorized_prescriber(self):
        pass  # NOOP

    @property
    def duration(self):
        return self.end_at - self.start_at

    @property
    def is_in_progress(self):
        return self.start_at <= timezone.localdate() <= self.end_at

    @staticmethod
    def get_max_end_at(approval_id, start_at, reason, ignore=None):
        """
        Returns the maximum date on which a prolongation can end.
        """
        max_cumulative_duration = Prolongation.PROLONGATION_RULES[reason]["max_cumulative_duration"]
        if max_cumulative_duration is None:
            return start_at + Prolongation.PROLONGATION_RULES[reason]["max_duration"]
        used = Prolongation.objects.get_cumulative_duration_for(approval_id, ignore=ignore)
        remaining_days = max_cumulative_duration - used
        return start_at + remaining_days


class ProlongationRequest(CommonProlongation):
    status = models.CharField(
        verbose_name="statut",
        choices=enums.ProlongationRequestStatus.choices,
        default=enums.ProlongationRequestStatus.PENDING,
        max_length=32,
    )

    processed_at = models.DateTimeField(verbose_name="date de traitement", null=True, blank=True)
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="traité par",
        on_delete=models.RESTRICT,  # For traceability and accountability
        related_name="%(class)s_processed",
        null=True,
        blank=True,
    )

    reminder_sent_at = models.DateTimeField(verbose_name="rappel envoyé le", null=True, editable=False)

    class Meta(CommonProlongation.Meta):
        verbose_name = "demande de prolongation"
        verbose_name_plural = "demandes de prolongation"
        ordering = ["-created_at"]
        constraints = CommonProlongation.Meta.constraints + [
            # Phone and email are mandatory when the interview is required
            models.CheckConstraint(
                name="check_%(class)s_require_phone_interview",
                condition=Q(require_phone_interview=False) | Q(~Q(contact_email=""), ~Q(contact_phone="")),
            ),
            # Approvals can only have 1 PENDING request
            models.UniqueConstraint(
                name="unique_%(class)s_approval_for_pending",
                fields=["approval"],
                condition=Q(status=enums.ProlongationRequestStatus.PENDING),
                violation_error_message="Une demande de prolongation à traiter existe déjà pour ce PASS IAE",
            ),
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        field = self._meta.get_field("validated_by")
        field.verbose_name = "prescripteur habilité qui a reçu la demande de prolongation"

    def __str__(self):
        return f"{self.approval} — {self.get_status_display()} — {self.start_at:%d/%m/%Y} - {self.end_at:%d/%m/%Y}"

    def notify_authorized_prescriber(self):
        notifications.ProlongationRequestCreatedForPrescriberNotification(
            self.validated_by, self.prescriber_organization, prolongation_request=self
        ).send()

    def grant(self, user):
        self.status = enums.ProlongationRequestStatus.GRANTED
        self.processed_by = user
        self.processed_at = timezone.now()
        self.updated_by = user
        prolongation = Prolongation.from_prolongation_request(self)

        with transaction.atomic():  # Not relying on global settings as those two objects *must* be saved together.
            prolongation.save()
            self.save()

        notifications.ProlongationRequestGrantedForEmployerNotification(
            self.declared_by,
            self.declared_by_siae,
            prolongation_request=self,
        ).send()
        notifications.ProlongationRequestGrantedForJobSeekerNotification(
            self.approval.user,
            prolongation_request=self,
        ).send()

        return prolongation

    def deny(self, user, information):
        self.status = enums.ProlongationRequestStatus.DENIED
        self.processed_by = user
        self.processed_at = timezone.now()
        self.updated_by = user
        information.request = self

        with transaction.atomic():
            information.save()
            self.save()

        notifications.ProlongationRequestDeniedForEmployerNotification(
            self.declared_by, self.declared_by_siae, prolongation_request=self
        ).send()
        notifications.ProlongationRequestDeniedForJobSeekerNotification(
            self.approval.user, prolongation_request=self
        ).send()


class ProlongationRequestDenyInformation(models.Model):
    request = models.OneToOneField(ProlongationRequest, related_name="deny_information", on_delete=models.CASCADE)
    reason = models.CharField(
        verbose_name="motif de refus",
        choices=enums.ProlongationRequestDenyReason.choices,
    )
    reason_explanation = models.TextField(verbose_name="explications du motif de refus")

    proposed_actions = ArrayField(
        verbose_name="actions envisagées",
        base_field=models.CharField(choices=enums.ProlongationRequestDenyProposedAction.choices),
        null=True,
        blank=True,
    )
    proposed_actions_explanation = models.TextField(verbose_name="explications des actions envisagées", blank=True)

    created_at = models.DateTimeField(verbose_name="date de création", default=timezone.now)
    updated_at = models.DateTimeField(verbose_name="date de modification", auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                name="non_empty_proposed_actions",
                condition=~models.Q(proposed_actions__len=0),
                violation_error_message="Les actions envisagées ne peuvent pas être vide",
            ),
        ]

    def get_proposed_actions_display(self):
        if not self.proposed_actions:
            return []
        return [
            enums.ProlongationRequestDenyProposedAction(proposed_action).label
            for proposed_action in self.proposed_actions
        ]


class ProlongationQuerySet(models.QuerySet):
    @property
    def in_progress_lookup(self):
        # This logic was duplicated in Approval.is_suspended for performance issues
        today = timezone.localdate()
        return models.Q(start_at__lte=today, end_at__gte=today)

    def in_progress(self):
        return self.filter(self.in_progress_lookup)

    def not_in_progress(self):
        return self.exclude(self.in_progress_lookup)


class ProlongationManager(models.Manager):
    def get_cumulative_duration_for(self, approval_id, ignore=None):
        duration = datetime.timedelta(0)
        for prolongation in self.filter(approval_id=approval_id).exclude(pk__in=ignore or []):
            duration += prolongation.duration
        return duration


class Prolongation(CommonProlongation):
    request = models.OneToOneField(
        ProlongationRequest,
        verbose_name="demande de prolongation",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )

    objects = ProlongationManager.from_queryset(ProlongationQuerySet)()

    class Meta(CommonProlongation.Meta):
        verbose_name = "prolongation"
        ordering = ["-start_at"]
        constraints = CommonProlongation.Meta.constraints + [
            # Use an exclusion constraint to prevent overlapping date ranges.
            # This requires the btree_gist extension on PostgreSQL.
            # See "Tip of the Week" https://postgresweekly.com/issues/289
            # https://docs.djangoproject.com/en/3.1/ref/contrib/postgres/constraints/
            ExclusionConstraint(
                name="exclude_%(class)s_overlapping_dates",
                expressions=(
                    ("approval", RangeOperators.EQUAL),
                    (
                        # [start_at, end_at) (inclusive start, exclusive end).
                        # For prolongations: upper bound of preceding interval is the lower bound of the next.
                        DateRange(
                            "start_at",
                            "end_at",
                            RangeBoundary(inclusive_lower=True, inclusive_upper=False),
                        ),
                        RangeOperators.OVERLAPS,
                    ),
                ),
                violation_error_message="La période chevauche une prolongation existante pour ce PASS IAE.",
            ),
        ]
        triggers = [
            pgtrigger.Trigger(
                name="update_approval_end_at",
                when=pgtrigger.After,
                operation=pgtrigger.Insert | pgtrigger.Update | pgtrigger.Delete,
                func="""
                    --
                    -- When a prolongation is inserted/updated/deleted, the end date
                    -- of its approval is automatically pushed back or forth.
                    --
                    -- See:
                    -- https://www.postgresql.org/docs/12/triggers.html
                    -- https://www.postgresql.org/docs/12/plpgsql-trigger.html#PLPGSQL-TRIGGER-AUDIT-EXAMPLE
                    --
                    IF (TG_OP = 'DELETE') THEN
                        -- At delete time, the approval's end date is pushed back if the prolongation
                        -- was validated.
                        UPDATE approvals_approval
                        SET end_at = end_at - (OLD.end_at - OLD.start_at), updated_at=NOW()
                        WHERE id = OLD.approval_id;
                    ELSIF (TG_OP = 'INSERT') THEN
                        -- At insert time, the approval's end date is pushed forward if the prolongation
                        -- is validated.
                        UPDATE approvals_approval
                        SET end_at = end_at + (NEW.end_at - NEW.start_at), updated_at=NOW()
                        WHERE id = NEW.approval_id;
                    ELSIF (TG_OP = 'UPDATE') THEN
                        -- At update time, the approval's end date is first reset before
                        -- being pushed forward.
                        UPDATE approvals_approval
                        SET
                          end_at = end_at - (OLD.end_at - OLD.start_at) + (NEW.end_at - NEW.start_at),
                          updated_at=NOW()
                        WHERE id = NEW.approval_id;
                    END IF;
                    RETURN NULL;
                """,
            ),
        ]

    @classmethod
    def from_prolongation_request(cls, prolongation_request):
        fields_to_copy = {
            "approval",
            "start_at",
            "end_at",
            "reason",
            "reason_explanation",
            "declared_by",
            "declared_by_siae",
            "prescriber_organization",
            "created_by",
            "report_file",
            "require_phone_interview",
            "contact_email",
            "contact_phone",
        }

        obj = cls()
        obj.request = prolongation_request
        for field in fields_to_copy:
            setattr(obj, field, getattr(prolongation_request, field))
        # The user granting the request can be different from the one that was ask to
        obj.validated_by = prolongation_request.processed_by

        return obj


class PoleEmploiApprovalManager(models.Manager):
    def get_import_dates(self):
        """
        Return a list of import dates.
        [
            datetime.date(2020, 2, 23),
            datetime.date(2020, 4, 8),
            …
        ]

        It used to be used in the admin but it slowed it down.
        It's still used from time to time in django-admin shell.
        """
        return list(
            self
            # Remove default `Meta.ordering` to avoid an extra field being added to the GROUP BY clause.
            .order_by()
            .annotate(import_date=TruncDate("created_at"))
            .values_list("import_date", flat=True)
            .annotate(c=Count("id"))
        )

    def find_for(self, user):
        """
        Find existing Pôle emploi's approvals for the given user.

        We were told to check on `first_name` + `last_name` + `birthdate`
        but it's far from ideal:

        - the character encoding format is different between databases
        - there are no accents in the PE database
            => `format_name_as_pole_emploi()` is required to harmonize the formats
        - input errors in names are possible on both sides
        - there can be an inversion of first and last name fields
        - imported data can be poorly structured (first and last names in the same field)

        In many cases, we can identify the user based on its NIR number, when the PoleEmploiApproval
        has this information (which is the case 90% of the time) and we also have it.

        We'll also return the PE Approvals based on the combination of `pole_emploi_id`
        (non-unique but it is assumed that every job seeker knows his number) and `birthdate`.

        Their input formats can be checked to limit the risk of errors.
        """
        filters = []
        if user.jobseeker_profile.nir:
            # Allow duplicated NIR within PE approvals, but that will most probably change with the
            # ApprovalsWrapper code revamp later on. For now there is no unicity constraint on this column.
            filters.append(Q(nir=user.jobseeker_profile.nir))
        if user.jobseeker_profile.pole_emploi_id and user.jobseeker_profile.birthdate:
            filters.append(
                Q(pole_emploi_id=user.jobseeker_profile.pole_emploi_id, birthdate=user.jobseeker_profile.birthdate)
            )
        if not filters:
            return self.none()
        return self.filter(or_queries(filters)).order_by("-start_at", "-number")


class PoleEmploiApproval(PENotificationMixin, CommonApprovalMixin):
    """
    Store consolidated approvals (`agréments` in French) delivered by Pôle emploi.

    Two approval's delivering systems co-exist. Pôle emploi's approvals
    are issued in parallel.

    Thus, before Itou can deliver an approval, we have to check this table
    to ensure that there isn't already a valid Pôle emploi's approval.

    This table was populated and updated through the `import_pe_approvals`
    admin command on a regular basis with data shared by Pôle emploi.

    If a valid Pôle emploi's approval is found, it's copied in the `Approval`
    at the time of issuance. See Approval model's code for more information.
    """

    # Matches prescriber_organization.code_safir_pole_emploi.
    pe_structure_code = models.CharField("code structure France Travail", max_length=5)

    # - first 5 digits = code SAFIR of the PE agency of the consultant creating the approval
    # - next 2 digits = 2-digit year of delivery
    # - next 5 digits = decision number with autonomous increment per PE agency, e.g.: 75631 14 10001
    #     - decisions are starting with 1
    #     - decisions starting with 0 are reserved for "Reprise des décisions", e.g.: 75631 14 00001
    number = models.CharField(verbose_name="numéro", max_length=12, unique=True)

    pole_emploi_id = models.CharField("identifiant France Travail", max_length=8)
    first_name = models.CharField("prénom", max_length=150)
    last_name = models.CharField("nom", max_length=150)
    birth_name = models.CharField("nom de naissance", max_length=150)
    birthdate = models.DateField(verbose_name="date de naissance", default=timezone.localdate)
    nir = models.CharField(verbose_name="NIR", max_length=15, null=True, blank=True)
    # Some people have no NIR. They can have a temporary NIA or NTT instead:
    # https://www.net-entreprises.fr/astuces/identification-des-salaries%E2%80%AF-nir-nia-et-ntt/
    # NTT max length = 40 chars, max duration = 3 months
    ntt_nia = models.CharField(verbose_name="NTT ou NIA", max_length=40, null=True, blank=True)

    siae_siret = models.CharField(
        verbose_name="siret de la SIAE",
        max_length=14,
        validators=[validate_siret],
        null=True,
        blank=True,
    )
    siae_kind = models.CharField(
        verbose_name="type de la SIAE",
        max_length=6,
        choices=companies_enums.CompanyKind.choices,
        null=True,
        blank=True,
    )

    objects = PoleEmploiApprovalManager.from_queryset(CommonApprovalQuerySet)()

    class Meta:
        verbose_name = "agrément Pôle emploi"
        verbose_name_plural = "agréments Pôle emploi"
        ordering = ["-start_at"]
        indexes = [
            models.Index(fields=["nir"], name="nir_idx"),
            models.Index(fields=["pole_emploi_id", "birthdate"], name="pe_id_and_birthdate_idx"),
        ]

    def __str__(self):
        return self.number

    @staticmethod
    def format_name_as_pole_emploi(name):
        """
        Format `name` in the same way as it is in the Pôle emploi export file:
        Upper-case ASCII transliterations of Unicode text.
        """
        return unidecode(name.strip()).upper()

    @property
    def number_with_spaces(self):
        return f"{self.number[:5]} {self.number[5:7]} {self.number[7:]}"

    def notify_pole_emploi(self) -> api_enums.PEApiNotificationStatus:
        now = timezone.now()

        pe_client = pole_emploi_partenaire_api_client()
        try:
            id_national = pe_client.recherche_individu_certifie(
                first_name=self.first_name,
                last_name=self.last_name,
                birthdate=self.birthdate,
                nir=self.nir,
            )
        except PoleEmploiAPIException:
            self.pe_log_err("got a recoverable error in recherche_individu")
            return self.pe_save_should_retry(now)
        except PoleEmploiAPIBadResponse as exc:
            self.pe_log_err("got an unrecoverable error={} in recherche_individu", exc.response_code)
            return self.pe_save_error(
                now, endpoint=api_enums.PEApiEndpoint.RECHERCHE_INDIVIDU, exit_code=exc.response_code
            )

        return self.pe_maj_pass(
            id_national_pe=id_national,
            siae_siret=self.siae_siret,
            siae_kind=self.siae_kind,
            sender_kind=job_application_enums.SenderKind.PRESCRIBER,
            prescriber_kind=prescribers_enums.PrescriberOrganizationKind.FT,
            at=now,
        )


class OriginalPoleEmploiApproval(CommonApprovalMixin):
    """
    This table contains the original, "unmerged" PEApprovals: in particular it may have
    several lines for a single person, one being actually a suspension, others an Approval
    and some others, a prolongation.

    The merged PE Approvals that we generated are present in the "PoleEmploiApproval" model and
    have been merged using a one-time command (merge_pe_approvals) on March 18th, 2022.

    This table is kept for reference and historical reasons. It does not contain any import
    later than March 18th, 2022; in particular the one that has been done on March 30th 2022
    only has been made to the PoleEmploiApproval table.
    """

    # The normal length of a number is 12 chars.
    # Sometimes the number ends with an extension ('A01', 'E02', 'P03', 'S04' etc.) that
    # increases the length to 15 chars.
    # Suffixes meaning in French:
    class Suffix(models.TextChoices):
        # `P`: Prolongation = la personne a besoin d'encore quelques mois
        P = "prolongation", "Prolongation"
        # `E`: Extension = la personne est passée d'une structure à une autre
        E = "extension", "Extension"
        # `A`: Interruption = la personne ne s'est pas présentée
        A = "interruption", "Interruption"
        # `S`: Suspension = creux pendant la période justifié dans un cadre légal (incarcération, arrêt maladie etc.)
        S = "suspension", "Suspension"

    # All those fields are copied from PoleEmploiApproval
    pe_structure_code = models.CharField("code structure France Travail", max_length=5)

    # Parts of an "original" PE Approval number:
    #     - first 5 digits = code SAFIR of the PE agency of the consultant creating the approval
    #     - next 2 digits = 2-digit year of delivery
    #     - next 5 digits = decision number with autonomous increment per PE agency, e.g.: 75631 14 10001
    #         - decisions are starting with 1
    #         - decisions starting with 0 are reserved for "Reprise des décisions", e.g.: 75631 14 00001
    #     - next 3 chars (optional suffix) = status change, e.g.: 75631 14 10001 E01
    #         - first char = kind of amendment:
    #             - E for "Extension"
    #             - S for "Suspension"
    #             - P for "Prolongation"
    #             - A for "Interruption"
    #         - next 2 digits = refer to the act number (e.g. E02 = second extension)
    # An Approval number is not modifiable, there is a new entry for each new status change.
    # Suffixes are not taken into account in Itou.
    number = models.CharField(verbose_name="numéro", max_length=15, unique=True)

    pole_emploi_id = models.CharField("identifiant France Travail", max_length=8)
    first_name = models.CharField("prénom", max_length=150)
    last_name = models.CharField("nom", max_length=150)
    birth_name = models.CharField("nom de naissance", max_length=150)
    birthdate = models.DateField(verbose_name="date de naissance", default=timezone.localdate)
    nir = models.CharField(verbose_name="NIR", max_length=15, null=True, blank=True)
    ntt_nia = models.CharField(verbose_name="NTT ou NIA", max_length=40, null=True, blank=True)
    merged = models.BooleanField()

    class Meta:
        # the table name is misleading but is called "merged" for historical reasons.
        # actually, the table contains original, **unmerged** approvals (after tables were swapped
        # in production on March 18th, 2022)
        db_table = "merged_approvals_poleemploiapproval"
        verbose_name = "agrément Pôle emploi original"
        verbose_name_plural = "agréments Pôle emploi originaux"
        ordering = ["-start_at"]
        indexes = [
            models.Index(
                fields=["pole_emploi_id", "birthdate"],
                name="merged_pe_id_and_birthdate_idx",
            )
        ]
