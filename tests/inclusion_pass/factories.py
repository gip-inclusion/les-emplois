import factory

from itou.companies.enums import ProSupportReportAutonomy, ProSupportReportSolution
from itou.inclusion_pass import catalogue
from itou.inclusion_pass.models import (
    AccesDonnee,
    Accompagnement,
    BilanIntervention,
    Consentement,
    DonneePartagee,
    NotificationPrescripteur,
    Offreur,
    OffreurMembership,
    SituationSuivi,
)


class OffreurFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Offreur
        skip_postgeneration_save = True

    name = factory.Sequence("Auto-école test {}".format)
    structure = factory.SubFactory("tests.insertion.factories.StructureFactory")
    donnees_demandees = factory.LazyFunction(lambda: list(catalogue.DONNEES))

    @factory.post_generation
    def with_member(self, create, extracted, **kwargs):
        if create and extracted:
            OffreurMembershipFactory(offreur=self, is_admin=True)


class OffreurMembershipFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = OffreurMembership

    offreur = factory.SubFactory(OffreurFactory)
    user = factory.SubFactory("tests.users.factories.ProfessionalFactory")


class AccompagnementFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Accompagnement

    personne = factory.SubFactory("tests.users.factories.JobSeekerFactory")
    offreur = factory.SubFactory(OffreurFactory)


class ConsentementFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Consentement

    personne = factory.SubFactory("tests.users.factories.JobSeekerFactory")
    offreur = factory.SubFactory(OffreurFactory)
    donnee = catalogue.IDENTITE


class DonneePartageeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DonneePartagee

    personne = factory.SubFactory("tests.users.factories.JobSeekerFactory")
    donnee = catalogue.EMAIL
    valeur = factory.LazyAttribute(lambda obj: {"texte": obj.personne.email})
    source = "franceconnect"


class AccesDonneeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AccesDonnee

    personne = factory.SubFactory("tests.users.factories.JobSeekerFactory")
    offreur = factory.SubFactory(OffreurFactory)
    donnee = catalogue.IDENTITE
    action = AccesDonnee.Action.OCTROI


class SituationSuiviFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SituationSuivi

    accompagnement = factory.SubFactory(AccompagnementFactory)
    mois = 3
    situation = SituationSuivi.Situation.EMPLOI


class NotificationPrescripteurFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = NotificationPrescripteur

    prescripteur = factory.SubFactory("tests.prescribers.factories.PrescriberOrganizationFactory")
    accompagnement = factory.SubFactory(AccompagnementFactory)
    message = "Votre orientation a abouti."


class BilanInterventionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = BilanIntervention

    accompagnement = factory.SubFactory(AccompagnementFactory)
    auteur = factory.SubFactory("tests.users.factories.ProfessionalFactory")
    barriers = factory.LazyFunction(list)
    autonomy = ProSupportReportAutonomy.OCCASIONAL_SUPPORT
    solution = ProSupportReportSolution.TRAINING
