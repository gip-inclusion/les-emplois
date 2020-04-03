from django.shortcuts import render

from itou.utils.version_achat import disable_version_achat, enable_version_achat, is_version_achat_enabled
from itou.www.search.forms import SiaeSearchForm


def get_home_context(request):
    return {"siae_search_form": SiaeSearchForm(is_version_achat_enabled=is_version_achat_enabled(request))}


def home(request, template_name="home/home.html"):
    disable_version_achat(request)
    return render(request, template_name, get_home_context(request))


def home_achat(request, template_name="home/home.html"):
    enable_version_achat(request)
    return render(request, template_name, get_home_context(request))


def trigger_error(request):
    print(1 / 0)  # Should raise a ZeroDivisionError.
