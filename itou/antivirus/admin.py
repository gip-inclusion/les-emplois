from django.contrib import admin
from django.db.models import Case, F, Q, When

from itou.antivirus.models import Scan
from itou.utils.admin import ItouModelAdmin


class SuspiciousFilter(admin.SimpleListFilter):
    title = "statut “à vérifier”"
    parameter_name = "suspicious"

    def lookups(self, request, model_admin):
        return [("1", "Oui"), ("0", "Non")]

    def queryset(self, request, queryset):
        match self.value():
            case "0":
                return queryset.filter(suspicious=None)
            case "1":
                return queryset.filter(suspicious=True)
            case _:
                return queryset


@admin.register(Scan)
class ScanAdmin(ItouModelAdmin):
    list_display = ["file_id", "suspicious", "infected", "clamav_signature", "clamav_completed_at"]
    readonly_fields = ["clamav_completed_at", "clamav_signature"]
    fields = ["clamav_completed_at", "clamav_signature", "infected", "comment"]
    list_filter = [SuspiciousFilter, "infected", "clamav_completed_at"]
    search_fields = ["file__key", "clamav_signature"]

    @admin.display(boolean=True, description="à vérifier", ordering="suspicious")
    def suspicious(self, obj):
        return bool(obj.infected is None and obj.clamav_signature)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        is_suspicious = Case(When(Q(infected=None) & ~Q(clamav_signature=""), then=True))
        return qs.annotate(suspicious=is_suspicious).order_by(F("suspicious").desc(nulls_last=True), "file_id")

    def has_add_permission(self, request):
        return False
