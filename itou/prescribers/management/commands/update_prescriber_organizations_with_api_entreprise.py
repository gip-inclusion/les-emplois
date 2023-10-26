import datetime
import logging

from django.utils import timezone

from itou.prescribers.models import PrescriberOrganization
from itou.utils.apis.api_entreprise import etablissement_get_or_error
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    """
    By default, the command updates the last 200 prescriber organizations sorted
    by updated_at and not updated in the last 7 days with informations from API
    Entreprise.

    With around 5k organizations in DB, it's one update a month for every
    organization.
    """

    help = "Fetch informations from API Entreprise to update organizations."

    def add_arguments(self, parser):
        parser.add_argument(
            "--max",
            dest="n_organizations",
            metavar="N",
            type=int,
            help="Maximum number of organizations to update",
            required=False,
            default=200,
        )
        parser.add_argument(
            "--days",
            dest="days",
            metavar="DAYS",
            type=int,
            help="Update organizations not modified in the last n days",
            required=False,
            default=7,
        )

    def set_logger(self, verbosity):
        """
        Set logger level based on the verbosity option.
        """
        handler = logging.StreamHandler(self.stdout)

        self.logger = logging.getLogger(__name__)
        self.logger.propagate = False
        self.logger.addHandler(handler)

        self.logger.setLevel(logging.INFO)
        if verbosity > 1:
            self.logger.setLevel(logging.DEBUG)

    def handle(self, *, days, n_organizations, verbosity, **options):
        self.set_logger(verbosity)

        prescriber_orgs = PrescriberOrganization.objects.filter(
            updated_at__lte=timezone.now() - datetime.timedelta(days=days)
        ).exclude(siret__isnull=True)[:n_organizations]
        for prescriber_org in prescriber_orgs:
            self.logger.info("ID %s - SIRET %s - %s", prescriber_org.pk, prescriber_org.siret, prescriber_org.name)
            etablissement, error = etablissement_get_or_error(prescriber_org.siret)
            if error:
                self.logger.error("| Unable to fetch information: %s", error)
            elif prescriber_org.is_head_office != etablissement.is_head_office:
                self.logger.debug("| New status of head office: %s", etablissement.is_head_office)
                prescriber_org.is_head_office = etablissement.is_head_office

            # Organization is saved to set updated_at field even if no changes because we don't want
            # to block on organizations that are unrecognized by API Entreprise.
            # Round after round, only the unrecognized organizations would be selected by the query.
            prescriber_org.save()
