from functools import update_wrapper
from pprint import pformat

import httpx
from django.conf import settings
from django.contrib import admin
from django.db.models import Q
from django.http import JsonResponse
from django.template import loader
from django.urls import path
from django.utils.html import format_html
from django.utils.text import Truncator

from itou.emails.models import Email


class EmailStatusFilter(admin.SimpleListFilter):
    title = "transmis au fournisseur d’e-mail"
    parameter_name = "sent_to_esp"

    def lookups(self, request, model_admin):
        return [
            ("0", "Non"),
            ("1", "Oui"),
        ]

    def queryset(self, request, queryset):
        filter_q = Q(esp_response__isnull=True) | Q(esp_response__Messages__contains=[{"Status": "error"}])
        if self.value() == "0":
            return queryset.filter(filter_q)
        elif self.value() == "1":
            return queryset.exclude(filter_q)
        return queryset


@admin.register(Email)
class EmailAdmin(admin.ModelAdmin):
    class Media:
        css = {"all": ("css/itou-admin.css",)}

    exclude = ["esp_response"]
    list_display = ["to", "cc", "bcc", "subject", "created_at", "sent_to_esp"]
    list_display_links = ["to", "subject"]
    list_filter = [EmailStatusFilter]
    # See get_search_results for a performance override.
    search_fields = ["to", "cc", "bcc", "subject"]
    readonly_fields = ["sent_to_esp", "details"]
    show_full_result_count = False

    def has_add_permission(self, obj=None):
        return False

    def get_search_results(self, request, queryset, search_term):
        if "@" in search_term:
            # Use the GIN, Luke.
            return queryset.filter(
                Q(to__contains=[search_term]) | Q(cc__contains=[search_term]) | Q(bcc__contains=[search_term])
            ), False
        return super().get_search_results(request, queryset, search_term)

    @admin.display(description="subject", ordering="subject")
    def subject(self, obj):
        return Truncator(obj.subject).chars(100)

    @admin.display(description="transmis au fournisseur d’e-mail", boolean=True)
    def sent_to_esp(self, obj):
        if obj.esp_response:
            return all(msg["Status"] == "success" for msg in obj.esp_response["Messages"])
        return False

    def details(self, obj):
        if obj.esp_response:
            [message] = obj.esp_response["Messages"]
            if message["Status"] == "success":
                context = {"email_statuses": {"To": [], "Cc": [], "Bcc": []}}
                for section in context["email_statuses"]:
                    context["email_statuses"][section] = [
                        {
                            "id": recipient["MessageID"],
                            "email": recipient["Email"],
                        }
                        for recipient in message.get(section, [])
                    ]
                return loader.render_to_string("admin/emails/mailjet_status.html", context)
            return format_html("<pre><code>{}</code></pre>", pformat(message["Errors"], width=120))
        return ""

    def get_urls(self):
        urls = super().get_urls()

        def wrap(view):
            def wrapper(*args, **kwargs):
                return self.admin_site.admin_view(view)(*args, **kwargs)

            wrapper.model_admin = self
            return update_wrapper(wrapper, view)

        view_email_url = path(
            "<int:message_id>/mailjet.json",
            wrap(self.mailjet_view),
            name=f"{self.opts.app_label}_{self.opts.model_name}_mailjet",
        )
        return [*urls, view_email_url]

    def mailjet_view(self, request, message_id, *args, **kwargs):
        # Proxy Mailjet API to avoid giving API credentials to clients.
        response = httpx.get(
            f"https://api.mailjet.com/v3/REST/messagehistory/{message_id}",
            auth=(settings.ANYMAIL["MAILJET_API_KEY"], settings.ANYMAIL["MAILJET_SECRET_KEY"]),
        )
        response.raise_for_status()
        # Middlewares processing the response expect a Django response.
        return JsonResponse(response.json())
