from django import template
from django.urls import reverse
from django.utils.text import slugify


register = template.Library()


class NavItem:
    def __init__(
        self,
        *,
        icon=None,
        label,
        target,
        active_view_names,
        matomo_event_category=None,
        matomo_event_name=None,
        matomo_event_option=None,
    ):
        self.icon = icon
        self.label = label
        self.target = target
        self.active_view_names = active_view_names
        self.matomo_event_category = matomo_event_category
        self.matomo_event_name = matomo_event_name
        self.matomo_event_option = matomo_event_option
        self.active = False

    def __repr__(self):
        return f"NavItem(label={self.label})"


class NavGroup:
    def __init__(self, *, icon, label, items):
        self.icon = icon
        self.label = label
        self.items = items
        self.slug = slugify(label)

    @property
    def active(self):
        return any(item.active for item in self.items)

    def __repr__(self):
        return f"NavGroup(label={self.label})"


# This is quite verbose, and having a registry of entries helps with testing.
NAV_ENTRIES = {
    # Anonymous users
    "anonymous-search-employers": NavItem(
        label="Rechercher un emploi inclusif",
        target=reverse("search:employers_home"),
        active_view_names=[
            "search:employers_home",
            "search:employers_results",
            "search:job_descriptions_results",
        ],
    ),
    "anonymous-search-prescribers": NavItem(
        label="Rechercher des prescripteurs habilités",
        target=reverse("search:prescribers_home"),
        active_view_names=["search:prescribers_home", "search:prescribers_results"],
    ),
    # Logged in users.
    "home": NavItem(
        label="Accueil",
        icon="ri-home-line",
        target=reverse("home:hp"),
        active_view_names=["dashboard:index"],
    ),
    "employers-search": NavItem(
        label="Un emploi inclusif",
        target=reverse("search:employers_results"),
        active_view_names=[
            "search:employers_home",
            "search:employers_results",
            "search:job_descriptions_results",
        ],
    ),
    "prescribers-search": NavItem(
        label="Un prescripteur habilité",
        target=reverse("search:prescribers_results"),
        active_view_names=["search:prescribers_home", "search:prescribers_results"],
    ),
    # Job seekers.
    "job-seeker-job-apps": NavItem(
        label="Mes candidatures",
        icon="ri-draft-line",
        target=reverse("apply:list_for_job_seeker"),
        active_view_names=["apply:list_for_job_seeker"],
        matomo_event_category="offcanvasNav",
        matomo_event_name="clic",
        matomo_event_option="mes-candidatures",
    ),
    # Prescribers.
    "prescriber-job-apps": NavItem(
        label="Candidatures",
        icon="ri-draft-line",
        target=reverse("apply:list_prescriptions"),
        active_view_names=["apply:list_prescriptions", "apply:list_prescriptions_exports"],
        matomo_event_category="offcanvasNav",
        matomo_event_name="clic",
        matomo_event_option="candidatures",
    ),
    "prescriber-members": NavItem(
        label="Collaborateurs",
        target=reverse("prescribers_views:members"),
        active_view_names=["prescribers_views:members"],
        matomo_event_category="offcanvasNav",
        matomo_event_name="clic",
        matomo_event_option="collaborateurs",
    ),
    # Employers.
    "employer-job-apps": NavItem(
        label="Candidatures",
        icon="ri-draft-line",
        target=reverse("apply:list_for_siae"),
        active_view_names=["apply:list_for_siae", "apply:list_for_siae_exports"],
        matomo_event_category="offcanvasNav",
        matomo_event_name="clic",
        matomo_event_option="candidatures",
    ),
    "employer-approvals": NavItem(
        label="Salariés et PASS IAE",
        target=reverse("approvals:list"),
        active_view_names=["approvals:list"],
        matomo_event_category="offcanvasNav",
        matomo_event_name="clic",
        matomo_event_option="salaries-pass-iae",
    ),
    "employer-employee-records": NavItem(
        label="Fiches salariés ASP",
        target=f"{reverse('employee_record_views:list')}?status=NEW",
        active_view_names=["employee_record_views:list"],
        matomo_event_category="offcanvasNav",
        matomo_event_name="clic",
        matomo_event_option="fiches-salaries-asp",
    ),
    "employer-jobs": NavItem(
        label="Métiers et recrutements",
        target=reverse("companies_views:job_description_list"),
        active_view_names=["companies_views:job_description_list"],
        matomo_event_category="offcanvasNav",
        matomo_event_name="clic",
        matomo_event_option="metiers-recrutement",
    ),
    "employer-members": NavItem(
        label="Collaborateurs",
        target=reverse("companies_views:members"),
        active_view_names=["companies_views:members"],
        matomo_event_category="offcanvasNav",
        matomo_event_name="clic",
        matomo_event_option="collaborateurs",
    ),
    "employer-financial-annexes": NavItem(
        label="Annexes financières",
        target=reverse("companies_views:show_financial_annexes"),
        active_view_names=["companies_views:show_financial_annexes"],
        matomo_event_category="offcanvasNav",
        matomo_event_name="clic",
        matomo_event_option="annexes-financieres",
    ),
    # Labor inspectors.
    "labor-inspector-members": NavItem(
        label="Collaborateurs",
        target=reverse("institutions_views:members"),
        active_view_names=["institutions_views:members"],
        matomo_event_category="offcanvasNav",
        matomo_event_name="clic",
        matomo_event_option="annexes-financieres",
    ),
}


def is_active(request, menu_item):
    return request.resolver_match.view_name in menu_item.active_view_names


@register.inclusion_tag("utils/templatetags/nav.html")
def nav(request):
    menu_items: list[NavItem | NavGroup] = []
    if request.user.is_authenticated:
        menu_items.append(NAV_ENTRIES["home"])
        if request.user.is_job_seeker:
            menu_items.append(NAV_ENTRIES["job-seeker-job-apps"])
        elif request.user.is_prescriber:
            menu_items.append(NAV_ENTRIES["prescriber-job-apps"])
            if request.current_organization:
                menu_items.append(
                    NavGroup(
                        label="Organisation",
                        icon="ri-team-line",
                        items=[NAV_ENTRIES["prescriber-members"]],
                    )
                )
        elif request.user.is_employer and request.current_organization:
            menu_items.append(NAV_ENTRIES["employer-job-apps"])
            if request.current_organization.is_subject_to_eligibility_rules:
                employee_group_items = [NAV_ENTRIES["employer-approvals"]]
                if request.current_organization.can_use_employee_record:
                    employee_group_items.append(NAV_ENTRIES["employer-employee-records"])
                menu_items.append(NavGroup(label="Salariés", icon="ri-team-line", items=employee_group_items))
            company_group_items = [NAV_ENTRIES["employer-jobs"]]
            if request.current_organization.is_active:
                company_group_items.append(NAV_ENTRIES["employer-members"])
            if request.current_organization.convention_can_be_accessed_by(request.user):
                company_group_items.append(NAV_ENTRIES["employer-financial-annexes"])
            menu_items.append(NavGroup(label="Organisation", icon="ri-community-line", items=company_group_items))
        elif request.user.is_labor_inspector:
            menu_items.append(
                NavGroup(
                    label="Organisation",
                    icon="ri-community-line",
                    items=[NAV_ENTRIES["labor-inspector-members"]],
                )
            )
        menu_items.append(
            NavGroup(
                label="Rechercher",
                icon="ri-search-line",
                items=[
                    NAV_ENTRIES["employers-search"],
                    NAV_ENTRIES["prescribers-search"],
                ],
            )
        )

        if request.resolver_match:
            for group_or_item in menu_items:
                try:
                    for item in group_or_item.items:
                        item.active = is_active(request, item)
                except AttributeError:
                    group_or_item.active = is_active(request, group_or_item)
    return {"menu_items": menu_items}


@register.inclusion_tag("utils/templatetags/nav_anonymous.html")
def nav_anonymous(request, *, mobile):
    menu_items = [
        NAV_ENTRIES["anonymous-search-employers"],
        NAV_ENTRIES["anonymous-search-prescribers"],
    ]
    if request.resolver_match:
        for item in menu_items:
            item.active = is_active(request, item)
    return {
        "menu_items": menu_items,
        "mobile": mobile,
    }
