import sentry_sdk
from django import template
from django.conf import settings
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
        target=reverse("dashboard:index"),
        active_view_names=["dashboard:index", "dashboard:index_stats"],
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
        active_view_names=[
            "search:prescribers_home",
            "search:prescribers_results",
            "prescribers_views:card",
        ],
    ),
    # Job seekers.
    "job-seeker-job-apps": NavItem(
        label="Mes candidatures",
        icon="ri-draft-line",
        target=reverse("apply:list_for_job_seeker"),
        active_view_names=[
            "apply:check_nir_for_job_seeker",
            "apply:details_for_jobseeker",
            "apply:list_for_job_seeker",
            "apply:step_check_job_seeker_info",
            "apply:step_check_prev_applications",
        ],
        matomo_event_category="offcanvasNav",
        matomo_event_name="clic",
        matomo_event_option="mes-candidatures",
    ),
    # Prescribers.
    "prescriber-jobseekers": NavItem(
        label="Candidats",
        icon="ri-user-line",
        target=reverse("job_seekers_views:list"),
        active_view_names=[
            "job_seekers_views:list",
            "job_seekers_views:details",
            "job_seekers_views:check_job_seeker_info",
        ],
        matomo_event_category="offcanvasNav",
        matomo_event_name="clic",
        matomo_event_option="candidats",
    ),
    "prescriber-job-apps": NavItem(
        label="Candidatures",
        icon="ri-draft-line",
        target=reverse("apply:list_prescriptions"),
        active_view_names=[
            "apply:application_eligibility",
            "apply:application_end",
            "apply:application_geiq_eligibility",
            "apply:application_jobs",
            "apply:application_resume",
            "apply:check_nir_for_sender",
            "apply:create_job_seeker_step_1_for_sender",
            "apply:create_job_seeker_step_2_for_sender",
            "apply:create_job_seeker_step_3_for_sender",
            "apply:create_job_seeker_step_end_for_sender",
            "apply:details_for_prescriber",
            "apply:list_prescriptions",
            "apply:list_prescriptions_exports",
            "apply:pending_authorization_for_sender",
            "apply:search_by_email_for_sender",
            "apply:step_check_job_seeker_info",
            "apply:step_check_prev_applications",
            "apply:update_job_seeker_step_1",
            "apply:update_job_seeker_step_2",
            "apply:update_job_seeker_step_3",
            "apply:update_job_seeker_step_end",
            "job_seekers_views:check_nir_for_sender",
            "job_seekers_views:create_job_seeker_step_1_for_sender",
            "job_seekers_views:create_job_seeker_step_2_for_sender",
            "job_seekers_views:create_job_seeker_step_3_for_sender",
            "job_seekers_views:create_job_seeker_step_end_for_sender",
            "job_seekers_views:search_by_email_for_sender",
            "job_seekers_views:update_job_seeker_step_1",
            "job_seekers_views:update_job_seeker_step_2",
            "job_seekers_views:update_job_seeker_step_3",
            "job_seekers_views:update_job_seeker_step_end",
        ],
        matomo_event_category="offcanvasNav",
        matomo_event_name="clic",
        matomo_event_option="candidatures",
    ),
    "prescriber-members": NavItem(
        label="Collaborateurs",
        target=reverse("prescribers_views:members"),
        active_view_names=[
            "invitations_views:invite_prescriber_with_org",
            "prescribers_views:deactivate_member",
            "prescribers_views:edit_organization",
            "prescribers_views:members",
            "prescribers_views:update_admin_role",
        ],
        matomo_event_category="offcanvasNav",
        matomo_event_name="clic",
        matomo_event_option="collaborateurs",
    ),
    # Employers.
    "employer-job-apps": NavItem(
        label="Candidatures",
        icon="ri-draft-line",
        target=reverse("apply:list_for_siae"),
        active_view_names=[
            "apply:list_for_siae",
            "apply:list_for_siae_exports",
            "apply:accept",
            "apply:application_eligibility",
            "apply:application_end",
            "apply:application_geiq_eligibility",
            "apply:application_jobs",
            "apply:application_resume",
            "apply:check_job_seeker_info_for_hire",
            "apply:check_nir_for_hire",
            "apply:check_nir_for_sender",
            "apply:check_prev_applications_for_hire",
            "apply:create_job_seeker_step_1_for_hire",
            "apply:create_job_seeker_step_1_for_sender",
            "apply:create_job_seeker_step_2_for_hire",
            "apply:create_job_seeker_step_2_for_sender",
            "apply:create_job_seeker_step_3_for_hire",
            "apply:create_job_seeker_step_3_for_sender",
            "apply:create_job_seeker_step_end_for_hire",
            "apply:create_job_seeker_step_end_for_sender",
            "apply:details_for_company",
            "apply:edit_contract_start_date",
            "apply:eligibility",
            "apply:eligibility_for_hire",
            "apply:geiq_eligibility",
            "apply:geiq_eligibility_criteria_for_hire",
            "apply:geiq_eligibility_for_hire",
            "apply:hire_confirmation",
            "apply:job_application_external_transfer_step_1",
            "apply:job_application_external_transfer_step_1_company_card",
            "apply:job_application_external_transfer_step_1_job_description_card",
            "apply:job_application_external_transfer_step_2",
            "apply:job_application_external_transfer_step_3",
            "apply:job_application_external_transfer_step_end",
            "apply:job_application_internal_transfer",
            "apply:postpone",
            "apply:process",
            "apply:refuse",
            "apply:search_by_email_for_hire",
            "apply:search_by_email_for_sender",
            "apply:step_check_job_seeker_info",
            "apply:step_check_prev_applications",
            "apply:transfer",
            "apply:update_job_seeker_step_1",
            "apply:update_job_seeker_step_1_for_hire",
            "apply:update_job_seeker_step_2",
            "apply:update_job_seeker_step_2_for_hire",
            "apply:update_job_seeker_step_3",
            "apply:update_job_seeker_step_3_for_hire",
            "apply:update_job_seeker_step_end",
            "apply:update_job_seeker_step_end_for_hire",
            "job_seekers_views:check_job_seeker_info",
            "job_seekers_views:check_job_seeker_info_for_hire",
            "job_seekers_views:check_nir_for_hire",
            "job_seekers_views:check_nir_for_job_seeker",
            "job_seekers_views:check_nir_for_sender",
            "job_seekers_views:create_job_seeker_step_1_for_hire",
            "job_seekers_views:create_job_seeker_step_1_for_sender",
            "job_seekers_views:create_job_seeker_step_2_for_hire",
            "job_seekers_views:create_job_seeker_step_2_for_sender",
            "job_seekers_views:create_job_seeker_step_3_for_hire",
            "job_seekers_views:create_job_seeker_step_3_for_sender",
            "job_seekers_views:create_job_seeker_step_end_for_hire",
            "job_seekers_views:create_job_seeker_step_end_for_sender",
            "job_seekers_views:search_by_email_for_hire",
            "job_seekers_views:search_by_email_for_sender",
            "job_seekers_views:update_job_seeker_step_1",
            "job_seekers_views:update_job_seeker_step_1_for_hire",
            "job_seekers_views:update_job_seeker_step_2",
            "job_seekers_views:update_job_seeker_step_2_for_hire",
            "job_seekers_views:update_job_seeker_step_3",
            "job_seekers_views:update_job_seeker_step_3_for_hire",
            "job_seekers_views:update_job_seeker_step_end",
            "job_seekers_views:update_job_seeker_step_end_for_hire",
        ],
        matomo_event_category="offcanvasNav",
        matomo_event_name="clic",
        matomo_event_option="candidatures",
    ),
    "employer-approvals": NavItem(
        label="Salariés et PASS IAE",
        target=reverse("approvals:list"),
        active_view_names=[
            "approvals:list",
            "employees:detail",
            "approvals:declare_prolongation",
            "approvals:details",
            "approvals:display_printable_approval",
            "approvals:prolongation_request_show",
            "approvals:prolongation_requests_list",
            "approvals:suspend",
            "approvals:suspension_action_choice",
            "approvals:suspension_delete",
            "approvals:suspension_update",
            "approvals:suspension_update_enddate",
        ],
        matomo_event_category="offcanvasNav",
        matomo_event_name="clic",
        matomo_event_option="salaries-pass-iae",
    ),
    "employer-employee-records": NavItem(
        label="Fiches salarié ASP",
        target=f"{reverse('employee_record_views:list')}?status=NEW",
        active_view_names=[
            "employee_record_views:add",
            "employee_record_views:create",
            "employee_record_views:create_step_2",
            "employee_record_views:create_step_3",
            "employee_record_views:create_step_4",
            "employee_record_views:create_step_5",
            "employee_record_views:disable",
            "employee_record_views:list",
            "employee_record_views:reactivate",
            "employee_record_views:summary",
        ],
        matomo_event_category="offcanvasNav",
        matomo_event_name="clic",
        matomo_event_option="fiches-salaries-asp",
    ),
    "employer-jobs": NavItem(
        label="Métiers et recrutements",
        target=reverse("companies_views:job_description_list"),
        active_view_names=[
            "companies_views:create_company",
            "companies_views:edit_company_step_contact_infos",
            "companies_views:edit_company_step_description",
            "companies_views:edit_company_step_preview",
            "companies_views:edit_job_description",
            "companies_views:edit_job_description_details",
            "companies_views:edit_job_description_preview",
            "companies_views:job_description_list",
            "companies_views:update_job_description",
        ],
        matomo_event_category="offcanvasNav",
        matomo_event_name="clic",
        matomo_event_option="metiers-recrutement",
    ),
    "employer-members": NavItem(
        label="Collaborateurs",
        target=reverse("companies_views:members"),
        active_view_names=[
            "companies_views:members",
            "companies_views:deactivate_member",
            "companies_views:update_admin_role",
            "invitations_views:invite_employer",
        ],
        matomo_event_category="offcanvasNav",
        matomo_event_name="clic",
        matomo_event_option="collaborateurs",
    ),
    "employer-financial-annexes": NavItem(
        label="Annexes financières",
        target=reverse("companies_views:show_financial_annexes"),
        active_view_names=[
            "companies_views:show_financial_annexes",
            "companies_views:select_financial_annex",
        ],
        matomo_event_category="offcanvasNav",
        matomo_event_name="clic",
        matomo_event_option="annexes-financieres",
    ),
    # Labor inspectors.
    "labor-inspector-members": NavItem(
        label="Collaborateurs",
        target=reverse("institutions_views:members"),
        active_view_names=[
            "invitations_views:invite_labor_inspector",
            "institutions_views:deactivate_member",
            "institutions_views:members",
            "institutions_views:update_admin_role",
        ],
        matomo_event_category="offcanvasNav",
        matomo_event_name="clic",
        matomo_event_option="annexes-financieres",
    ),
}


def handle_nav_exception(e):
    if settings.DEBUG:
        # The django 500 page is used, it does not include this template tag.
        raise
    # Keep going, we may be rendering the 500 page.
    sentry_sdk.capture_exception(e)


def is_active(request, menu_item):
    return request.resolver_match.view_name in menu_item.active_view_names


@register.inclusion_tag("utils/templatetags/nav.html")
def nav(request):
    menu_items: list[NavItem | NavGroup] = [NAV_ENTRIES["home"]]
    try:
        if request.user.is_job_seeker:
            menu_items.append(NAV_ENTRIES["job-seeker-job-apps"])
        elif request.user.is_prescriber:
            menu_items.append(NAV_ENTRIES["prescriber-job-apps"])
            menu_items.append(NAV_ENTRIES["prescriber-jobseekers"])
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
            menu_items.append(NavGroup(label="Structure", icon="ri-community-line", items=company_group_items))
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
    except Exception as e:
        handle_nav_exception(e)
    return {"menu_items": menu_items}


@register.inclusion_tag("utils/templatetags/nav_anonymous.html")
def nav_anonymous(request, *, mobile):
    menu_items = [
        NAV_ENTRIES["anonymous-search-employers"],
        NAV_ENTRIES["anonymous-search-prescribers"],
    ]
    try:
        if request.resolver_match:
            for item in menu_items:
                item.active = is_active(request, item)
    except Exception as e:
        handle_nav_exception(e)
    return {
        "menu_items": menu_items,
        "mobile": mobile,
    }
