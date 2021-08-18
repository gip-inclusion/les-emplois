import logging

from django.shortcuts import render

from itou.www.home.forms import DuetDatePickerForm
from itou.www.search.forms import SiaeSearchForm


logger = logging.getLogger(__name__)


def home(request, template_name="home/home.html"):
    context = {"siae_search_form": SiaeSearchForm()}
    return render(request, template_name, context)


def trigger_error(request):
    if request.POST:
        raise Exception("%s error: %s" % (request.POST.get("status_code"), request.POST.get("error_message")))

    print(1 / 0)  # Should raise a ZeroDivisionError.


def duet_date_picker(request, template_name="home/duet_date_picker.html"):
    """
    Test Duet Date Picker.
    """

    form = DuetDatePickerForm(data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        print("-" * 80)
        print(form.cleaned_data)

    context = {"form": form}
    return render(request, template_name, context)
