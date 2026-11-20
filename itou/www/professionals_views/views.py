from django.conf import settings
from django.contrib.auth.mixins import UserPassesTestMixin
from django.db.models import Q
from django.views.generic import ListView

from itou.institutions.enums import InstitutionKind
from itou.prescribers.enums import PrescriberOrganizationKind
from itou.prescribers.models import PrescriberOrganization
from itou.utils.pagination import ItouPaginator


class AuthorizationListView(UserPassesTestMixin, ListView):
    template_name = "professionals/authorizations_list.html"
    paginate_by = settings.PAGE_SIZE_DEFAULT
    paginator_class = ItouPaginator
    model = PrescriberOrganization
    ordering = ("authorization_status", "name")

    def get_filters(self):
        if (
            self.request.from_prescriber
            and self.request.current_organization.kind == PrescriberOrganizationKind.DEPT
            and self.request.is_current_organization_admin
        ):
            return Q(
                Q(is_brsa=True) | Q(kind=PrescriberOrganizationKind.ODC),
                department=self.request.current_organization.department,
            )
        if self.request.from_institution and self.request.current_organization.kind == InstitutionKind.DDETS_IAE:
            return Q(
                department=self.request.current_organization.department,
                kind=PrescriberOrganizationKind.OHPD,
            )

    def test_func(self):
        return self.get_filters() is not None

    def get_queryset(self):
        return super().get_queryset().filter(self.get_filters()).select_related("created_by")
