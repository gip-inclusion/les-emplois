# Generated by Django 5.0.6 on 2024-06-20 15:48

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0002_alter_companyapitoken_companies_companytoken"),
    ]

    operations = [
        migrations.DeleteModel(
            name="CompanyApiToken",
        ),
    ]
