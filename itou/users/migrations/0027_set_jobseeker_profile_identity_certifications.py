import logging
import time
from itertools import batched

from django.db import migrations


logger = logging.getLogger(__name__)

API_RECHERCHE_INDIVIDU_CERTIFIE = "api_recherche_individu_certifie"
API_PARTICULIER = "api_particulier"


def forwards(apps, editor):
    JobSeekerProfile = apps.get_model("users", "JobSeekerProfile")
    IdentityCertification = apps.get_model("users", "IdentityCertification")
    SelectedAdministrativeCriteria = apps.get_model("eligibility", "SelectedAdministrativeCriteria")

    print()

    total = 0
    batch_size = 10_000
    for batch in batched(
        JobSeekerProfile.objects.exclude(pe_obfuscated_nir=None).values_list("pk", flat=True),
        batch_size,
    ):
        start = time.perf_counter()
        identity_certifications = []
        for profile in JobSeekerProfile.objects.filter(pk__in=batch):
            identity_certifications.append(
                IdentityCertification(
                    certifier=API_RECHERCHE_INDIVIDU_CERTIFIE,
                    jobseeker_profile=profile,
                    certified_at=profile.pe_last_certification_attempt_at,
                )
            )
        IdentityCertification.objects.bulk_create(identity_certifications, ignore_conflicts=True)
        total += len(identity_certifications)
        logger.info(
            "Wrote %d France Travail certifications in %.2fs.",
            total,
            time.perf_counter() - start,
        )
        if len(batch) == batch_size:
            time.sleep(2)
    # Handle identity certifications removed while the table was being populated.
    IdentityCertification.objects.filter(
        certifier=API_RECHERCHE_INDIVIDU_CERTIFIE,
        jobseeker_profile__pe_obfuscated_nir=None,
    ).delete()

    profile_identity_certifications = {}
    start = time.perf_counter()
    for criteria in SelectedAdministrativeCriteria.objects.exclude(certified=None).select_related(
        "eligibility_diagnosis__job_seeker__jobseeker_profile"
    ):
        profile = criteria.eligibility_diagnosis.job_seeker.jobseeker_profile
        identity_certification = IdentityCertification(
            certifier=API_PARTICULIER,
            jobseeker_profile=profile,
            certified_at=criteria.certified_at,
        )
        try:
            existing = profile_identity_certifications[profile.pk]
        except KeyError:
            profile_identity_certifications[profile.pk] = identity_certification
        else:
            existing.certified_at = max(existing.certified_at, criteria.certified_at)
    IdentityCertification.objects.bulk_create(profile_identity_certifications.values(), ignore_conflicts=True)
    logger.info(
        "Wrote %d API particulier certifications in %.2f.",
        len(profile_identity_certifications),
        time.perf_counter() - start,
    )


class Migration(migrations.Migration):
    atomic = False
    dependencies = [
        ("eligibility", "0011_update_geiqeligibilitydiagnosis_author_kind_coherence"),
        ("users", "0026_identitycertification"),
    ]

    operations = [migrations.RunPython(forwards, elidable=True)]
