from django.http import Http404, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse

from itou.utils.apis.api_entreprise import Etablissement
from itou.utils.apis.geocoding import get_geocoding_data
from itou.www.search.forms import SiaeSearchForm


def home(request, template_name="home/home.html"):
    context = {"siae_search_form": SiaeSearchForm()}
    return render(request, template_name, context)


def trigger_error(request):
    print(1 / 0)  # Should raise a ZeroDivisionError.


def tmp_test_siret(request, template_name="home/tmp_test_siret.html"):

    siret = request.GET.get("siret")
    etablissement = None
    coords = None

    if siret:

        if not siret.isdigit() or len(siret) != 14:
            raise Http404()

        etablissement = Etablissement(siret)

        address_fields = [
            etablissement.address_line_1,
            etablissement.address_line_2,
            etablissement.post_code,
            etablissement.city,
            etablissement.department,
        ]
        address_on_one_line = ", ".join([field for field in address_fields if field])

        geocoding_data = get_geocoding_data(address_on_one_line, post_code=etablissement.post_code)
        coords = geocoding_data["coords"]

    context = {"etablissement": etablissement, "coords": coords, "siret": siret}
    return render(request, template_name, context)
