from rest_framework import serializers

from itou.users.models import User


class ApplicantSerializer(serializers.ModelSerializer):
    """Applicant serializer: job seeker field of a job application"""

    civilite = serializers.SerializerMethodField()
    nom = serializers.CharField(source="last_name")
    prenom = serializers.CharField(source="first_name")
    courriel = serializers.CharField(source="email")
    telephone = serializers.CharField(source="phone")
    adresse = serializers.CharField(source="address_line_1")
    complement_adresse = serializers.CharField(source="address_line_2")
    code_postal = serializers.CharField(source="post_code")
    ville = serializers.CharField(source="city")
    date_naissance = serializers.DateField(source="jobseeker_profile.birthdate")
    lieu_naissance = serializers.CharField(source="jobseeker_profile.birth_place")
    pays_naissance = serializers.CharField(source="jobseeker_profile.birth_country")
    lien_cv = serializers.CharField(default=None)  # Deprecated field
    uid_structures = serializers.ListField(child=serializers.CharField(), source="companies_uids")

    class Meta:
        model = User
        fields = (
            "civilite",
            "nom",
            "prenom",
            "courriel",
            "telephone",
            "adresse",
            "complement_adresse",
            "code_postal",
            "ville",
            "date_naissance",
            "lieu_naissance",
            "pays_naissance",
            "lien_cv",
            "uid_structures",
        )
        read_only_fields = fields

    def get_civilite(self, obj) -> str:
        return obj.title or "Non fournie"


class StringArrayField(serializers.ListField):
    def to_internal_value(self, data):
        data = data[0].split(",")  # convert string to list
        data = [d for d in data if d != ""]
        return super().to_internal_value(data)


class APIParametersSerializer(serializers.Serializer):
    mode_multi_structures = serializers.BooleanField(required=False)
    uid_structures = StringArrayField(child=serializers.CharField(), required=False)
