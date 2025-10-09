from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("asp", "0001_initial"),
        ("prescribers", "0001_initial"),
        ("users", "0038_fix_job_seeker_profile_birthdate"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="jobseekerprofile",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("birth_country", None), ("birth_place", None)),
                    models.Q(
                        ("birth_country__isnull", False), ("birth_country_id", 91), ("birth_place__isnull", False)
                    ),
                    models.Q(
                        models.Q(("birth_country__isnull", False), ("birth_country_id", 91), _negated=True),
                        models.Q(("birth_place__isnull", True)),
                    ),
                    _connector="OR",
                ),
                name="jobseekerprofile_birth_country_and_place",
                violation_error_message="La commune de naissance doit être spécifiée si et seulement si le pays de naissance est la France.",  # noqa: E501
            ),
        ),
    ]
