from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="ProbeStatus",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.TextField(unique=True)),
                ("last_success_at", models.DateTimeField(null=True)),
                ("last_success_info", models.TextField(null=True)),
                ("last_failure_at", models.DateTimeField(null=True)),
                ("last_failure_info", models.TextField(null=True)),
            ],
        ),
    ]
