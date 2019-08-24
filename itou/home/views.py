from django.shortcuts import render

from itou.siaes.forms import SiaeSearchForm


def home(request, template_name="home.html"):
    context = {"siae_search_form": SiaeSearchForm()}
    return render(request, template_name, context)
