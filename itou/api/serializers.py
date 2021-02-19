from random import randint

from django.conf import settings
from django.utils.crypto import salted_hmac
from rest_framework import serializers

from itou.siaes.models import Siae


class SiaeSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = Siae
        fields = ["kind", "siret", "source"]


class DummyEmployeeRecordSerializer(serializers.Serializer):
    """
    Fake serializer always returning the same preset json with some random variation.

    See README-FS-SSII.md for a detailed documentation of all the json fields.

    Field documentation is *not* duplicated here, to stay as DNRY as possible.
    """

    def to_representation(self, instance):
        # Random integer always having exactly 5 digits.
        rnd = randint(10000, 99999)
        physical_person = {
            "passIae": f"9999900{rnd}",
            "sufPassIae": None,
            "idItou": salted_hmac(
                key_salt="job_seeker.id",
                # rnd is supposed to be job_seeker.id
                value=rnd,
                secret=settings.SECRET_KEY,
            ).hexdigest()[:30],
            "civilite": "M",
            "nomUsage": "DECAILLOUX",
            "nomNaissance": None,
            "prenom": "YVES",
            "dateNaissance": "01/08/1954",
            "codeComInsee": {
                "codeComInsee": "34172",
                "codeDpt": "034",
            },
            "codeInseePays": "100",
            "codeGroupePays": "1",
        }

        address = {
            "adrTelephone": f"01000{rnd}",
            "adrMail": f"john.doe.{rnd}@gmail.com",
            "adrNumeroVoie": None,
            "codeextensionvoie": None,
            "codetypevoie": "AV",
            "adrLibelleVoie": "AVENUE ABBE PAUL PARGUEL",
            "adrCpltDistribution": None,
            "codeinseecom": "34172",
            "codepostalcedex": "34000",
        }

        job_seeker_situation = {
            "orienteur": "01",
            "niveauFormation": "00",
            "salarieEnEmploi": False,
            "salarieTypeEmployeur": None,
            "salarieSansEmploiDepuis": "04",
            "salarieSansRessource": False,
            "inscritPoleEmploi": True,
            "inscritPoleEmploiDepuis": "04",
            "numeroIDE": f"11{rnd}A",
            "salarieRQTH": False,
            "salarieOETH": False,
            "salarieAideSociale": False,
            "salarieBenefRSA": "NON",
            "salarieBenefRSADepuis": None,
            "salarieBenefASS": False,
            "salarieBenefASSDepuis": None,
            "salarieBenefAAH": False,
            "salarieBenefAAHDepuis": None,
            "salarieBenefATA": False,
            "salarieBenefATADepuis": None,
        }

        fiche_salarie = {
            "mesure": "ACI_DC",
            "siret": f"330550393{rnd}",
            "numeroAnnexe": f"ACI0232{rnd}A0M0",
            "personnePhysique": physical_person,
            "adresse": address,
            "situationSalarie": job_seeker_situation,
        }

        return fiche_salarie
