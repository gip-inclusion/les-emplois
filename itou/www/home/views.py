import base64
import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden, HttpResponseServerError
from django.shortcuts import get_object_or_404, render
from django.utils.encoding import force_bytes
from django.views.decorators.csrf import csrf_exempt

from itou.users.models import User
from itou.utils.tokens import resume_signer
from itou.www.search.forms import SiaeSearchForm


logger = logging.getLogger(__name__)


def home(request, template_name="home/home.html"):
    context = {"siae_search_form": SiaeSearchForm()}
    return render(request, template_name, context)


@csrf_exempt
def update_resume_link(request):
    # 1/ Check that the request is coming from Typeform.
    # https://stackoverflow.com/questions/59114066/securing-typeform-webhook-python
    # Thanks man!
    header_signature = request.headers.get("Typeform-Signature")
    secret_key = settings.TYPEFORM_SECRET

    if header_signature is None:
        return HttpResponseForbidden("Permission denied.")

    sha_name, signature = header_signature.split("=", 1)
    if sha_name != "sha256":
        return HttpResponseServerError("Operation not supported.", status=501)

    mac = hmac.new(force_bytes(secret_key), msg=force_bytes(request.body), digestmod=hashlib.sha256)
    if not hmac.compare_digest(force_bytes(base64.b64encode(mac.digest()).decode()), force_bytes(signature)):
        return HttpResponseForbidden("Permission denied.")

    # 2/ Now process content
    response = json.loads(request.read().decode("utf-8"))
    job_seeker_pk = response["form_response"]["hidden"]["job_seeker_pk"]
    job_seeker_pk = int(resume_signer.unsign(job_seeker_pk))
    user = get_object_or_404(User, pk=job_seeker_pk)

    resume_link = response["form_response"]["answers"][0]["file_url"]
    user.resume_link = resume_link
    user.save()

    return HttpResponse(status=200)


def trigger_error(request):
    print(1 / 0)  # Should raise a ZeroDivisionError.
