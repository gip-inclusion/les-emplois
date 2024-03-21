import time
import uuid
from collections import Counter

from django.conf import settings
from django.contrib.auth.models import AbstractUser, UserManager
from django.contrib.postgres.fields import CIEmailField
from django.contrib.postgres.indexes import OpClass
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.core.validators import MinLengthValidator
from django.db import models
from django.db.models import Count, Max, OuterRef, Q, Subquery
from django.db.models.functions import Greatest, Upper
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.utils.functional import cached_property
from django.utils.safestring import mark_safe

from itou.approvals.enums import Origin
from itou.approvals.models import Approval, PoleEmploiApproval
from itou.asp.models import (
    AllocationDuration,
    Commune,
    Country,
    EducationLevel,
    EmployerType,
    LaneExtension,
    LaneType,
    RSAAllocation,
)
from itou.common_apps.address.departments import department_from_postcode
from itou.common_apps.address.format import format_address
from itou.common_apps.address.models import AddressMixin
from itou.companies.enums import CompanyKind
from itou.utils.models import UniqueConstraintWithErrorCode
from itou.utils.validators import validate_birthdate, validate_nir, validate_pole_emploi_id

from .enums import IdentityProvider, LackOfNIRReason, LackOfPoleEmploiId, Title, UserKind


class ApprovalAlreadyExistsError(Exception):
    pass


class ItouUserManager(UserManager):
    def get_duplicated_pole_emploi_ids(self):
        """
        Returns an array of `pole_emploi_id` used more than once:

            ['6666666A', '7777777B', '8888888C', '...']

        Performs this kind of SQL (with extra filters):

            select pole_emploi_id, count(*)
            from users_user
            group by pole_emploi_id, birthdate
            having count(*) > 1

        Used in the `deduplicate_job_seekers` management command.
        Implemented as a manager method to make unit testing easier.
        """
        return (
            self.values("jobseeker_profile__pole_emploi_id")
            .filter(kind=UserKind.JOB_SEEKER)
            # Skip empty `pole_emploi_id`.
            .exclude(jobseeker_profile__pole_emploi_id="")
            # Skip 31 cases where `00000000` was used as the `pole_emploi_id`.
            .exclude(jobseeker_profile__pole_emploi_id="00000000")
            # Group by.
            .values("jobseeker_profile__pole_emploi_id")
            .annotate(num_of_duplications=Count("jobseeker_profile__pole_emploi_id"))
            .filter(num_of_duplications__gt=1)
            .values_list("jobseeker_profile__pole_emploi_id", flat=True)
        )

    def get_duplicates_by_pole_emploi_id(self, prefetch_related_lookups=None):
        """
        Find duplicates with the same `pole_emploi_id` and `birthdate`
        and returns a dict:

            {
                '5589555S': [<User: a>, <User: b>],
                '7744222A': [<User: x>, <User: y>, <User: z>],
                ...
            }

        Used in the `deduplicate_job_seekers` management command.
        Implemented as a manager method to make unit testing easier.
        """
        users = self.select_related("jobseeker_profile").filter(
            jobseeker_profile__pole_emploi_id__in=self.get_duplicated_pole_emploi_ids()
        )
        if prefetch_related_lookups:
            users = users.prefetch_related(*prefetch_related_lookups)

        result = dict()
        for user in users:
            result.setdefault(user.jobseeker_profile.pole_emploi_id, []).append(user)

        pe_id_to_remove = []

        for pe_id, duplicates in result.items():
            same_birthdate = all(user.birthdate == duplicates[0].birthdate for user in duplicates)

            if not same_birthdate:
                # Two users with the same `pole_emploi_id` but a different
                # `birthdate` are not guaranteed to be duplicates.
                if len(duplicates) == 2:
                    pe_id_to_remove.append(pe_id)
                    continue

                # Keep only users with the same most common birthdate.
                list_of_birthdates = [u.birthdate for u in duplicates]
                c = Counter(list_of_birthdates)
                most_common_birthdate = c.most_common(1)[0][0]

                duplicates_with_same_birthdate = [u for u in duplicates if u.birthdate == most_common_birthdate]

                if len(duplicates_with_same_birthdate) == 1:
                    # We stop if there is only one user left.
                    pe_id_to_remove.append(pe_id)
                else:
                    result[pe_id] = duplicates_with_same_birthdate

        for pe_id in pe_id_to_remove:
            del result[pe_id]

        return result

    def job_seekers_with_last_activity(self):
        from itou.eligibility.models import EligibilityDiagnosis, GEIQEligibilityDiagnosis
        from itou.job_applications.models import JobApplication

        return self.filter(
            kind=UserKind.JOB_SEEKER,
        ).annotate(
            last_activity=Greatest(
                "date_joined",
                "last_login",
                Subquery(
                    JobApplication.objects.filter(job_seeker_id=OuterRef("pk"))
                    .values("job_seeker_id")
                    .annotate(last_updated_at=Max("updated_at"))
                    .values("last_updated_at")
                ),
                Subquery(
                    EligibilityDiagnosis.objects.filter(job_seeker_id=OuterRef("pk"))
                    .values("job_seeker_id")
                    .annotate(last_updated_at=Max("updated_at"))
                    .values("last_updated_at")
                ),
                Subquery(
                    GEIQEligibilityDiagnosis.objects.filter(job_seeker_id=OuterRef("pk"))
                    .values("job_seeker_id")
                    .annotate(last_updated_at=Max("updated_at"))
                    .values("last_updated_at")
                ),
            )
        )


class User(AbstractUser, AddressMixin):
    """
    Custom user model.

    Default fields are listed here:
    https://github.com/django/django/blob/f3901b5899d746dc5b754115d94ce9a045b4db0a/django/contrib/auth/models.py#L321

    Auth is managed with django-allauth.

    To retrieve SIAEs this user belongs to:
        self.company_set.all()
        self.companymembership_set.all()

    To retrieve prescribers this user belongs to:
        self.prescriberorganization_set.all()
        self.prescribermembership_set.all()


    The User model has a "companion" model in the `external_data` app,
    for third-party APIs data import concerns (class `JobSeekerExternalData`).

    At the moment, only users (job seekers) connected via PE Connect
    have external data stored.

    More details in `itou.external_data.models` module
    """

    ERROR_EMAIL_ALREADY_EXISTS = "Cet e-mail existe déjà."

    title = models.CharField(
        max_length=3,
        verbose_name="civilité",
        blank=True,
        default="",
        choices=Title.choices,
    )

    birthdate = models.DateField(
        verbose_name="date de naissance",
        null=True,
        blank=True,
        validators=[validate_birthdate],
    )
    email = CIEmailField(
        "adresse e-mail",
        db_index=True,
        # Empty values are stored as NULL if both `null=True` and `unique=True` are set.
        # This avoids unique constraint violations when saving multiple objects with blank values.
        null=True,
        unique=True,
    )
    phone = models.CharField(verbose_name="téléphone", max_length=20, blank=True)

    kind = models.CharField(max_length=20, verbose_name="type", choices=UserKind.choices, blank=False)

    identity_provider = models.CharField(
        max_length=20,
        verbose_name="fournisseur d'identité (SSO)",
        default=IdentityProvider.DJANGO,
        choices=IdentityProvider.choices,
    )

    has_completed_welcoming_tour = models.BooleanField(verbose_name="parcours de bienvenue effectué", default=False)

    created_by = models.ForeignKey(
        "self",
        verbose_name="créé par",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    external_data_source_history = models.JSONField(
        verbose_name="information sur la source des champs",
        blank=True,
        null=True,
        encoder=DjangoJSONEncoder,
    )

    last_checked_at = models.DateTimeField(verbose_name="date de dernière vérification", default=timezone.now)
    upcoming_deletion_notified_at = models.DateTimeField(
        verbose_name="date de notification d'une suppression prochaine",
        blank=True,
        null=True,
    )

    public_id = models.UUIDField(
        verbose_name="identifiant public opaque, pour les API",
        default=uuid.uuid4,
    )

    address_filled_at = models.DateTimeField(
        verbose_name="date de dernier remplissage de l'adresse",
        null=True,
        help_text="Mise à jour par autocomplétion de l'utilisateur",
    )

    objects = ItouUserManager()

    class Meta(AbstractUser.Meta):
        indexes = [
            models.Index(
                OpClass(Upper("email"), name="text_pattern_ops"),
                name="users_user_email_upper",
            )
        ]
        constraints = [
            models.CheckConstraint(
                name="staff_and_superusers",
                violation_error_message="Seul un utilisateur ITOU_STAFF peut avoir is_staff ou is_superuser de vrai.",
                check=models.Q(~models.Q(kind=UserKind.ITOU_STAFF) & models.Q(is_staff=False, is_superuser=False))
                | models.Q(kind=UserKind.ITOU_STAFF, is_staff=True),
            ),
            models.CheckConstraint(
                name="has_kind",
                violation_error_message="Le type d’utilisateur est incorrect.",
                check=(
                    models.Q(kind=UserKind.ITOU_STAFF)
                    | models.Q(kind=UserKind.JOB_SEEKER)
                    | models.Q(kind=UserKind.PRESCRIBER)
                    | models.Q(kind=UserKind.EMPLOYER)
                    | models.Q(kind=UserKind.LABOR_INSPECTOR)
                ),
            ),
        ]

    def __init__(self, *args, _auto_create_job_seeker_profile=True, **kwargs):
        super().__init__(*args, **kwargs)
        self._auto_create_job_seeker_profile = _auto_create_job_seeker_profile

    def __str__(self):
        return f"{self.get_full_name()} — {self.email}"

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        instance._old_values = dict(zip(field_names, values))
        return instance

    def has_data_changed(self, fields):
        if hasattr(self, "_old_values"):
            for field in fields:
                if getattr(self, field) != self._old_values[field]:
                    return True
        return False

    def validate_identity_provider(self):
        if self.identity_provider == IdentityProvider.FRANCE_CONNECT and self.kind != UserKind.JOB_SEEKER:
            raise ValidationError("France connect n'est utilisable que par un candidat.")

        if self.identity_provider == IdentityProvider.PE_CONNECT and self.kind != UserKind.JOB_SEEKER:
            raise ValidationError("PE connect n'est utilisable que par un candidat.")

        if self.identity_provider == IdentityProvider.INCLUSION_CONNECT and self.kind not in [
            UserKind.PRESCRIBER,
            UserKind.EMPLOYER,
        ]:
            raise ValidationError("Inclusion connect n'est utilisable que par un prescripteur ou employeur.")

    def save(self, *args, **kwargs):
        must_create_profile = self._state.adding and self._auto_create_job_seeker_profile

        # Update department from postal code (if possible).
        self.department = department_from_postcode(self.post_code)
        self.validate_unique()

        # Update is_staff with kind
        if self.kind == UserKind.ITOU_STAFF:
            self.is_staff = True
        elif self.kind in UserKind:
            # Any other user kind isn't staff
            self.is_staff = False

        self.validate_constraints()
        self.validate_identity_provider()

        super().save(*args, **kwargs)

        if self.is_job_seeker:
            if must_create_profile:
                JobSeekerProfile.objects.create(user=self)

            if self.has_data_changed(["birthdate", "last_name", "first_name"]):
                self.jobseeker_profile.pe_obfuscated_nir = None
                self.jobseeker_profile.pe_last_certification_attempt_at = None
                self.jobseeker_profile.save(update_fields=["pe_obfuscated_nir", "pe_last_certification_attempt_at"])

    def get_full_name(self):
        """
        Return the first_name plus the last_name, with a space in between.
        """
        full_name = "%s %s" % (self.first_name.strip().title(), self.last_name.upper())
        return full_name.strip()

    @property
    def is_job_seeker(self):
        return self.kind == UserKind.JOB_SEEKER

    @property
    def is_prescriber(self):
        return self.kind == UserKind.PRESCRIBER

    @property
    def is_employer(self):
        return self.kind == UserKind.EMPLOYER

    @property
    def is_labor_inspector(self):
        return self.kind == UserKind.LABOR_INSPECTOR

    def can_edit_email(self, user):
        return user.is_handled_by_proxy and user.is_created_by(self) and not user.has_verified_email

    def can_edit_personal_information(self, user):
        if self.pk == user.pk:  # I am me
            return True

        if self.is_prescriber:
            if self.is_prescriber_with_authorized_org:
                return user.is_handled_by_proxy
            else:
                return user.is_handled_by_proxy and user.is_created_by(self)
        elif self.is_employer:
            return user.is_handled_by_proxy

        return False

    def can_view_personal_information(self, user):
        if self.can_edit_personal_information(user):  # If we can edit them then we can view them
            return True

        if user.is_job_seeker:  # Restrict display of personal information to job seeker
            if self.is_prescriber:
                if self.is_prescriber_with_authorized_org:
                    return True
                else:
                    return user.is_handled_by_proxy and user.is_created_by(self)
            elif self.is_employer:
                return True

        return False

    def can_add_nir(self, job_seeker):
        return (self.is_prescriber_with_authorized_org or self.is_employer) and (
            job_seeker and not job_seeker.jobseeker_profile.nir
        )

    def is_created_by(self, user):
        return bool(self.created_by_id and self.created_by_id == user.pk)

    @property
    def has_sso_provider(self):
        return self.identity_provider != IdentityProvider.DJANGO

    @cached_property
    def has_verified_email(self):
        return self.emailaddress_set.filter(email=self.email, verified=True).exists()

    @cached_property
    def latest_approval(self):
        if not self.is_job_seeker:
            return None

        approvals = self.approvals.all()

        if not approvals:
            return None
        if approvals.valid().exists():
            return approvals.valid().first()

        approval = sorted(
            approvals,
            key=lambda x: (
                -time.mktime(x.end_at.timetuple()),
                time.mktime(x.start_at.timetuple()),
            ),
        )[0]
        if approval.waiting_period_has_elapsed:
            return None
        return approval

    @cached_property
    def latest_pe_approval(self):
        if not self.is_job_seeker:
            return None

        approval_numbers = self.approvals.all().values_list("number", flat=True)

        pe_approvals = PoleEmploiApproval.objects.find_for(self).exclude(number__in=approval_numbers)
        if not pe_approvals:
            return None
        pe_approval = sorted(
            pe_approvals,
            key=lambda x: (
                -time.mktime(x.end_at.timetuple()),
                time.mktime(x.start_at.timetuple()),
            ),
        )[0]
        if pe_approval.waiting_period_has_elapsed:
            return None
        return pe_approval

    @property
    def latest_common_approval(self):
        """
        Rationale:
        - if there is a latest PASS IAE that is valid, it is returned.
        - if there is no PASS IAE, we return the longest PE Approval whatever its state.
        - if there is no PASS nor PE Approval, or the waiting period for those is over, return nothing.
        - if the latest PASS IAE is invalid:
          * but still in waiting period:
            > return a valid PE Approval if there is one
            > else, return the PASS in waiting period.
          * if outdated, we consider there's no PASS. Return the latest PE approval, if any.
        """

        # if there is a latest PASS IAE that is valid, it is returned.
        if self.latest_approval and self.latest_approval.is_valid():
            return self.latest_approval

        if (
            self.latest_approval
            and self.latest_approval.is_in_waiting_period
            and self.latest_pe_approval
            and self.latest_pe_approval.is_valid
        ):
            return self.latest_pe_approval

        return self.latest_approval or self.latest_pe_approval

    @property
    def has_valid_common_approval(self):
        return (self.latest_approval and self.latest_approval.is_valid()) or (
            self.latest_pe_approval and self.latest_pe_approval.is_valid()
        )

    @property
    def has_common_approval_in_waiting_period(self):
        return (self.latest_approval and not self.latest_approval.is_valid()) or (
            self.latest_pe_approval and not self.latest_pe_approval.is_valid()
        )

    @property
    def has_no_common_approval(self):
        return not self.latest_approval and not self.latest_pe_approval

    def approval_can_be_renewed_by(self, siae, sender_prescriber_organization):
        """
        An approval in waiting period can only be bypassed if the prescriber is authorized
        or if the structure is not a SIAE.
        """
        is_sent_by_authorized_prescriber = (
            sender_prescriber_organization is not None and sender_prescriber_organization.is_authorized
        )

        # Only diagnoses made by authorized prescribers are taken into account.
        has_valid_diagnosis = self.has_valid_diagnosis()
        return (
            self.has_common_approval_in_waiting_period
            and siae.is_subject_to_eligibility_rules
            and not (is_sent_by_authorized_prescriber or has_valid_diagnosis)
        )

    def get_or_create_approval(self, origin_job_application):
        """
        Returns an existing valid Approval or create a new entry from
        a pre-existing valid PoleEmploiApproval by copying its data.
        """
        # FIXME(vperron): move this method and all the other approval-related code to JobSeekerProfile.
        if not self.has_valid_common_approval:
            raise RuntimeError("Invalid approval.")
        if self.latest_approval and self.latest_approval.is_valid():
            return self.latest_approval
        pe_approval = self.latest_pe_approval
        if Approval.objects.filter(number=pe_approval.number).exists():
            raise ApprovalAlreadyExistsError()
        approval_from_pe = Approval(
            start_at=pe_approval.start_at,
            end_at=pe_approval.end_at,
            user=self,
            number=pe_approval.number,
            origin=Origin.PE_APPROVAL,
            **Approval.get_origin_kwargs(origin_job_application),
        )
        approval_from_pe.save()
        return approval_from_pe

    @property
    def is_handled_by_proxy(self):
        if self.is_job_seeker and self.created_by_id and not self.last_login:
            return True
        return False

    @cached_property
    def is_prescriber_with_authorized_org(self):
        return (
            self.is_prescriber
            and self.prescribermembership_set.filter(
                is_active=True, organization__is_authorized=True, user__is_active=True
            ).exists()
        )

    @property
    def has_external_data(self):
        return self.is_job_seeker and hasattr(self, "jobseekerexternaldata")

    @property
    def has_jobseeker_profile(self):
        return self.is_job_seeker and hasattr(self, "jobseeker_profile")

    def has_valid_diagnosis(self, for_siae=None):
        return self.eligibility_diagnoses.has_considered_valid(job_seeker=self, for_siae=for_siae)

    def joined_recently(self):
        time_since_date_joined = timezone.now() - self.date_joined
        return time_since_date_joined.days < 7

    def active_or_in_grace_period_company_memberships(self):
        """
        Return the company memberships accessible to the employer, which means either active
        or in grace period, with a minimum of database queries.
        """
        # Unfortunately we need two queries here, no solution was found to combine both
        # `company_set.active_or_in_grace_period()` and `companymembership_set.active()` in a single query.
        user_company_set_pks = self.company_set.active_or_in_grace_period().values_list("pk", flat=True)
        memberships = (
            self.companymembership_set.active()
            .select_related("company")
            .filter(company__pk__in=user_company_set_pks)
            .all()
        )
        return memberships

    def can_create_siae_antenna(self, parent_siae):
        """
        Only admin employers can create an antenna for their SIAE.

        For SIAE structures (AI, ACI...) the convention has to be present to link the parent SIAE and its antenna.
        In some edge cases (e.g. SIAE created by staff and not yet officialized) the convention is absent,
        in that case we must absolutely not allow any antenna to be created.

        For non SIAE structures (EA, EATT...) the convention logic is not implemented thus no convention ever exists.
        Antennas cannot be freely created by the user as the EA system authorities do not allow any non official SIRET
        to be used (except for GEIQ).

        Finally, for OPCS it has been decided for now to disallow it; those structures are strongly attached to
        a given territory and thus would not need to join others.
        """
        return (
            self.is_employer
            and parent_siae.is_active
            and parent_siae.has_admin(self)
            and (
                parent_siae.kind == CompanyKind.GEIQ
                or (parent_siae.should_have_convention and parent_siae.convention is not None)
            )
        )

    def update_external_data_source_history_field(self, provider, field, value) -> bool:
        """
        Attempts to update the history json data for a field inside
        `external_data_source_history`, and returns a boolean if the user data was modified,
        so that the database save() can be performed later on

        We store a history of the various data sources for the user information
        inside `external_data_source_history`. It can look like:
        Since we only append data, they should all be chronologically sorted
        [
            {"field_name": "first_name", "source": "FRANCE_CONNECT", "created_at": "…", "value": "Jean-Michel"},
            {"field_name": "birth_date", "source": "PE_CONNECT", "created_at": "…", "value": "…"},
            …

        """
        now = timezone.now()
        has_performed_update = False

        if not self.external_data_source_history:
            self.external_data_source_history = []

        try:
            field_history = list(
                filter(
                    lambda d: d["field_name"] == field,
                    self.external_data_source_history,
                )
            )
            current_value = field_history[-1]["value"]
        except IndexError:
            current_value = None
        if current_value != value:
            self.external_data_source_history.append(
                {
                    "field_name": field,
                    "source": provider.value,
                    "created_at": now,
                    "value": value,
                }
            )
            has_performed_update = True
        return has_performed_update

    @cached_property
    def last_accepted_job_application(self):
        if not self.is_job_seeker:
            return None

        # Some candidates may not have accepted job applications
        # Assuming its the case can lead to issues downstream
        return self.job_applications.accepted().with_accepted_at().order_by("-accepted_at", "-hiring_start_at").first()

    def last_hire_was_made_by_company(self, company):
        if not self.is_job_seeker:
            return False
        return self.last_accepted_job_application and self.last_accepted_job_application.to_company == company

    @classmethod
    def create_job_seeker_by_proxy(cls, proxy_user, **fields):
        """
        Used when a "prescriber" user creates another user of kind "job seeker".

        Minimum required keys in `fields` are:
            {
                "email": "foo@foo.com",
                "first_name": "Foo",
                "last_name": "Foo",
            }
        """
        username = cls.generate_unique_username()
        fields["kind"] = UserKind.JOB_SEEKER
        fields["created_by"] = proxy_user
        user = cls.objects.create_user(username, email=fields.pop("email"), **fields)
        return user

    @classmethod
    def create_job_seeker_from_pole_emploi_approval(cls, proxy_user, email, pole_emploi_approval):
        """Uses the data from a PoleEmploiApproval to create a job seeker"""
        job_seeker_data = {
            "email": email,
            "first_name": pole_emploi_approval.first_name,
            "last_name": pole_emploi_approval.last_name,
            "birthdate": pole_emploi_approval.birthdate,
        }
        user = cls.create_job_seeker_by_proxy(proxy_user, **job_seeker_data)
        user.jobseeker_profile.pole_emploi_id = pole_emploi_approval.pole_emploi_id
        user.jobseeker_profile.save(update_fields=("pole_emploi_id",))
        return user

    @classmethod
    def generate_unique_username(cls):
        """
        `AbstractUser.username` is a required field. It is not used in Itou but
         it is still required in places like `User.objects.create_user()` etc.

        We used to rely on `allauth.utils.generate_unique_username` to populate
        it with a random username but it often failed causing errors in Sentry.

        We now use a UUID4.
        """
        return uuid.uuid4().hex

    @classmethod
    def email_already_exists(cls, email, exclude_pk=None):
        """
        RFC 5321 Part 2.4 states that only the domain portion of an email
        is case-insensitive. Consider toto@toto.com and TOTO@toto.com as
        the same email.
        """
        queryset = cls.objects.filter(email__iexact=email)
        if exclude_pk:
            queryset = queryset.exclude(pk=exclude_pk)
        return queryset.exists()

    def get_kind_display(self):
        return UserKind(self.kind).label


def get_allauth_account_user_display(user):
    return user.email


class JobSeekerProfile(models.Model):
    """
    Specific information about the job seeker

    Instead of augmenting the 'User' model, additional data is collected in a "profile" object.

    This user profile has 2 main parts:

    1 - Job seeker "administrative" situation

    These fields are part of the mandatory fields for EmployeeRecord processing:
    - education level
    - various social allowances flags and durations

    2 - Job seeker address in HEXA address format:

    The SNA (Service National de l'Adresse) has several certification / validation
    norms to verify french addresses:
    - Hexacle: house number level
    - Hexaposte: zip code level
    - Hexavia: street level
    + many others...

    For the employee record domain, this means that the job seeker address has to be
    formatted in a very specific way to be accepted as valid by ASP backend.

    These conversions and formatting processes are almost automatic,
    but absolutely not 100% error-proof.

    Formatted addresses are stored in this model, avoiding multiple calls to the
    reverse geocoding API at processing time.

    This kind of address are at the moment only used by the employee_record app,
    but their usage could be extended to other domains should the need arise.

    Note that despite the name, addresses of this model are not fully compliant
    with Hexa norms (but compliant enough to be accepted by ASP backend).
    """

    # Used for validation of birth country / place
    INSEE_CODE_FRANCE = Country._CODE_FRANCE

    ERROR_NOT_RESOURCELESS_IF_OETH_OR_RQTH = "La personne n'est pas considérée comme sans ressources si OETH ou RQTH"
    ERROR_EMPLOYEE_WITH_UNEMPLOYMENT_PERIOD = (
        "La personne ne peut avoir de période sans emploi si actuellement employée"
    )
    ERROR_UNEMPLOYED_BUT_RQTH_OR_OETH = (
        "La personne ne peut être considérée comme sans emploi si employée OETH ou RQTH"
    )
    ERROR_MUST_PROVIDE_BIRTH_PLACE = "Si le pays de naissance est la France, la commune de naissance est obligatoire"
    ERROR_BIRTH_COMMUNE_WITH_FOREIGN_COUNTRY = (
        "Il n'est pas possible de saisir une commune de naissance hors de France"
    )

    ERROR_HEXA_LANE_TYPE = "Le type de voie est obligatoire"
    ERROR_HEXA_LANE_NAME = "Le nom de voie est obligatoire"
    ERROR_HEXA_POST_CODE = "Le code postal est obligatoire"
    ERROR_HEXA_COMMUNE = "La commune INSEE est obligatoire"

    ERROR_JOBSEEKER_TITLE = "La civilité du demandeur d'emploi est obligatoire"
    ERROR_JOBSEEKER_EDUCATION_LEVEL = "Le niveau de formation du demandeur d'emploi est obligatoire"
    ERROR_JOBSEEKER_PE_FIELDS = "L'identifiant et la durée d'inscription à France Travail vont de pair"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        primary_key=True,
        verbose_name="demandeur d'emploi",
        related_name="jobseeker_profile",
    )

    birth_place = models.ForeignKey(
        "asp.Commune",
        verbose_name="commune de naissance",
        related_name="jobseeker_profiles_born_here",
        null=True,
        blank=True,
        on_delete=models.RESTRICT,
    )
    birth_country = models.ForeignKey(
        "asp.Country",
        verbose_name="pays de naissance",
        related_name="jobseeker_profiles_born_here",
        null=True,
        blank=True,
        on_delete=models.RESTRICT,
    )

    # Don’t need to specify db_index because unique implies the creation of an index.
    nir = models.CharField(
        verbose_name="NIR",
        max_length=15,
        validators=[validate_nir],
        blank=True,
    )

    lack_of_nir_reason = models.CharField(
        verbose_name="pas de NIR ?",
        help_text="Indiquez la raison de l'absence de NIR.",
        max_length=30,
        choices=LackOfNIRReason.choices,
        blank=True,
    )

    # The two following Pôle emploi fields are reserved for job seekers.
    # They are used in the process of delivering an approval.
    # They depend on each other: one or the other must be filled but not both.

    # Pôle emploi ID is not guaranteed to be unique.
    # At least, we haven't received any confirmation of its uniqueness.
    # It looks like it pre-dates the national merger and may be unique
    # by user and by region…
    pole_emploi_id = models.CharField(
        verbose_name="identifiant France Travail (ex pôle emploi)",
        help_text="7 chiffres suivis d'une 1 lettre ou d'un chiffre.",
        max_length=8,
        validators=[validate_pole_emploi_id, MinLengthValidator(8)],
        blank=True,
    )
    lack_of_pole_emploi_id_reason = models.CharField(
        verbose_name="pas d'identifiant France Travail (ex pôle emploi) ?",
        help_text=mark_safe(
            "Indiquez la raison de l'absence d'identifiant France Travail.<br>"
            "Renseigner l'identifiant France Travail des candidats inscrits "
            "permet d'instruire instantanément votre demande.<br>"
            "Dans le cas contraire un délai de deux jours est nécessaire "
            "pour effectuer manuellement les vérifications d’usage."
        ),
        choices=LackOfPoleEmploiId.choices,
        blank=True,
    )

    asp_uid = models.TextField(
        verbose_name="ID unique envoyé à l'ASP",
        help_text="Si vide, une valeur sera assignée automatiquement.",
        max_length=30,
        blank=True,
        unique=True,
    )

    education_level = models.CharField(
        max_length=2,
        verbose_name="niveau de formation (ASP)",
        blank=True,
        choices=EducationLevel.choices,
    )

    resourceless = models.BooleanField(verbose_name="sans ressource", default=False)

    rqth_employee = models.BooleanField(
        verbose_name="titulaire de la RQTH",
        help_text="Reconnaissance de la qualité de travailleur handicapé",
        default=False,
    )
    oeth_employee = models.BooleanField(
        verbose_name="bénéficiaire de la loi handicap (OETH)",
        help_text="L'obligation d’emploi des travailleurs handicapés",
        default=False,
    )

    pole_emploi_since = models.CharField(
        max_length=2,
        verbose_name="inscrit à France Travail depuis",
        blank=True,
        choices=AllocationDuration.choices,
    )

    unemployed_since = models.CharField(
        max_length=2,
        verbose_name="sans emploi depuis",
        blank=True,
        choices=AllocationDuration.choices,
    )

    previous_employer_kind = models.CharField(
        max_length=2,
        verbose_name="précédent employeur",
        blank=True,
        choices=EmployerType.choices,
    )

    # Despite the name of this field in the ASP model (salarieBenefRSA),
    # this field is not a boolean, but has 3 different options
    # See asp.models.RSAAllocation for details
    has_rsa_allocation = models.CharField(
        max_length=6,
        verbose_name="salarié bénéficiaire du RSA",
        choices=RSAAllocation.choices,
        default=RSAAllocation.NO,
    )

    rsa_allocation_since = models.CharField(
        max_length=2,
        verbose_name="allocataire du RSA depuis",
        blank=True,
        choices=AllocationDuration.choices,
    )

    ass_allocation_since = models.CharField(
        max_length=2,
        verbose_name="allocataire de l'ASS depuis",
        blank=True,
        choices=AllocationDuration.choices,
    )

    aah_allocation_since = models.CharField(
        max_length=2,
        verbose_name="allocataire de l'AAH depuis",
        blank=True,
        choices=AllocationDuration.choices,
    )

    ata_allocation_since = models.CharField(
        max_length=2,
        verbose_name="allocataire de l'ATA depuis",
        blank=True,
        choices=AllocationDuration.choices,
    )

    # Jobseeker address in Hexa format

    hexa_lane_number = models.CharField(max_length=10, verbose_name="numéro de la voie", blank=True, default="")
    hexa_std_extension = models.CharField(
        max_length=1,
        verbose_name="extension de voie",
        blank=True,
        default="",
        choices=LaneExtension.choices,
    )
    # No need to set blank=True, this field is never used with a text choice
    hexa_non_std_extension = models.CharField(
        max_length=10,
        verbose_name="extension de voie (non-repertoriée)",
        blank=True,
        default="",
    )
    hexa_lane_type = models.CharField(
        max_length=4,
        verbose_name="type de voie",
        blank=True,
        choices=LaneType.choices,
    )
    hexa_lane_name = models.CharField(max_length=120, verbose_name="nom de la voie", blank=True)
    hexa_additional_address = models.CharField(max_length=32, verbose_name="complément d'adresse", blank=True)
    hexa_post_code = models.CharField(max_length=6, verbose_name="code postal", blank=True)
    hexa_commune = models.ForeignKey(
        Commune,
        verbose_name="commune (ref. ASP)",
        null=True,
        blank=True,
        on_delete=models.RESTRICT,
    )

    pe_obfuscated_nir = models.CharField(
        verbose_name="identifiant France Travail (ex pôle emploi) chiffré",
        null=True,
        blank=True,
        max_length=48,
        help_text=(
            "Identifiant France Travail chiffré, utilisé dans la communication à France Travail. "
            "Son existence implique que le nom, prénom, date de naissance et NIR de ce candidat "
            "sont connus et valides du point de vue de France Travail.",
        ),
    )

    pe_last_certification_attempt_at = models.DateTimeField(
        verbose_name="date de la dernière tentative de certification",
        null=True,
        help_text="Date à laquelle nous avons tenté pour la dernière fois de certifier ce candidat",
    )

    class Meta:
        verbose_name = "profil demandeur d'emploi"
        verbose_name_plural = "profils demandeur d'emploi"

        constraints = [
            # Make sure that if you have a lack_of_nir_reason value, you cannot have a nir value
            # (but we'll have a lot of users lacking both nir & lack_of_nir_reason values)
            models.CheckConstraint(
                check=Q(lack_of_nir_reason="") | Q(nir=""),
                name="jobseekerprofile_lack_of_nir_reason_or_nir",
                violation_error_message=(
                    "Un utilisateur ayant un NIR ne peut avoir un motif justifiant l'absence de son NIR."
                ),
            ),
            UniqueConstraintWithErrorCode(
                "nir",
                name="jobseekerprofile_unique_nir_if_not_empty",
                condition=~Q(nir=""),
                validation_error_code="unique_nir_if_not_empty",
                violation_error_message="Ce numéro de sécurité sociale est déjà associé à un autre utilisateur.",
            ),
        ]

    def __str__(self):
        return str(self.user)

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        instance._old_values = dict(zip(field_names, values))
        return instance

    def has_data_changed(self, fields):
        if hasattr(self, "_old_values"):
            for field in fields:
                if getattr(self, field) != self._old_values[field]:
                    return True
        return False

    def _default_asp_uid(self):
        return salted_hmac(key_salt="job_seeker.id", value=self.user_id).hexdigest()[:30]

    def save(self, force_insert=False, force_update=False, using=None, update_fields=None):
        self.validate_constraints()
        if not self.asp_uid:
            self.asp_uid = self._default_asp_uid()
            if update_fields is not None:
                update_fields = set(update_fields) | {"asp_uid"}
        if self.has_data_changed(["nir"]):
            self.pe_obfuscated_nir = None
            self.pe_last_certification_attempt_at = None
            if update_fields is not None:
                update_fields = set(update_fields) | {"pe_obfuscated_nir", "pe_last_certification_attempt_at"}
        super().save(force_insert=force_insert, force_update=force_update, using=using, update_fields=update_fields)

    @staticmethod
    def clean_pole_emploi_fields(cleaned_data):
        """
        Validate Pôle emploi fields that depend on each other.
        Only for users with kind == job_seeker.
        It must be used in forms and modelforms that manipulate job seekers.
        """
        pole_emploi_id = cleaned_data.get("pole_emploi_id")
        lack_of_pole_emploi_id_reason = cleaned_data.get("lack_of_pole_emploi_id_reason")
        # One or the other must be filled.
        if not pole_emploi_id and not lack_of_pole_emploi_id_reason:
            raise ValidationError(
                "Renseignez soit un identifiant France Travail (ex pôle emploi), soit la raison de son absence."
            )
        # If both are filled, `pole_emploi_id` takes precedence (Trello #1724).
        if pole_emploi_id and lack_of_pole_emploi_id_reason:
            # Take advantage of the fact that `cleaned_data` is passed by sharing:
            # the object is shared between the caller and the called routine.
            cleaned_data["lack_of_pole_emploi_id_reason"] = ""

    def _clean_job_seeker_details(self):
        # Title is not mandatory for User, but it is for ASP
        if not self.user.title:
            raise ValidationError(self.ERROR_JOBSEEKER_TITLE)

        # Check birth place and country
        self._clean_birth_fields()

        if not self.education_level:
            raise ValidationError(self.ERROR_JOBSEEKER_EDUCATION_LEVEL)

    def _clean_job_seeker_situation(self):
        if self.previous_employer_kind and self.unemployed_since:
            raise ValidationError(self.ERROR_EMPLOYEE_WITH_UNEMPLOYMENT_PERIOD)

        # NOTE(fvergez): Seems to be a major source of 500 errors
        # Not really needed here, checks are done at form level
        # if bool(self.pole_emploi_since) != bool(self.user.pole_emploi_id):
        #   raise ValidationError(self.ERROR_JOBSEEKER_PE_FIELDS)

        # Social allowances fields are not mandatory
        # However we may add some coherence check later on

    def _clean_job_seeker_hexa_address(self):
        # Check if any fields of the hexa address is filled
        if not any(
            [
                self.hexa_lane_number,
                self.hexa_std_extension,
                self.hexa_non_std_extension,
                self.hexa_lane_type,
                self.hexa_lane_name,
                self.hexa_additional_address,
                self.hexa_post_code,
                self.hexa_commune,
            ]
        ):
            # Nothing to check
            return

        # if any 'hexa' field is given, then check all mandatory fields
        # (all or nothing)
        if not self.hexa_lane_type:
            raise ValidationError(self.ERROR_HEXA_LANE_TYPE)

        if not self.hexa_lane_name:
            raise ValidationError(self.ERROR_HEXA_LANE_NAME)

        if not self.hexa_post_code:
            raise ValidationError(self.ERROR_HEXA_POST_CODE)

        if not self.hexa_commune:
            raise ValidationError(self.ERROR_HEXA_COMMUNE)

    def _clean_birth_fields(self):
        """
        Validation for FS
        Mainly coherence checks for birth country / place.
        Must be non blocking if these fields are not provided.
        """
        # If birth country is France, then birth place must be provided
        if self.birth_country and self.birth_country.code == self.INSEE_CODE_FRANCE and not self.birth_place:
            raise ValidationError(self.ERROR_MUST_PROVIDE_BIRTH_PLACE)

        # If birth country is not France, do not fill a birth place (no ref file)
        if self.birth_country and self.birth_country.code != self.INSEE_CODE_FRANCE and self.birth_place:
            raise ValidationError(self.ERROR_BIRTH_COMMUNE_WITH_FOREIGN_COUNTRY)

    #  This used to be the `clean` method for the global model validation
    #  when using forms.
    #  However, building forms with ModelForm objects and a *subset* of
    #  the model fields is really troublesome when using a global validator.
    #  (forms are calling model.clean() at every validation).
    #  This method is triggered manually.
    def clean_model(self):
        """
        Global model validation. Used to be the `clean` method.
        """
        # see partial validation methods above
        self._clean_job_seeker_details()
        self._clean_job_seeker_situation()
        self._clean_job_seeker_hexa_address()

    def update_hexa_address(self):
        """
        This method tries to fill the HEXA address fields based the current address of the job seeker (`User` model).
        """
        result, error = format_address(self.user)

        if error:
            raise ValidationError(error)

        # Fill matching fields
        self.hexa_lane_type = result.get("lane_type")
        self.hexa_lane_number = result.get("number")
        self.hexa_std_extension = result.get("std_extension", "")
        self.hexa_non_std_extension = result.get("non_std_extension")
        self.hexa_lane_name = result.get("lane")
        self.hexa_post_code = result.get("post_code")
        self.hexa_additional_address = result.get("additional_address")

        # Special field: Commune object contains both city name and INSEE code
        insee_code = result.get("insee_code")

        try:
            self.hexa_commune = Commune.objects.by_insee_code(insee_code)
        except Commune.DoesNotExist:
            raise ValidationError(f"Le code INSEE {insee_code} n'est pas référencé par l'ASP")

        self.save()

        return self

    def clear_hexa_address(self):
        """
        Wipe hexa address fields and updates the profile in DB.

        Use with caution:
            clearing HEXA addresses of a job seeker can block employee record update notifications transfer.
        """
        self.hexa_lane_type = ""
        self.hexa_lane_number = ""
        self.hexa_std_extension = ""
        self.hexa_non_std_extension = ""
        self.hexa_lane_name = ""
        self.hexa_additional_address = ""
        self.hexa_post_code = ""
        self.hexa_commune = None

        self.save()

    @property
    def is_employed(self):
        # `previous_employer_kind` field is not needed for ASP processing
        return not self.unemployed_since

    @property
    def has_ass_allocation(self):
        return bool(self.ass_allocation_since)

    @property
    def has_aah_allocation(self):
        return bool(self.aah_allocation_since)

    @property
    def has_ata_allocation(self):
        return bool(self.ata_allocation_since)

    @property
    def has_social_allowance(self):
        return bool(
            self.has_rsa_allocation != RSAAllocation.NO
            or self.has_ass_allocation
            or self.has_aah_allocation
            or self.has_ata_allocation
        )

    @property
    def hexa_address_filled(self):
        return bool(self.hexa_lane_name and self.hexa_lane_type and self.hexa_post_code and self.hexa_commune)

    @property
    def hexa_address_display(self):
        if self.hexa_address_filled:
            result = ""
            if self.hexa_lane_number:
                result += f"{self.hexa_lane_number} "
            if self.hexa_std_extension:
                result += f"{self.hexa_std_extension} "
            elif self.hexa_non_std_extension:
                result += f"{self.hexa_non_std_extension} "
            if self.hexa_lane_type:
                result += f"{self.get_hexa_lane_type_display()} "

            result += f"{self.hexa_lane_name} - {self.hexa_post_code} {self.hexa_commune.name}"
            return result

        return "Adresse HEXA incomplète"
