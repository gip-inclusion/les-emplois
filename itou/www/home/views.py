from django.shortcuts import render

from itou.www.search.forms import SiaeSearchForm


def home(request, template_name="home/home.html"):
    context = {"siae_search_form": SiaeSearchForm()}
    return render(request, template_name, context)


def trigger_error(request):
    print(1 / 0)  # Should raise a ZeroDivisionError.


def eligibility_criteria(request, template_name="home/eligibility_criteria.html"):
    context = {}
    return render(request, template_name, context)
