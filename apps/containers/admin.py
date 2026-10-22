from django.contrib import admin

from .models import Container, Entry


@admin.register(Container)
class ContainerAdmin(admin.ModelAdmin):
    list_display = ("title", "owner", "status", "visibility", "entry_count", "last_activity_at")
    list_filter = ("status", "visibility")
    search_fields = ("title", "owner__email")
    raw_id_fields = ("owner",)


@admin.register(Entry)
class EntryAdmin(admin.ModelAdmin):
    list_display = ("id", "container", "kind", "status", "created_at")
    list_filter = ("kind", "status")
    raw_id_fields = ("owner", "container")
    exclude = ("search_vector",)
