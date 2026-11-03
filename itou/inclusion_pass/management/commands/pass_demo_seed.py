import datetime
import random

from allauth.account.models import EmailAddress
from dateutil.relativedelta import relativedelta
from django.urls import reverse
from django.utils import timezone

from itou.inclusion_pass import catalogue, connecteurs, services
from itou.inclusion_pass.models import Accompagnement, Offreur
from itou.insertion.enums import GenericReferenceItemKind, OrientationRefusalReason, OrientationStatus
from itou.insertion.models import GenericReferenceItem, Orientation, Service, Structure
from itou.job_applications.enums import SenderKind
from itou.users.enums import IdentityProvider, Title, UserKind
from itou.users.models import User
from itou.utils.command import BaseCommand


DEMO_EMAIL_DOMAIN = "@pass-demo.example.com"
OFFREUR_EMAIL = "demo.emplois+offreur@inclusion.gouv.fr"
STRUCTURE_UID = "pass-demo--auto-ecole-solidaire"

# Fictitious people for a non-empty follow-up list and impact report: name, title, birth year
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
]

# Orientations received by the structure, besides the persona's one: name, title, status
ORIENTES = [
    ("Inès", "Faure", Title.MME, OrientationStatus.PENDING),
    ("Lucas", "Mercier", Title.M, OrientationStatus.PENDING),
    ("Nadia", "Bouzid", Title.MME, OrientationStatus.ACCEPTED),
    ("Hugo", "Lemoine", Title.M, OrientationStatus.REFUSED),
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


def _job_seeker(email, first_name, last_name, title, birthdate):
    user = User.objects.create(
        username=User.generate_unique_username(),
        kind=UserKind.JOB_SEEKER,
        email=email,
        first_name=first_name,
        last_name=last_name,
        title=title,
        address_line_1="12 rue des Lilas",
        post_code="59000",
        city="Lille",
    )
    user.jobseeker_profile.birthdate = birthdate
    user.jobseeker_profile.save(update_fields=["birthdate"])
    return user


def _reference(kind, value):
    return GenericReferenceItem.objects.get(kind=kind, value=value)


class Command(BaseCommand):
    help = "Create (or recreate with --reset) the fictitious data of the pass inclusion demo"

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete the demo data first")

    ATOMIC_HANDLE = True

    def handle(self, *, reset, **options):
        if reset:
            Orientation.objects.filter(service__structure__uid=STRUCTURE_UID).delete()
            Offreur.objects.all().delete()
            Structure.include_inactive.filter(uid=STRUCTURE_UID).delete()
            User.objects.filter(email__endswith=DEMO_EMAIL_DOMAIN).delete()
            User.objects.filter(email__in=[connecteurs.PERSONA_EMAIL, OFFREUR_EMAIL]).delete()
        self._seed()

    def _structure(self):
        dora = _reference(GenericReferenceItemKind.SOURCE, "dora")
        today = timezone.localdate()
        structure = Structure.objects.create(
            uid=STRUCTURE_UID,
            source=dora,
            name="Auto-école solidaire (démo)",
            description=(
                "L’Auto-école solidaire accompagne vers le permis de conduire les personnes pour qui la mobilité "
                "est un frein à l’emploi ou à la formation.\n\n"
                "Nos moniteurs sont formés à l’accompagnement des publics en insertion : rythme adapté, "
                "pédagogie individualisée, aide aux démarches de financement (CPF, aides de France Travail, "
                "du Département ou de la Région)."
            ),
            website="https://auto-ecole-solidaire.example.com",
            email="contact@auto-ecole-solidaire.example.com",
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
        user.set_password("password")
        user.save(update_fields=["password"])
        EmailAddress.objects.create(user=user, email=user.email, verified=True, primary=True)
        offreur.memberships.create(user=user, is_admin=True)
        return offreur

    def _orientation(self, structure, prescripteur, beneficiary, status, rng, jours):
        sender = prescripteur.active_members.first()
        orientation = Orientation.objects.create(
            beneficiary=beneficiary,
            sender=sender,
            sender_kind=SenderKind.PRESCRIBER,
            sender_prescriber_organization=prescripteur,
            service=rng.choice(list(structure.services.all())),
            referent_first_name=sender.first_name,
            referent_last_name=sender.last_name,
            referent_email=sender.email,
            orientation_reasons="La mobilité est le principal frein à la reprise d’emploi.",
            data_protection_commitment=True,
        )
        created_at = timezone.now() - datetime.timedelta(days=jours)
        updates = {"created_at": created_at}
        if status == OrientationStatus.ACCEPTED:
            updates |= {"status": status, "processing_date": created_at + datetime.timedelta(days=2)}
        elif status == OrientationStatus.REFUSED:
            updates |= {
                "status": status,
                "processing_date": created_at + datetime.timedelta(days=3),
                "refusal_reasons": [OrientationRefusalReason.NOT_REACHABLE],
                "refusal_details": "Trois appels sans réponse.",
            }
        Orientation.objects.filter(pk=orientation.pk).update(**updates)
        return orientation

    def _seed(self):
        rng = random.Random(42)
        structure = self._structure()
        offreur = self._offreur(structure)
        prescripteur = services.prescripteur_de_demo()

        persona = _job_seeker(connecteurs.PERSONA_EMAIL, "Sophie", "Leroy", Title.MME, datetime.date(1988, 3, 14))
        if prescripteur:
            self._orientation(structure, prescripteur, persona, OrientationStatus.PENDING, rng, jours=5)
            for index, (first_name, last_name, title, status) in enumerate(ORIENTES):
                beneficiary = _job_seeker(
                    f"{first_name.lower()}.{last_name.lower()}{DEMO_EMAIL_DOMAIN}",
                    first_name,
                    last_name,
                    title,
                    datetime.date(1990 + index, 6, 1),
                )
                self._orientation(structure, prescripteur, beneficiary, status, rng, jours=2 + 4 * index)

        now = timezone.now()
        for index, (first_name, last_name, title, annee) in enumerate(ANCIENS):
            personne = _job_seeker(
                f"{first_name.lower()}.{last_name.lower()}{DEMO_EMAIL_DOMAIN}",
                first_name,
                last_name,
                title,
                datetime.date(annee, 1 + index, 10),
            )
            cles = [*catalogue.DONNEES, catalogue.SUIVI_LONG]
            if index % 3 == 0:
                cles.append(catalogue.INFORMER_PRESCRIPTEUR)
            accompagnement = services.accorder(personne, offreur, cles, prescripteur_par_defaut=prescripteur)
            debut = now - relativedelta(months=rng.randint(14, 24))
            Accompagnement.objects.filter(pk=accompagnement.pk).update(started_at=debut, vu_par_offreur=True)
            accompagnement.refresh_from_db()
            if index < 7:
                accompagnement.ended_at = debut + relativedelta(months=rng.randint(3, 8))
                accompagnement.save(update_fields=["ended_at"])
                services.simuler_suivi(accompagnement, rng=rng)

        self.stdout.write("Données de démo créées (préfixer les URL par http://<IP du poste>:8000) :")
        self.stdout.write(f"  Offreur      : bandeau DEV > « Offreur de service » ({OFFREUR_EMAIL})")
        self.stdout.write(
            f"  Prescripteur : bandeau DEV > « Prescripteur habilité » ({services.DEMO_PRESCRIPTEUR_EMAIL})"
        )
        self.stdout.write(f"  Accueil (QR) : {reverse('inclusion_pass:accueil', args=[offreur.uuid_accueil])}")
        self.stdout.write(
            f"  Persona      : {connecteurs.PERSONA_EMAIL} (bouton « Connexion simulée » sur la page d’accueil)"
        )
