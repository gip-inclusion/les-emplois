# Generated by Django 4.1.9 on 2023-06-09 09:14

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("france_connect", "0004_alter_franceconnectstate_created_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="franceconnectstate",
            name="state",
            field=models.CharField(max_length=12, null=True, unique=True),
        ),
    ]