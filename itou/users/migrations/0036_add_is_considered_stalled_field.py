import django.db.models.expressions
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("asp", "0008_update_commune_lomme"),
        ("prescribers", "0015_drop_is_head_office_for_real"),
        ("users", "0035_add_is_not_stalled_anymore_field"),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name="jobseekerprofile",
            name="users_jobseeker_stalled_idx",
        ),
        migrations.AddField(
            model_name="jobseekerprofile",
            name="is_considered_stalled",
            field=models.GeneratedField(
                db_persist=True,
                expression=django.db.models.expressions.RawSQL(
                    '"is_stalled" AND NOT ("is_not_stalled_anymore" AND "is_not_stalled_anymore" IS NOT NULL)', {}
                ),
                output_field=models.BooleanField(),
                verbose_name="candidat considéré comme sans solution (données et utilisateurs)",
            ),
        ),
        migrations.AddIndex(
            model_name="jobseekerprofile",
            index=models.Index(
                condition=models.Q(("is_considered_stalled", True)),
                fields=["is_considered_stalled"],
                name="users_jobseeker_stalled_idx",
            ),
        ),
    ]
