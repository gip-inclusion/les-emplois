from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0012_user_lack_of_nir_reason_and_more"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="user",
            constraint=models.CheckConstraint(
                check=models.Q(
                    ("kind", "itou_staff"),
                    ("kind", "job_seeker"),
                    ("kind", "prescriber"),
                    ("kind", "siae_staff"),
                    ("kind", "labor_inspector"),
                    _connector="OR",
                ),
                name="has_kind",
                violation_error_message="Le type d’utilisateur est incorrect.",
            ),
        ),
    ]
