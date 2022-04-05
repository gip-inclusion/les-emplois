import logging

from django.shortcuts import render

from itou.siaes.models import SiaeJobDescription
from itou.www.search.forms import PrescriberSearchForm, SiaeSearchForm


logger = logging.getLogger(__name__)


def home(request, template_name="home/home.html"):
    siae_jobs = SiaeJobDescription.objects.filter(is_active=True).order_by("-updated_at").all()[:6]
    siae_jobs_count = SiaeJobDescription.objects.filter(is_active=True).count()
    context = {
        "siae_jobs_count": siae_jobs_count,
        "siae_jobs": siae_jobs,
        "siae_search_form": SiaeSearchForm(),
        "prescribers_search_form": PrescriberSearchForm(),
    }
    return render(request, template_name, context)


def trigger_error(request):
    if request.POST:
        raise Exception("%s error: %s" % (request.POST.get("status_code"), request.POST.get("error_message")))

    print(1 / 0)  # Should raise a ZeroDivisionError.
