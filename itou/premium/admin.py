from django.conf import settings
from django.contrib import admin

from itou.premium.models import Customer, Note, SyncedJobApplication


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("company", "end_subscription_date", "last_synced_at")
    raw_id_fields = ("company",)

    def has_add_permission(self, request):
        return settings.DEBUG

    def has_change_permission(self, request, obj=None):
        return settings.DEBUG

    def has_delete_permission(self, request, obj=None):
        return settings.DEBUG


@admin.register(SyncedJobApplication)
class SyncedJobApplicationAdmin(admin.ModelAdmin):
    list_display = ("customer", "job_application", "last_in_progress_suspension")
    raw_id_fields = ("customer", "job_application", "last_in_progress_suspension")

    def has_add_permission(self, request):
        return settings.DEBUG

    def has_change_permission(self, request, obj=None):
        return settings.DEBUG

    def has_delete_permission(self, request, obj=None):
        return settings.DEBUG


@admin.register(Note)
class NoteAdmin(admin.ModelAdmin):
    list_display = ("synced_job_application", "created_by")
    raw_id_fields = ("synced_job_application", "created_by", "updated_by")

    def has_add_permission(self, request):
        return settings.DEBUG

    def has_change_permission(self, request, obj=None):
        return settings.DEBUG

    def has_delete_permission(self, request, obj=None):
        return settings.DEBUG
