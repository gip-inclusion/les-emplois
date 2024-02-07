from rest_framework import serializers

from itou.employee_record.serializers import EmployeeRecordSerializer, _AddressSerializer, _PersonSerializer


# Employee record serializer is mostly the same as the one used
# for serialization transfers.
# Except some fields are "unobfuscated" and added for third-party
# software connecting to the API.


class _API_AddressSerializer(_AddressSerializer):
    """
    This class in only useful for compatibility.
    We decided not to send phone and email (business concerns and bad ASP address filters).
    But we make it available in the API for compatibility with original document
    (these fields should really be actual data, not fake, by implicit contract).
    """

    adrTelephone = serializers.CharField(source="phone")
    adrMail = serializers.CharField(source="email")


class _API_PersonSerializer(_PersonSerializer):
    """
    Specific fields added to the API (not used in ASP transfers)
    """

    NIR = serializers.CharField(source="job_seeker.jobseeker_profile.nir")


class EmployeeRecordAPISerializer(EmployeeRecordSerializer):
    """
    This serializer is a version with the `numeroAnnexe` field added (financial annex number).

    This field not needed by ASP was simply ignored in earlier versions of the
    main SFTP serializer but was removed for RGPD concerns.
    """

    numeroAnnexe = serializers.CharField(source="financial_annex_number")
    adresse = _API_AddressSerializer(source="job_seeker")
    personnePhysique = _API_PersonSerializer(source="*")
