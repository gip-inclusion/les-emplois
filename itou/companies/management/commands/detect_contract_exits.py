import datetime

from django.db.models import Exists, OuterRef
from django.template.defaultfilters import pluralize
from django.utils import timezone
from itoutils.django.commands import dry_runnable

from itou.companies.constants import CONTRACT_EXIT_DETECTION_DAYS
from itou.companies.models import Contract, ContractExit
from itou.utils.command import BaseCommand


# Exit reasons declared by the SIAE to the ASP, as received in `Contract.details`.
# They are identified by their label, which the data team guarantees stable, and not by their code:
# several labels share a code.
NEGATIVE_EXIT_REASONS = frozenset(
    {
        "Au chômage",
        "Démission du bénéficiaire",
        "Inactif",
        "Rupture employeur pour faute grave du salarié",
        "Rupture pendant la période d'essai à l'initiative de l'employeur",
        "Rupture pendant la période d'essai à l'initiative du salarié",
        "Sans nouvelle",
    }
)
OTHER_EXIT_REASONS = frozenset(
    {
        "Autre sortie reconnue comme positive",
        "Classement au service général",
        "Classement auprès d'un concessionnaire de l'établissement pénitentiaire",
        "Congés de longue durée (maternité, maladie)",
        "Création et reprise d'entreprise à son compte hors détention",
        "Création ou reprise d'entreprise à son compte",
        "Création ou reprise d'entreprise à son compte (hors EITI)",
        "Décision administrative / Décision de justice",
        "Décision de déclassement du chef d'établissement",
        "Décès",
        "Embauche en CDD (sans aide publique à l'emploi) d'une durée de 6 mois et plus",
        "Embauche en CDD (sans aide publique à l'emploi) d'une durée de 6 mois et plus hors détention",
        "Embauche en CDD (sans aide publique à l'emploi) de moins de 6 mois (hors IAE)",
        "Embauche en CDD (sans aide publique à l'emploi) de moins de 6 mois par un autre employeur",
        (
            "Embauche en CDD (sans aide publique à l'emploi) de moins de 6 mois par un autre employeur "
            "hors détention ou contrat de travail temporaire"
        ),
        "Embauche en CDI aidé",
        "Embauche en CDI aidé par un autre employeur",
        "Embauche en CDI dans la structure ou filiale",
        "Embauche en CDI Inclusion",
        "Embauche en CDI non aidé",
        "Embauche en CDI non aidé par un autre employeur",
        "Embauche en CDI non aidé par un autre employeur hors détention",
        "Embauche en contrat aidé pour une durée déterminée (hors IAE)",
        "Embauche en contrat aidé pour une durée déterminée par un autre employeur (hors IAE)",
        "Embauche en contrat passerelle",
        "Embauche pour une durée déterminée dans une autre structure IAE",
        "Entrée en formation qualifiante ou poursuite de formation qualifiante",
        "Entrée en formation qualifiante ou poursuite de formation qualifiante en détention",
        "Entrée en formation qualifiante ou poursuite de formation qualifiante hors détention",
        "Intégration dans la fonction publique",
        "Libération",
        "Pour une durée déterminée dans une autre structure IAE hors détention",
        "Poursuite au sein de l'EITI sans aide au poste avec un CA supérieur au seuil de pauvreté",
        "Poursuite au sein de l'EITI sans aide au poste avec un CA supérieur à 70% du salaire médian mensuel",
        "Prise des droits à la retraite",
        "Sortie automatique",
        "Sortie en CDDI CVG",
        "Sortie en CDDI Classique",
        "Transfert d'employeur",
    }
)


class Command(BaseCommand):
    ATOMIC_HANDLE = True

    def add_arguments(self, parser):
        parser.add_argument("--wet-run", dest="wet_run", action="store_true")

    @dry_runnable
    def handle(self, *, wet_run, **options):
        today = timezone.localdate()
        contracts = (
            Contract.objects.filter(
                end_date__range=(today - datetime.timedelta(days=CONTRACT_EXIT_DETECTION_DAYS), today),
            )
            .exclude(Exists(ContractExit.objects.filter(contract=OuterRef("pk"), exit_date=OuterRef("end_date"))))
            .only("end_date", "details")
        )

        exits = []
        unknown_reasons = set()
        for contract in contracts.iterator():
            exit_reason = contract.exit_reason
            if exit_reason in NEGATIVE_EXIT_REASONS:
                exits.append(ContractExit(contract=contract, exit_date=contract.end_date))
            elif exit_reason is not None and exit_reason not in OTHER_EXIT_REASONS:
                unknown_reasons.add(exit_reason)

        # A new label means the ASP changed its list: the exits using it are ignored until we classify it.
        for exit_reason in sorted(unknown_reasons):
            self.logger.error("Unknown contract exit reason: %s", exit_reason)

        ContractExit.objects.bulk_create(exits)
        self.logger.info("Detected %d new contract exit%s.", len(exits), pluralize(len(exits)))
