import urllib.parse

from django.db import migrations
from django.db.models import Value
from django.db.models.functions import Replace


def forwards(apps, editor):
    PrescriberOrganization = apps.get_model("prescribers", "PrescriberOrganization")

    PrescriberOrganization.objects.filter(email__endswith="@pole-emploi.fr").update(
        email=Replace("email", Value("@pole-emploi.fr"), Value("@francetravail.fr"))
    )

    PE_PATH = "/votre-pole-emploi/"
    FT_PATH = "/votre-agence-francetravail/"
    orgs = []
    for org in PrescriberOrganization.objects.filter(website__icontains="pole-emploi.fr"):
        website_bits = urllib.parse.urlsplit(org.website)
        website_bits = website_bits._replace(scheme="https")
        website_bits = website_bits._replace(netloc="www.francetravail.fr")
        if PE_PATH in website_bits.path:
            website_bits = website_bits._replace(path=website_bits.path.replace(PE_PATH, FT_PATH))
        org.website = urllib.parse.urlunsplit(website_bits)
        orgs.append(org)
    PrescriberOrganization.objects.bulk_update(orgs, fields=["website"])

    PrescriberOrganization.objects.filter(
        website__icontains="pole-emploi.org",
    ).update(website="https://www.francetravail.org/accueil/")


class Migration(migrations.Migration):
    dependencies = [
        ("prescribers", "0003_set_prescriber_organizations_active_members_email_reminder_last_sent_at"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop, elidable=True),
    ]
