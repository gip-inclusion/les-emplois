from itou.users import admin
from itou.users.factories import JobSeekerFactory
from itou.users.models import JobSeekerProfile


def test_filter():
    js_certified = JobSeekerFactory()
    js_certified.jobseeker_profile.pe_obfuscated_nir = "PRINCEOFBELAIR"
    js_certified.jobseeker_profile.save()

    js_non_certified = JobSeekerFactory(jobseeker_profile__pe_obfuscated_nir=None)

    filter = admin.IsPECertifiedFilter(
        None,
        {"is_pe_certified": "yes"},
        JobSeekerProfile(),
        admin.JobSeekerProfileAdmin,
    )
    profiles = filter.queryset(None, JobSeekerProfile.objects.all())
    assert list(profiles) == [js_certified.jobseeker_profile]

    filter = admin.IsPECertifiedFilter(
        None,
        {"is_pe_certified": "no"},
        JobSeekerProfile(),
        admin.JobSeekerProfileAdmin,
    )
    profiles = filter.queryset(None, JobSeekerProfile.objects.all())
    assert list(profiles) == [js_non_certified.jobseeker_profile]

    filter = admin.IsPECertifiedFilter(
        None,
        {},
        JobSeekerProfile(),
        admin.JobSeekerProfileAdmin,
    )
    profiles = filter.queryset(None, JobSeekerProfile.objects.all())
    assert list(profiles) == list(JobSeekerProfile.objects.all())
