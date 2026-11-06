import datetime
from zoneinfo import ZoneInfo

from allauth.account.models import EmailAddress
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone
from sentry_sdk.crons import monitor

from itou.companies.enums import CompanyKind
from itou.companies.models import CompanyMembership
from itou.eligibility.enums import AuthorKind
from itou.eligibility.models import EligibilityDiagnosis
from itou.job_applications.models import JobApplication, JobApplicationState
from itou.prescribers.enums import PrescriberAuthorizationStatus
from itou.prescribers.models import PrescriberMembership
from itou.users.enums import IdentityProvider, UserKind
from itou.users.models import JobSeekerProfileQuerySet, User
from itou.utils.brevo import PIXEL_TRACKING_CONSENT_ATTRIBUTE, BrevoClient, BrevoListID
from itou.utils.command import BaseCommand


RECENT_DIAGNOSIS_THRESHOLD = datetime.datetime(2025, 4, 1, tzinfo=ZoneInfo("Europe/Paris"))
# The command runs daily: the overlap makes up for a missed or failed run
EMAIL_TRACKING_CONSENT_UPDATE_WINDOW = datetime.timedelta(days=2)


def verified_email_or_sso(identity_providers):
    """Condition on users having a verified primary email, or an account from an SSO, which verifies emails itself."""
    has_verified_primary_email = Exists(
        EmailAddress.objects.filter(
            user_id=OuterRef("pk"),
            email=OuterRef("email"),
            primary=True,
            verified=True,
        )
    )
    return has_verified_primary_email | Q(identity_provider__in=identity_providers)


def has_siae_membership(*, include_inactive=False):
    """Condition on users being members of an SIAE, as opposed to other kinds of companies.

    Memberships are deactivated rather than deleted, so `include_inactive` also matches former members.
    """
    memberships = CompanyMembership.include_inactive if include_inactive else CompanyMembership.objects
    return Exists(
        memberships.filter(
            user_id=OuterRef("pk"),
            company__kind__in=CompanyKind.siae_kinds(),
        )
    )


def has_prescriber_membership(*, include_inactive=False, **filters):
    """Condition on users being members of a prescriber organization, matching the given filters.

    Memberships are deactivated rather than deleted, so `include_inactive` also matches former members.
    """
    memberships = PrescriberMembership.include_inactive if include_inactive else PrescriberMembership.objects
    return Exists(memberships.filter(user_id=OuterRef("pk"), **filters))


def email_tracking_consent_attributes(user):
    if user.email_tracking_consent_updated_at is None:
        # Never asked: no attribute, Brevo must consider that there is no consent
        return {}
    return {PIXEL_TRACKING_CONSENT_ATTRIBUTE: "Yes" if user.email_tracking_consent else "No"}


def professional_serializer(user, brevo_type):
    return {
        "email": user.email,
        "attributes": {
            "prenom": user.first_name.title(),
            "nom": user.last_name.upper(),
            "date_inscription": timezone.localdate(user.date_joined).isoformat(),
            "type": brevo_type,
            **email_tracking_consent_attributes(user),
        },
    }


def employer_serializer(user):
    return professional_serializer(user, "employeur")


def authorized_prescriber_serializer(user):
    return professional_serializer(user, "prescripteur habilité")


def prescriber_serializer(user):
    return professional_serializer(user, "orienteur")


def job_seeker_serializer(user):
    return {
        "email": user.email,
        "attributes": {
            "id": user.pk,
            "prenom": user.first_name.title(),
            "nom": user.last_name.upper(),
            "departement": user.job_seeker_department,
            "date_inscription": timezone.localdate(user.date_joined).isoformat(),
            **email_tracking_consent_attributes(user),
        },
    }


class Command(BaseCommand):
    ATOMIC_HANDLE = False
    AUTO_TRIGGER_CONTEXT = False

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--wet-run",
            action="store_true",
            help="Enroll new users to a mailing list in Brevo",
        )

    @monitor(
        monitor_slug="new-users-to-brevo",
        monitor_config={
            "schedule": {"type": "crontab", "value": "30 1 * * *"},
            "checkin_margin": 30,
            "max_runtime": 30,
            "failure_issue_threshold": 1,
            "recovery_threshold": 1,
            "timezone": "UTC",
        },
    )
    def handle(self, *args, wet_run, **options):
        self.client = BrevoClient()
        self.wet_run = wet_run
        professionals = User.objects.filter(
            verified_email_or_sso([IdentityProvider.PRO_CONNECT]),
            kind=UserKind.PROFESSIONAL,
            is_active=True,
        ).order_by("email")
        job_seekers = User.objects.filter(
            verified_email_or_sso([IdentityProvider.FRANCE_CONNECT, IdentityProvider.FT_CONNECT]),
            kind=UserKind.JOB_SEEKER,
            is_active=True,
        ).order_by("pk")
        self.import_professionals(professionals)
        self.import_job_seekers(job_seekers)
        # Imports are asynchronous, so this update doesn't depend on the daily import above. A user
        # in both is sent twice with the same consent, which is harmless.
        self.update_email_tracking_consents(professionals, job_seekers)

    def import_users(self, name, users, list_id, serializer, *, update_existing_contacts=False):
        """Log the number of users, and import them into a Brevo list on a wet run."""
        users = list(users)
        self.logger.info("%s count: %d", name, len(users))
        if self.wet_run:
            self.client.import_users(users, list_id, serializer, update_existing_contacts=update_existing_contacts)

    def import_professionals(
        self, professionals, *, include_inactive_memberships=False, name_suffix="", update_existing_contacts=False
    ):
        """Import the SIAE members into the employers list, and the prescriber members into the prescribers list.

        Professionals who are neither were never sent to Brevo, so they are left out.

        Args:
            professionals: Professionals to import.
            include_inactive_memberships: also match former members, through their inactive memberships.
            name_suffix: appended to the name of each group of users in the logs.
            update_existing_contacts: see `BrevoClient.import_users()`.
        """
        authorized_prescriber = has_prescriber_membership(
            include_inactive=include_inactive_memberships,
            organization__authorization_status=PrescriberAuthorizationStatus.VALIDATED,
        )
        self.import_users(
            f"SIAE users{name_suffix}",
            professionals.filter(has_siae_membership(include_inactive=include_inactive_memberships)),
            BrevoListID.EMPLOYERS,
            employer_serializer,
            update_existing_contacts=update_existing_contacts,
        )
        self.import_users(
            f"Prescribers{name_suffix}",
            professionals.filter(authorized_prescriber),
            BrevoListID.PRESCRIBERS,
            authorized_prescriber_serializer,
            update_existing_contacts=update_existing_contacts,
        )
        self.import_users(
            f"Orienteurs{name_suffix}",
            professionals.filter(has_prescriber_membership(include_inactive=include_inactive_memberships)).exclude(
                authorized_prescriber
            ),
            BrevoListID.PRESCRIBERS,
            prescriber_serializer,
            update_existing_contacts=update_existing_contacts,
        )

    def import_job_seekers(self, job_seekers):
        """Import the job seekers recently joined, stalled, or autonomous and waiting for a job."""
        midnight_today = datetime.datetime.combine(
            timezone.localdate(),
            datetime.time.min,
            tzinfo=timezone.get_current_timezone(),
        )
        autonomous_with_recent_diagnosis_and_no_accepted_application = Q(
            Exists(
                EligibilityDiagnosis.objects.filter(
                    job_seeker_id=OuterRef("pk"),
                    author_kind=AuthorKind.PRESCRIBER,
                    created_at__gte=RECENT_DIAGNOSIS_THRESHOLD,
                )
            ),
            ~Exists(
                JobApplication.objects.filter(
                    job_seeker_id=OuterRef("pk"),
                    state=JobApplicationState.ACCEPTED,
                )
            ),
            last_login__isnull=False,
        )
        job_seekers_to_import = job_seekers.filter(
            Q(date_joined__gte=midnight_today - datetime.timedelta(days=30))
            | JobSeekerProfileQuerySet.is_considered_stalled_condition(True, "jobseeker_profile__")
            | autonomous_with_recent_diagnosis_and_no_accepted_application
        )
        self.import_users("Job seekers", job_seekers_to_import, BrevoListID.CANDIDATS, job_seeker_serializer)

    def update_email_tracking_consents(self, professionals, job_seekers):
        """Import the users who recently answered the email tracking consent, each in their Brevo list.

        Importing them updates the contacts Brevo knows, and creates the others in that list. Each answer is sent by
        every run within the update window.
        """
        recently_answered = Q(
            email_tracking_consent_updated_at__gte=timezone.now() - EMAIL_TRACKING_CONSENT_UPDATE_WINDOW
        )
        name_suffix = " with a recent email tracking consent answer"
        professionals = professionals.filter(recently_answered)
        self.import_professionals(professionals, name_suffix=name_suffix, update_existing_contacts=True)
        # Former members left their structure but remain in Brevo, in the list of their former structure.
        # Someone now in a structure is only sent to the list of their current one.
        former_members = professionals.exclude(has_siae_membership() | has_prescriber_membership())
        self.import_professionals(
            former_members,
            include_inactive_memberships=True,
            name_suffix=f" (former members){name_suffix}",
            update_existing_contacts=True,
        )
        self.import_users(
            f"Job seekers{name_suffix}",
            job_seekers.filter(recently_answered),
            BrevoListID.CANDIDATS,
            job_seeker_serializer,
            update_existing_contacts=True,
        )
