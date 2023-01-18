from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0005_alter_user_last_checked_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="asp_uid",
            field=models.TextField(
                blank=True, max_length=30, null=True, unique=True, verbose_name="ID unique envoyé à l'ASP"
            ),
        ),
    ]
