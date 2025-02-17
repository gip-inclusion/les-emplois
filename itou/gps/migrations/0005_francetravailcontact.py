# Generated by Django 5.0.8 on 2024-08-14 11:51

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("gps", "0004_alter_followupgroup_created_at_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="FranceTravailContact",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255)),
                ("email", models.EmailField(max_length=254)),
                (
                    "jobseeker_profile",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="advisor_information",
                        to="users.jobseekerprofile",
                        verbose_name="profil",
                    ),
                ),
            ],
            options={
                "verbose_name": "conseiller France Travail",
                "verbose_name_plural": "conseillers FT",
            },
        ),
    ]
