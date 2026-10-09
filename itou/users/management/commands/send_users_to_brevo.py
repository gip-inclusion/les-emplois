import datetime
from collections import namedtuple
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
PROFESSIONAL_SSO_PROVIDERS = [IdentityProvider.PRO_CONNECT]
JOB_SEEKER_SSO_PROVIDERS = [IdentityProvider.FRANCE_CONNECT, IdentityProvider.FT_CONNECT]

Audience = namedtuple("Audience", ["name", "users", "list_id", "serializer"])


def has_verified_primary_email():
    return Exists(
        EmailAddress.objects.filter(
            user_id=OuterRef("pk"),
            email=OuterRef("email"),
            primary=True,
            verified=True,
        )
    )


def verified_email_or_sso(identity_providers):
    """Condition on users having a verified primary email, or an account from an SSO, which verifies emails itself."""
    return has_verified_primary_email() | Q(identity_provider__in=identity_providers)


def has_membership(membership_model, **filters):
    """Condition on users having an active membership of the given model."""
    return Exists(membership_model.objects.filter(user_id=OuterRef("pk"), **filters))


def has_siae_membership():
    """Condition on users being members of an SIAE, as opposed to other kinds of companies."""
    return has_membership(CompanyMembership, company__kind__in=CompanyKind.siae_kinds())


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


def professional_audiences():
    """Return the audiences of the professionals who are SIAE or prescriber members."""
    professionals = User.objects.filter(
        verified_email_or_sso(PROFESSIONAL_SSO_PROVIDERS),
        kind=UserKind.PROFESSIONAL,
        is_active=True,
    ).order_by("email")
    authorized_prescriber = has_membership(
        PrescriberMembership,
        organization__authorization_status=PrescriberAuthorizationStatus.VALIDATED,
    )
    return [
        Audience(
            "SIAE users",
            professionals.filter(has_siae_membership()),
            BrevoListID.EMPLOYERS,
            employer_serializer,
        ),
        Audience(
            "Prescribers",
            professionals.filter(authorized_prescriber),
            BrevoListID.PRESCRIBERS,
            authorized_prescriber_serializer,
        ),
        Audience(
            "Orienteurs",
            professionals.filter(has_membership(PrescriberMembership)).exclude(authorized_prescriber),
            BrevoListID.PRESCRIBERS,
            prescriber_serializer,
        ),
    ]


def job_seekers():
    """Return the job seekers who may be sent to Brevo."""
    return User.objects.filter(
        verified_email_or_sso(JOB_SEEKER_SSO_PROVIDERS),
        kind=UserKind.JOB_SEEKER,
        is_active=True,
    ).order_by("pk")


def job_seekers_to_import():
    """Return the job seekers of the daily import: recently joined, stalled, or autonomous and waiting for a job."""
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
    return job_seekers().filter(
        Q(
            Q(date_joined__gte=midnight_today - datetime.timedelta(days=30)),
            JobSeekerProfileQuerySet.is_considered_stalled_condition(True, "jobseeker_profile__"),
            autonomous_with_recent_diagnosis_and_no_accepted_application,
            _connector=Q.OR,
        )
    )


def daily_audiences():
    """Return the audiences of the daily import, meant for new contacts."""
    return [
        *professional_audiences(),
        Audience("Job seekers", job_seekers_to_import(), BrevoListID.CANDIDATS, job_seeker_serializer),
    ]


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
        client = BrevoClient()
        self.import_audiences(client, daily_audiences(), wet_run=wet_run)

    def import_audiences(self, client, audiences, *, wet_run):
        """Log the size of each audience, and import it into its Brevo list on a wet run."""
        for name, users, list_id, serializer in audiences:
            users = list(users)
            self.logger.info("%s count: %d", name, len(users))
            if wet_run:
                client.import_users(users, list_id, serializer)
