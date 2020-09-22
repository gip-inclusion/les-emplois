import json
import logging

from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import csrf_exempt

from itou.www.search.forms import SiaeSearchForm


logger = logging.getLogger(__name__)


def home(request, template_name="home/home.html"):
    context = {"siae_search_form": SiaeSearchForm()}
    return render(request, template_name, context)


@csrf_exempt
def save_typeform_resume(request):
    response = json.loads(request.read().decode("utf-8"))

    # TODO: use Typeform Secret to make sure the request comes from Typeform

    # This is very unsecure!
    # TODO: encrypt
    user_email = response["form_response"]["hidden"]["mailuser"]
    user = get_object_or_404(get_user_model(), email=user_email)

    # We can't use this anymore as the response id is known too late.
    # typeform_response_id = response["form_response"]["token"]
    # user = get_object_or_404(get_user_model(), typeform_response_id=typeform_response_id)

    resume_link = response["form_response"]["answers"][0]["file_url"]
    user.resume_link = resume_link
    user.save()
    return HttpResponse(status=200)


def trigger_error(request):
    print(1 / 0)  # Should raise a ZeroDivisionError.
