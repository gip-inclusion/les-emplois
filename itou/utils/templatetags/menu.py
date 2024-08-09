from django import template
from django.urls import reverse
from django.utils.text import slugify


register = template.Library()


class MenuItem:
    active = False

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

    def __repr__(self):
        return f"MenuItem(label={self.label})"


class MenuGroup:
    def __init__(self, *, icon, label, items):
        self.icon = icon
        self.label = label
        self.items = items
        self.slug = slugify(label)

    @property
    def active(self):
        return any(item.active for item in self.items)

    def __repr__(self):
        return f"MenuGroup(label={self.label})"


# This is quite verbose, and having a registry of entries helps with testing.
MENU_ENTRIES = {
    # All users.
    "home": MenuItem(
        label="Accueil",
        icon="ri-home-line",
        target=reverse("home:hp"),
        active_view_names=["dashboard:index"],
    ),
    # Job seekers.
    "job-seeker-job-apps": MenuItem(
        label="Mes candidatures",
        icon="ri-draft-line",
        target=reverse("apply:list_for_job_seeker"),
        active_view_names=["apply:list_for_job_seeker"],
        matomo_event_category="offcanvasNav",
        matomo_event_name="clic",
        matomo_event_option="mes-candidatures",
    ),
    # Prescribers.
    "prescriber-job-apps": MenuItem(
        label="Candidatures",
        icon="ri-draft-line",
        target=reverse("apply:list_prescriptions"),
        active_view_names=["apply:list_prescriptions", "apply:list_prescriptions_exports"],
        matomo_event_category="offcanvasNav",
        matomo_event_name="clic",
        matomo_event_option="candidatures",
    ),
    "prescriber-members": MenuItem(
        label="Collaborateurs",
        target=reverse("prescribers_views:members"),
        active_view_names=["prescribers_views:members"],
        matomo_event_category="offcanvasNav",
        matomo_event_name="clic",
        matomo_event_option="collaborateurs",
    ),
    # Employers.
    "employer-job-apps": MenuItem(
        label="Candidatures",
        icon="ri-draft-line",
        target=reverse("apply:list_for_siae"),
        active_view_names=["apply:list_for_siae", "apply:list_for_siae_exports"],
        matomo_event_category="offcanvasNav",
        matomo_event_name="clic",
        matomo_event_option="candidatures",
    ),
    "employer-approvals": MenuItem(
        label="Salariés et PASS IAE",
        target=reverse("approvals:list"),
        active_view_names=["approvals:list"],
        matomo_event_category="offcanvasNav",
        matomo_event_name="clic",
        matomo_event_option="salaries-pass-iae",
    ),
    "employer-employee-records": MenuItem(
        label="Fiches salariés ASP",
        target=f"{reverse('employee_record_views:list')}?status=NEW",
        active_view_names=["employee_record_views:list"],
        matomo_event_category="offcanvasNav",
        matomo_event_name="clic",
        matomo_event_option="fiches-salaries-asp",
    ),
    "employer-jobs": MenuItem(
        label="Métiers et recrutement",
        target=reverse("companies_views:job_description_list"),
        active_view_names=["companies_views:job_description_list"],
        matomo_event_category="offcanvasNav",
        matomo_event_name="clic",
        matomo_event_option="metiers-recrutement",
    ),
    "employer-members": MenuItem(
        label="Collaborateurs",
        target=reverse("companies_views:members"),
        active_view_names=["companies_views:members"],
        matomo_event_category="offcanvasNav",
        matomo_event_name="clic",
        matomo_event_option="collaborateurs",
    ),
    "employer-financial-annexes": MenuItem(
        label="Annexes financières",
        target=reverse("companies_views:show_financial_annexes"),
        active_view_names=["companies_views:show_financial_annexes"],
        matomo_event_category="offcanvasNav",
        matomo_event_name="clic",
        matomo_event_option="annexes-financieres",
    ),
    # Labor inspectors.
    "labor-inspector-members": MenuItem(
        label="Collaborateurs",
        target=reverse("institutions_views:members"),
        active_view_names=["institutions_views:members"],
        matomo_event_category="offcanvasNav",
        matomo_event_name="clic",
        matomo_event_option="annexes-financieres",
    ),
}


@register.inclusion_tag("utils/templatetags/menu.html")
def menu(request):
    menu_items: list[MenuItem | MenuGroup] = []
    if request.user.is_authenticated:
        menu_items.append(MENU_ENTRIES["home"])
        if request.user.is_job_seeker:
            menu_items.append(MENU_ENTRIES["job-seeker-job-apps"])
        elif request.user.is_prescriber:
            menu_items.append(MENU_ENTRIES["prescriber-job-apps"])
            if request.current_organization:
                menu_items.append(
                    MenuGroup(
                        label="Organisation",
                        icon="ri-team-line",
                        items=[MENU_ENTRIES["prescriber-members"]],
                    )
                )
        elif request.user.is_employer and request.current_organization:
            menu_items.append(MENU_ENTRIES["employer-job-apps"])
            if request.current_organization.is_subject_to_eligibility_rules:
                employee_group_items = [MENU_ENTRIES["employer-approvals"]]
                if request.current_organization.can_use_employee_record:
                    employee_group_items.append(MENU_ENTRIES["employer-employee-records"])
                menu_items.append(MenuGroup(label="Salariés", icon="ri-team-line", items=employee_group_items))
            company_group_items = [MENU_ENTRIES["employer-jobs"]]
            if request.current_organization.is_active:
                company_group_items.append(MENU_ENTRIES["employer-members"])
            if request.current_organization.convention_can_be_accessed_by(request.user):
                company_group_items.append(MENU_ENTRIES["employer-financial-annexes"])
            menu_items.append(MenuGroup(label="Organisation", icon="ri-community-line", items=company_group_items))
        elif request.user.is_labor_inspector:
            menu_items.append(
                MenuGroup(
                    label="Organisation",
                    icon="ri-community-line",
                    items=[MENU_ENTRIES["labor-inspector-members"]],
                )
            )

        view_name = request.resolver_match.view_name
        if view_name:

            def is_active(menu_item):
                return view_name in menu_item.active_view_names

            for group_or_item in menu_items:
                try:
                    for item in group_or_item.items:
                        item.active = is_active(item)
                except AttributeError:
                    group_or_item.active = is_active(group_or_item)

    return {"menu_items": menu_items}
