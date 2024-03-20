from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, render
from django.views.generic import View

from itou.job_applications.models import JobApplication
from itou.premium.models import Note
from itou.utils.perms.company import get_current_company_or_404


class SaveNoteView(LoginRequiredMixin, View):

    def post(self, request, job_application_id, *args, **kwargs):
        to_company = get_current_company_or_404(request)
        job_application = get_object_or_404(JobApplication, id=job_application_id, to_company=to_company)

        premium_note, _ = Note.objects.update_or_create(
            job_application=job_application,
            defaults={
                "content": request.POST.get("content"),
                "updated_by": request.user,
            },
        )

        return render(
            request,
            "premium/partials/save_note_form.html",
            context={
                "content": premium_note.content,
                "job_application_id": job_application_id,
            },
        )
