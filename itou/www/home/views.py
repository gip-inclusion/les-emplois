from django.shortcuts import render

from itou.www.search.forms import SiaeSearchForm


def home(request, template_name="home/home.html"):
    context = {"siae_search_form": SiaeSearchForm(initial={"distance": SiaeSearchForm.DISTANCE_DEFAULT})}
    return render(request, template_name, context)


def trigger_error(request):
    print(1 / 0)  # Should raise a ZeroDivisionError.
