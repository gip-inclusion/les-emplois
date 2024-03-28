from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.generic import ListView, View

from itou.premium.models import Customer, Note, SyncedJobApplication
from itou.utils.pagination import ItouPaginator
from itou.utils.perms.company import get_current_company_or_404


class SaveNoteView(LoginRequiredMixin, View):

    def post(self, request, synced_job_application_id, *args, **kwargs):

        synced_job_application = get_object_or_404(
            SyncedJobApplication,
            id=synced_job_application_id,
            customer=get_object_or_404(Customer, company=get_current_company_or_404(self.request)),
        )

        premium_note, _ = Note.objects.update_or_create(
            synced_job_application=synced_job_application,
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
                "synced_job_application_id": synced_job_application_id,
            },
        )


class RefreshSyncJobApplicationView(LoginRequiredMixin, View):

    def get(self, request, *args, **kwargs):
        company = get_current_company_or_404(request)
        customer = get_object_or_404(Customer, company=company, end_subscription_date__gte=timezone.now())
        job_applications = company.job_applications_received.not_archived()

        synced_job_applications = [
            SyncedJobApplication(
                customer=customer,
                job_application=job_application,
                last_in_progress_suspension=(
                    job_application.approval.last_in_progress_suspension
                    if getattr(job_application, "approval")
                    else None
                ),
            )
            for job_application in job_applications
        ]

        SyncedJobApplication.objects.bulk_create(
            synced_job_applications,
            update_conflicts=True,
            unique_fields=("job_application",),
            update_fields=("customer", "last_in_progress_suspension"),
        )

        SyncedJobApplication.objects.exclude(job_application__in=job_applications).delete()

        customer.last_synced_at = timezone.now()
        customer.save()

        return redirect("premium_views:job_applications")


class SyncJobApplicationListView(LoginRequiredMixin, ListView):
    model = SyncedJobApplication
    template_name = "premium/synced_job_application_list.html"
    paginate_by = 100
    paginator_class = ItouPaginator

    def get_customer(self):
        if not hasattr(self, "customer"):
            self.customer = get_object_or_404(Customer, company=get_current_company_or_404(self.request))
        return self.customer

    def get_queryset(self):
        syncedjobapplications = SyncedJobApplication.objects.filter(customer=self.get_customer()).select_related(
            "job_application",
            "job_application__approval",
            "job_application__job_seeker",
            "job_application__job_seeker__jobseeker_profile",
            "job_application__sender",
            "job_application__sender_prescriber_organization",
        )

        sort_field = self.request.GET.get("sort", None)
        if sort_field:
            syncedjobapplications = syncedjobapplications.order_by(sort_field, "pk")

        return syncedjobapplications

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["last_synced_at"] = self.get_customer().last_synced_at
        return context
