import datetime
import random

from dateutil.relativedelta import relativedelta
from django.core.management import CommandError
from django.urls import reverse
from django.utils import timezone

from itou.companies.enums import ProSupportReportBarrier, ProSupportReportOrientation, ProSupportReportSolution
from itou.inclusion_pass import catalogue, connecteurs, demo, services
from itou.inclusion_pass.models import (
    Accompagnement,
    BilanIntervention,
    NotificationPrescripteur,
    Offreur,
    SituationSuivi,
)
from itou.insertion.enums import GenericReferenceItemKind, OrientationStatus
from itou.insertion.models import GenericReferenceItem, Orientation, Service, Structure
from itou.users.enums import IdentityProvider, Title, UserKind
from itou.users.models import User
from itou.utils.command import BaseCommand


OFFREUR_EMAIL = "demo.emplois+offreur@inclusion.gouv.fr"
STRUCTURE_UID = "pass-demo--auto-ecole-solidaire"

# Fictitious people for a non-empty follow-up list and impact report: name, title, birth year.
# The first ones were oriented by the demo prescriber and their follow-up has ended, the last ones came on their own
ANCIENS = [
    ("Karim", "Benali", Title.M, 2003),
    ("Julie", "Moreau", Title.MME, 1999),
    ("Thomas", "Leroy", Title.M, 1988),
    ("Aïcha", "Diallo", Title.MME, 1975),
    ("Nicolas", "Petit", Title.M, 1996),
    ("Sarah", "Lambert", Title.MME, 1968),
    ("Mehdi", "Haddad", Title.M, 2001),
    ("Laura", "Garnier", Title.MME, 1990),
    ("Kevin", "Roux", Title.M, 1985),
    ("Ray", "Troviseur", Title.M, 1979),
    ("Sarah", "Lentie", Title.MME, 2002),
    ("Agnès", "Thésie", Title.MME, 1971),
    ("Clara", "Vane", Title.MME, 1994),
    ("Laure", "Ganiser", Title.MME, 1983),
    ("Jean", "Tilhomme", Title.M, 1966),
    ("Henri", "Chir", Title.M, 1998),
    ("Lydia", "Logue", Title.MME, 1987),
    ("Sam", "Dépanne", Title.M, 2004),
    ("Anne", "Ticipé", Title.MME, 1992),
    ("Paul", "Itesse", Title.M, 1981),
]
AUTONOMES = 4

# Orientations received by the structure, besides the persona's one: name, title, status, days ago.
# Pending ones are less than 30 days old, otherwise the expire_orientations cron would expire them
ORIENTES = [
    ("Inès", "Faure", Title.MME, OrientationStatus.PENDING, 2),
    ("Lucas", "Mercier", Title.M, OrientationStatus.PENDING, 6),
    ("Nadia", "Bouzid", Title.MME, OrientationStatus.ACCEPTED, 10),
    ("Hugo", "Lemoine", Title.M, OrientationStatus.REFUSED, 14),
    ("Jacques", "Célère", Title.M, OrientationStatus.PENDING, 1),
    ("Marc", "Arrière", Title.M, OrientationStatus.PENDING, 3),
    ("Lucie", "Dité", Title.MME, OrientationStatus.PENDING, 8),
    ("Alain", "Térieur", Title.M, OrientationStatus.PENDING, 12),
    ("Odile", "Igence", Title.MME, OrientationStatus.ACCEPTED, 16),
    ("Mehdi", "Cament", Title.M, OrientationStatus.REFUSED, 19),
    ("Phil", "Indienne", Title.M, OrientationStatus.PENDING, 21),
    ("Élodie", "Vrance", Title.MME, OrientationStatus.ACCEPTED, 25),
    ("Jean-Michel", "Apeupré", Title.M, OrientationStatus.REFUSED, 31),
    ("Rémi", "Fasol", Title.M, OrientationStatus.ACCEPTED, 40),
]

SERVICES = [
    {
        "nom": "Permis B à tarif solidaire",
        "description": (
            "Formation au code et à la conduite à tarif adapté, avec un moniteur formé à l’accompagnement "
            "des publics éloignés de l’emploi. Rythme aménagé selon les contraintes de chacun."
        ),
        "thematique": "mobilite--preparer-un-permis",
        "type": "formation",
    },
    {
        "nom": "Code de la route accompagné",
        "description": "Séances collectives de préparation à l’examen du code, avec une plateforme en ligne.",
        "thematique": "mobilite--preparer-un-permis",
        "type": "atelier",
    },
    {
        "nom": "Bilan mobilité",
        "description": "Un entretien pour faire le point sur vos déplacements et trouver une solution adaptée.",
        "thematique": "mobilite--etre-accompagne-dans-son-parcours-mobilite",
        "type": "accompagnement",
    },
]


def _reference(kind, value):
    return GenericReferenceItem.objects.get(kind=kind, value=value)


class Command(BaseCommand):
    help = "Create (or recreate with --reset) the fictitious data of the pass inclusion demo"

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete the demo data first")

    ATOMIC_HANDLE = True

    def handle(self, *, reset, **options):
        # Redeploying a review app must not wipe what the audience did during the demo. Data seeded without the
        # demo prescriber has no orientation: it is recreated
        if not reset and Orientation.objects.filter(service__structure__uid=STRUCTURE_UID).exists():
            self.stdout.write("Données de démo déjà présentes, utiliser --reset pour les recréer.")
            return
        prescripteur = services.prescripteur_de_demo()
        if prescripteur is None:
            raise CommandError(
                f"Prescripteur de démo {services.DEMO_PRESCRIPTEUR_EMAIL} introuvable, lancer `make populate_db`."
            )
        Orientation.objects.filter(service__structure__uid=STRUCTURE_UID).delete()
        Offreur.objects.all().delete()
        Structure.include_inactive.filter(uid=STRUCTURE_UID).delete()
        User.objects.filter(email__endswith=demo.DEMO_EMAIL_DOMAIN).delete()
        User.objects.filter(email__in=[connecteurs.PERSONA_EMAIL, OFFREUR_EMAIL]).delete()
        self._seed(prescripteur)

    def _structure(self):
        dora = _reference(GenericReferenceItemKind.SOURCE, "dora")
        today = timezone.localdate()
        structure = Structure.objects.create(
            uid=STRUCTURE_UID,
            source=dora,
            name="Fondation Masse Trevidy Roulez Jeunesse",
            description=(
                "Roulez Jeunesse, porté par la Fondation Masse Trevidy, accompagne vers le permis de conduire les "
                "personnes pour qui la mobilité est un frein à l’emploi ou à la formation.\n\n"
                "Nos moniteurs sont formés à l’accompagnement des publics en insertion : rythme adapté, "
                "pédagogie individualisée, aide aux démarches de financement (CPF, aides de France Travail, "
                "du Département ou de la Région)."
            ),
            website="https://roulez-jeunesse.example.com",
            email="contact@roulez-jeunesse.example.com",
            phone="0320000000",
            opening_hours="Mo-Fr 09:00-12:00,14:00-18:00",
            accessibilite_lieu="https://acceslibre.beta.gouv.fr/",
            address_line_1="25 rue Nationale",
            post_code="59000",
            city="Lille",
            updated_on=today,
        )
        structure.reseaux_porteurs.set(GenericReferenceItem.objects.filter(kind="NETWORK", value="wimoov"))
        payant = _reference(GenericReferenceItemKind.FEE, "payant")
        presentiel = _reference(GenericReferenceItemKind.RECEPTION, "en-presentiel")
        for index, data in enumerate(SERVICES):
            service = Service.objects.create(
                uid=f"{STRUCTURE_UID}--{index}",
                source=dora,
                structure=structure,
                name=data["nom"],
                description=data["description"],
                kind=_reference(GenericReferenceItemKind.SERVICE_KIND, data["type"]),
                fee=payant,
                fee_details="Tarif solidaire selon les ressources",
                contact_email=structure.email,
                contact_phone=structure.phone,
                address_line_1=structure.address_line_1,
                post_code=structure.post_code,
                city=structure.city,
                updated_on=today,
            )
            service.thematics.set([_reference(GenericReferenceItemKind.THEMATIC, data["thematique"])])
            service.receptions.set([presentiel])
        return structure

    def _offreur(self, structure):
        offreur = Offreur.objects.create(
            name=structure.name,
            structure=structure,
            donnees_demandees=list(catalogue.DONNEES),
        )
        user = User.objects.create(
            username=User.generate_unique_username(),
            kind=UserKind.PROFESSIONAL,
            email=OFFREUR_EMAIL,
            first_name="Camille",
            last_name="Durand",
            identity_provider=IdentityProvider.PRO_CONNECT,
            terms_accepted_at=timezone.now(),
            first_login=timezone.now(),
        )
        demo.activer_connexion_par_bandeau(user)
        offreur.memberships.create(user=user, is_admin=True)
        return offreur

    def _bilan(self, accompagnement, auteur, rng):
        # The solution planned in the report matches the simulated situation 6 months later
        situation = accompagnement.situations.get(mois=6).situation
        solution = {
            SituationSuivi.Situation.EMPLOI: rng.choice(
                [ProSupportReportSolution.LASTING_JOB, ProSupportReportSolution.TRANSITIONAL_JOB]
            ),
            SituationSuivi.Situation.FORMATION: ProSupportReportSolution.TRAINING,
        }.get(situation, "")
        freins = [ProSupportReportBarrier.MOBILITY, ProSupportReportBarrier.DIGITAL, ProSupportReportBarrier.FAMILY]
        BilanIntervention.objects.create(
            accompagnement=accompagnement,
            auteur=auteur,
            created_at=accompagnement.ended_at,
            barriers=rng.sample(freins, k=rng.randint(0, 2)),
            autonomy=rng.randint(2, 5),
            solution=solution,
            orientation="" if solution else rng.choice(ProSupportReportOrientation.values),
        )

    def _seed(self, prescripteur):
        rng = random.Random(42)
        structure = self._structure()
        offreur = self._offreur(structure)
        # The demo prescriber account sends the orientations, so that they appear in its own lists
        sender = User.objects.get(email=services.DEMO_PRESCRIPTEUR_EMAIL)

        # Pending: activating her pass during the demo validates it
        persona = demo.job_seeker(connecteurs.PERSONA_EMAIL, "Sophie", "Leroy", Title.MME, datetime.date(1988, 3, 14))
        demo.activer_connexion_par_bandeau(persona)
        demo.orientation(structure, prescripteur, sender, persona, OrientationStatus.PENDING, rng, jours=5)
        for index, (first_name, last_name, title, status, jours) in enumerate(ORIENTES):
            beneficiary = demo.job_seeker(
                demo.email(first_name, last_name),
                first_name,
                last_name,
                title,
                datetime.date(1970 + 2 * index, 1 + index % 12, 1),
            )
            refus = demo.REFUS[index % len(demo.REFUS)]
            demo.orientation(structure, prescripteur, sender, beneficiary, status, rng, jours, refus)

        now = timezone.now()
        for index, (first_name, last_name, title, annee) in enumerate(ANCIENS):
            personne = demo.job_seeker(
                demo.email(first_name, last_name),
                first_name,
                last_name,
                title,
                datetime.date(annee, 1 + index % 12, 10),
            )
            cles = [*catalogue.DONNEES, catalogue.SUIVI_LONG]
            if index % 3 == 0:
                cles.append(catalogue.INFORMER_PRESCRIPTEUR)
            termine = index < len(ANCIENS) - AUTONOMES
            debut = now - relativedelta(months=rng.randint(14, 24))
            if termine:
                jours = (now - debut).days + 5
                demo.orientation(structure, prescripteur, sender, personne, OrientationStatus.ACCEPTED, rng, jours)
            accompagnement = services.accorder(personne, offreur, cles)
            Accompagnement.objects.filter(pk=accompagnement.pk).update(started_at=debut, vu_par_offreur=True)
            accompagnement.refresh_from_db()
            if termine:
                accompagnement.ended_at = debut + relativedelta(months=rng.randint(3, 8))
                accompagnement.save(update_fields=["ended_at"])
                services.simuler_suivi(accompagnement, rng=rng)
                self._bilan(accompagnement, offreur.members.get(), rng)
        # Old notifications were read long ago: the demo starts with the one of the persona only
        NotificationPrescripteur.objects.filter(accompagnement__offreur=offreur).update(lue_le=now)

        self.stdout.write("Données de démo créées (préfixer les URL par http://<IP du poste>:8000) :")
        self.stdout.write(f"  Offreur      : bandeau DEV > « Offreur de service » ({OFFREUR_EMAIL})")
        self.stdout.write(
            f"  Prescripteur : bandeau DEV > « Prescripteur habilité » ({services.DEMO_PRESCRIPTEUR_EMAIL})"
        )
        self.stdout.write(f"  Accueil (QR) : {reverse('inclusion_pass:accueil', args=[offreur.uuid_accueil])}")
        self.stdout.write(
            f"  Persona      : bandeau DEV > « Usager pass inclusion » ({connecteurs.PERSONA_EMAIL}), "
            "son orientation est validée à l’activation de son pass"
        )
        self.stdout.write(
            "  Public       : le bouton « Connexion simulée » de la page d’accueil crée un usager par appareil"
        )
