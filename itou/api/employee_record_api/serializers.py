from random import randint
from typing import OrderedDict

from django.conf import settings
from django.utils.crypto import salted_hmac
from rest_framework import serializers

from itou.employee_record.models import EmployeeRecord
from itou.employee_record.serializers import EmployeeRecordSerializer, _EmployeeAddressSerializer, _EmployeeSerializer
from itou.users.models import User


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


# Employee record serializer is mostly the same as the one used
# for serialization transfers.
# Except some fields are "unobfuscated" and added for third-party
# software connecting to the API.


class _API_EmployeeAddressSerializer(_EmployeeAddressSerializer):
    """
    This class in only useful for compatibility.
    We decided not to send phone and email (business concerns and bad ASP address filters).
    But we make it available in the API for compatibility with original document
    (these fields should really be actual data, not fake, by implicit contract).
    """

    def _update_address_and_phone_number(self, result, instance) -> OrderedDict:
        """
        Allow overriding these 2 fields:
        - adrTelephone
        - adrMail
        Make data readable again for API users.
        """
        result["adrTelephone"] = instance.phone
        result["adrMail"] = instance.email

        return result


class _API_EmployeeSerializer(_EmployeeSerializer):
    """
    Specific fields added to the API (not used in ASP transfers)
    """

    NIR = serializers.CharField(source="nir")

    class Meta:
        model = User
        fields = [
            "sufPassIae",
            "idItou",
            "NIR",
            "civilite",
            "nomUsage",
            "prenom",
            "dateNaissance",
            "codeComInsee",
            "codeDpt",
            "codeInseePays",
            "codeGroupePays",
        ]


class EmployeeRecordAPISerializer(EmployeeRecordSerializer):
    """
    This serializer is a version with the `numeroAnnexe` field added (financial annex number).

    This field not needed by ASP was simply ignored in earlier versions of the
    main SFTP serializer but was removed for RGPD concerns.
    """

    numeroAnnexe = serializers.CharField(source="financial_annex_number")
    adresse = _API_EmployeeAddressSerializer(source="job_application.job_seeker")
    personnePhysique = _API_EmployeeSerializer(source="job_application.job_seeker")

    class Meta:
        model = EmployeeRecord
        fields = [
            "passIae",
            "passDateDeb",
            "passDateFin",
            "numLigne",
            "typeMouvement",
            "numeroAnnexe",
            "mesure",
            "siret",
            "personnePhysique",
            "adresse",
            "situationSalarie",
            "codeTraitement",
            "libelleTraitement",
        ]
        read_only_fields = fields
