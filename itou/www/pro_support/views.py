import base64
import datetime
import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.core.exceptions import ValidationError
from django.http import Http404, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from itou.companies.models import Company, CompanyMembership
from itou.users.enums import UserKind
from itou.users.models import JobSeekerAssignment, ProSupportReport, User


logger = logging.getLogger(__name__)


class InvalidPayload(Exception):
    pass


def _is_signed_by_tally(request):
    signature = base64.b64encode(
        hmac.new(settings.TALLY_PRO_SUPPORT_REPORT_WEBHOOK_SECRET.encode(), request.body, hashlib.sha256).digest()
    ).decode()
    given_signature = request.headers.get("tally-signature", "")
    return hmac.compare_digest(signature, given_signature)


def _parse_payload(body):
    payload = json.loads(body)
    fields = {
        field["label"]: field["value"] for field in payload["data"]["fields"] if field["type"] == "HIDDEN_FIELDS"
    }
    try:
        job_seeker = User.objects.get(public_id=fields["uidjobseeker"], kind=UserKind.JOB_SEEKER)
        company = Company.objects.get(pk=fields["idcompany"])
        # The hidden fields travel through the employer browser: do not trust them without checking.
        author_is_member = CompanyMembership.objects.filter(
            user_id=fields["iduser"], company=company, is_active=True
        ).exists()
    except (KeyError, TypeError, ValidationError, ValueError, User.DoesNotExist, Company.DoesNotExist) as exc:
        raise InvalidPayload(f"Unknown job seeker, company or author: {exc}") from exc
    if not author_is_member:
        raise InvalidPayload(f"Author is not a member of company={company.pk}")
    if not JobSeekerAssignment.objects.filter(job_seeker=job_seeker, company=company).exists():
        raise InvalidPayload(f"Job seeker is not supported by company={company.pk}")
    return job_seeker, company, datetime.datetime.fromisoformat(payload["createdAt"])


@require_POST
@csrf_exempt
@login_not_required
def webhook(request):
    if not settings.TALLY_PRO_SUPPORT_REPORT_WEBHOOK_SECRET:
        raise Http404
    if not _is_signed_by_tally(request):
        logger.warning("Pro support report webhook called without a valid signature")
        return JsonResponse({"success": False}, status=401)
    try:
        job_seeker, company, submitted_at = _parse_payload(request.body)
    except InvalidPayload as exc:
        logger.warning("Pro support report discarded: %s", exc)
        return JsonResponse({"success": False}, status=400)

    report, created = ProSupportReport.objects.get_or_create(
        job_seeker=job_seeker, defaults={"company": company, "submitted_at": submitted_at}
    )
    if not created:
        # Tally retries for a day: a late report must not replace a more recent one.
        ProSupportReport.objects.filter(pk=report.pk, submitted_at__lt=submitted_at).update(
            company=company, submitted_at=submitted_at, updated_at=timezone.now()
        )
    return JsonResponse({"success": True})
