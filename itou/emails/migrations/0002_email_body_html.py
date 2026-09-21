from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("emails", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="email",
            name="body_html",
            field=models.TextField(blank=True, db_default="", default="", verbose_name="message HTML"),
        ),
    ]
