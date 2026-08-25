from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("insertion", "0012_alter_orientation_status_orientationtransitionlog"),
    ]

    operations = [
        migrations.RenameField(
            model_name="service",
            old_name="mobilization_modes_professionals_external_form_link",
            new_name="mobilization_link",
        ),
        migrations.AlterField(
            model_name="service",
            name="mobilization_link",
            field=models.URLField(blank=True, max_length=2000, verbose_name="lien de mobilisation"),
        ),
    ]
