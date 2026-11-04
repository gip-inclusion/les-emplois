"""Fictitious data of the pass inclusion demo, shared by the `pass_demo_seed` command and the simulated login."""

import datetime
import random
import secrets

from allauth.account.models import EmailAddress
from django.utils import timezone
from django.utils.text import slugify

from itou.inclusion_pass import services
from itou.insertion.enums import OrientationRefusalReason, OrientationStatus
from itou.insertion.models import Orientation
from itou.job_applications.enums import SenderKind
from itou.users.enums import ActionKind, Title, UserKind
from itou.users.models import JobSeekerAssignment, User


DEMO_EMAIL_DOMAIN = "@pass-demo.example.com"
DEMO_PASSWORD = "password"

# Names of the people created by the simulated login, one per device of the audience
CALEMBOURS = [
    ("Otto", "Mobile", Title.M),
    ("Aimé", "Ploi", Title.M),
    ("Paul", "Emploi", Title.M),
    ("Pierre", "Kiroul", Title.M),
    ("Guy", "Don", Title.M),
    ("Lydie", "Plôme", Title.MME),
    ("Nordine", "Ateur", Title.M),
    ("Théo", "Courant", Title.M),
    ("Alain", "Provist", Title.M),
    ("Justin", "Temps", Title.M),
    ("Inès", "Péré", Title.MME),
    ("Hélène", "Ergie", Title.MME),
    ("Sam", "Suffit", Title.M),
    ("Annie", "Versaire", Title.MME),
    ("Jean", "Bon", Title.M),
    ("Alex", "Térieur", Title.M),
    ("Sarah", "Croche", Title.MME),
    ("Anna", "Lyse", Title.MME),
    ("Ali", "Gator", Title.M),
    ("Élie", "Kopter", Title.M),
    ("Otto", "Stop", Title.M),
    ("Jean", "Sérien", Title.M),
    ("Max", "Imum", Title.M),
    ("Rose", "Bonbon", Title.MME),
    ("Cécile", "Encieux", Title.MME),
    ("Sarah", "Pelle", Title.MME),
    ("Paul", "Ochon", Title.M),
    ("Lara", "Tatouille", Title.MME),
    ("Clément", "Tine", Title.M),
    ("Laurie", "Zon", Title.MME),
    ("Agathe", "Zeblouse", Title.MME),
    ("Thérèse", "Ponsable", Title.MME),
    ("Marie", "Nade", Title.MME),
    ("Camille", "Onaire", Title.MME),
    ("Gérard", "Menvussa", Title.M),
    ("Sacha", "Touille", Title.M),
]

REFUS = [
    (OrientationRefusalReason.NOT_REACHABLE, "Trois appels sans réponse."),
    (OrientationRefusalReason.SESSION_FULL, "La session de mars est complète, à réorienter vers celle de mai."),
    (OrientationRefusalReason.HIRED_ELSEWHERE, "Un emploi a été trouvé entre-temps."),
]


def email(first_name, last_name, suffix=""):
    return f"{slugify(f'{first_name} {last_name}').replace('-', '.')}{suffix}{DEMO_EMAIL_DOMAIN}"


def job_seeker(email, first_name, last_name, title, birthdate):
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


def activer_connexion_par_bandeau(user):
    """Let the user log in from the demo banner, which sends the demo password."""
    user.set_password(DEMO_PASSWORD)
    user.save(update_fields=["password"])
    EmailAddress.objects.create(user=user, email=user.email, verified=True, primary=True)


def orientation(structure, prescripteur, sender, beneficiary, status, rng, jours, refus=REFUS[0]):
    """Create an orientation sent `jours` days ago by the demo prescriber, processed as `status`."""
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
    # A queryset update() bypasses auto_now: "Mise à jour le" follows the processing date
    updates = {"created_at": created_at, "updated_at": created_at}
    if status == OrientationStatus.ACCEPTED:
        processing_date = created_at + datetime.timedelta(days=2)
        updates |= {"status": status, "processing_date": processing_date, "updated_at": processing_date}
    elif status == OrientationStatus.REFUSED:
        processing_date = created_at + datetime.timedelta(days=3)
        reason, details = refus
        updates |= {
            "status": status,
            "processing_date": processing_date,
            "updated_at": processing_date,
            "refusal_reasons": [reason],
            "refusal_details": details,
        }
    Orientation.objects.filter(pk=orientation.pk).update(**updates)
    # As in insertion_views: the sender now follows the person, who appears in its job seekers list
    JobSeekerAssignment.objects.upsert_assignment(beneficiary, sender, prescripteur, ActionKind.ORIENT)
    JobSeekerAssignment.objects.filter(job_seeker=beneficiary, professional=sender).update(
        created_at=created_at, last_action_at=created_at, updated_at=created_at
    )
    return orientation


def creer_visiteur(offreur=None):
    """Create a new person for a device of the audience, with a pun name not taken yet when possible.

    When the person comes from the reception QR code of an offreur, the demo prescriber orients them to it first:
    activating the pass then validates the orientation, as for the demo persona.
    """
    pris = set(User.objects.filter(email__endswith=DEMO_EMAIL_DOMAIN).values_list("first_name", "last_name"))
    libres = [nom for nom in CALEMBOURS if nom[:2] not in pris]
    first_name, last_name, title = random.choice(libres or CALEMBOURS)
    birthdate = datetime.date(random.randint(1965, 2005), random.randint(1, 12), random.randint(1, 28))
    visiteur = job_seeker(
        email(first_name, last_name, f".{secrets.token_hex(3)}"), first_name, last_name, title, birthdate
    )
    prescripteur = services.prescripteur_de_demo()
    if offreur and prescripteur and offreur.structure.services.exists():
        sender = User.objects.get(email=services.DEMO_PRESCRIPTEUR_EMAIL)
        orientation(offreur.structure, prescripteur, sender, visiteur, OrientationStatus.PENDING, random, jours=0)
    return visiteur
