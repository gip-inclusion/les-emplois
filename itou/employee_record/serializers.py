from rest_framework import serializers

from itou.employee_record.models import EmployeeRecord
from itou.users.models import JobSeekerProfile, User


class _EmployeeSerializer(serializers.ModelSerializer):

    idItou = serializers.IntegerField(source="id")

    civilite = serializers.ChoiceField(choices=User.Title.choices, source="title")
    nomUsage = serializers.CharField(source="last_name")
    prenom = serializers.CharField(source="first_name")

    dateNaissance = serializers.DateField(format="%d/%m/%Y", source="birthdate")
    codeComInsee = serializers.IntegerField(source="birth_place.code")
    # TBD birth dpt
    codeInseePays = serializers.IntegerField(source="birth_country.code")
    # Nationalité TBD
    codeGroupePays = serializers.IntegerField(source="birth_country.group")

    class Meta:
        model = User
        fields = [
            "idItou",
            "civilite",
            "nomUsage",
            "prenom",
            "dateNaissance",
            "codeComInsee",
            "codeInseePays",
            "codeGroupePays",
        ]


class _EmployeeAddress(serializers.ModelSerializer):

    adrTelephone = serializers.CharField(source="phone")
    adrEmail = serializers.CharField(source="email")

    # TBD optional fields ?
    adrPointRemise = ""
    adrCpltPointGeo = ""

    adrNumeroVoie = serializers.CharField(source="jobseeker_profile.hexa_lane_number")
    codeextensionVoie = serializers.CharField(source="jobseeker_profile.hexa_std_extension")
    codetypeVoie = serializers.CharField(source="jobseeker_profile.hexa_lane_type")
    adrLibelleVoie = serializers.CharField(source="jobseeker_profile.hexa_lane_name")

    # TBD: double check coherence with ASP ref file
    codeinseecom = serializers.IntegerField(source="jobseeker_profile.hexa_commune.code")
    codepostalcedex = serializers.CharField(source="jobseeker_profile.hexa_post_code")

    class Meta:
        model = User
        fields = [
            "adrTelephone",
            "adrEmail",
            "adrNumeroVoie",
            "codeextensionVoie",
            "codetypeVoie",
            "adrLibelleVoie",
            "codeinseecom",
            "codepostalcedex",
        ]


class EmployeeRecordSerializer(serializers.ModelSerializer):

    passIae = serializers.CharField(max_length=12, source="approval_number")
    personnePhysique = _EmployeeSerializer(source="job_application.job_seeker")
    adresse = _EmployeeAddress(source="job_application.job_seeker")

    class Meta:
        model = EmployeeRecord
        fields = ["passIae", "personnePhysique", "adresse"]
        read_only_fields = fields
