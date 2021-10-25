from django.utils import timezone

from itou.jobs.models import Appellation
from itou.siaes.models import SiaeJobDescription
from itou.www.siaes_views.forms import ValidateSiaeJobDescriptionForm


def refresh_card_list(request, siae):
    errors = {}
    jobs = {"create": [], "delete": [], "update": [], "unmodified": []}

    # Validate submitted data for jobs list: this is not the standard way to do things
    # and errors will not be shown at the field level.
    submitted_codes = set(request.POST.getlist("code"))
    for code in submitted_codes:
        data = {
            # Omit `SiaeJobDescription.appellation` since the field is
            # hidden and `Appellation.objects.get()` will fail anyway.
            "custom_name": request.POST.get(f"custom-name-{code}", ""),
            "description": request.POST.get(f"description-{code}", ""),
            "is_active": bool(request.POST.get(f"is_active-{code}")),
        }
        # We use a single ModelForm instance to validate each submitted group of data.
        form = ValidateSiaeJobDescriptionForm(data=data)
        if not form.is_valid():
            for key, value in form.errors.items():
                verbose_name = form.fields[key].label
                error = value[0]
                # The key of the dict is used in tests.
                errors[code] = f"{verbose_name} : {error}"

    if not errors:

        current_codes = set(siae.job_description_through.values_list("appellation__code", flat=True))
        codes_to_create = submitted_codes - current_codes
        # It is assumed that the codes to delete are not submitted (they must
        # be removed from the DOM via JavaScript). Instead, they are deducted.
        codes_to_delete = current_codes - submitted_codes
        codes_to_update = current_codes - codes_to_delete
        if codes_to_create or codes_to_delete or codes_to_update:
            # Create.
            for code in codes_to_create:
                appellation = Appellation.objects.get(code=code)
                through_defaults = {
                    "custom_name": request.POST.get(f"custom-name-{code}", ""),
                    "description": request.POST.get(f"description-{code}", ""),
                    "is_active": bool(request.POST.get(f"is_active-{code}")),
                    "created_at": timezone.now(),
                }
                jobs["create"].append(SiaeJobDescription(siae=siae, appellation=appellation, **through_defaults))
            # Delete.
            if codes_to_delete:
                jobs["delete"] = Appellation.objects.filter(code__in=codes_to_delete)

            # Update.
            for job_through in siae.job_description_through.filter(appellation__code__in=codes_to_update).order_by(
                "-updated_at", "-created_at"
            ):
                code = job_through.appellation.code
                new_custom_name = request.POST.get(f"custom-name-{code}", "")
                new_description = request.POST.get(f"description-{code}", "")
                new_is_active = bool(request.POST.get(f"is_active-{code}"))
                if (
                    job_through.custom_name != new_custom_name
                    or job_through.description != new_description
                    or job_through.is_active != new_is_active
                ):
                    job_through.custom_name = new_custom_name
                    job_through.description = new_description
                    job_through.is_active = new_is_active
                    job_through.updated_at = timezone.now()
                    jobs["update"].append(job_through)
                else:
                    # need to add unmodified for preview
                    jobs["unmodified"].append(job_through)
    return {
        "jobs": jobs,
        "errors": errors,
    }
