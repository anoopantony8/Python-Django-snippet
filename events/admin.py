from django.contrib import admin
from reversion.admin import VersionAdmin

from .models import Event, EventType, Shift, ShiftEquipment, ShiftQualification,\
                    QuickQuote


class EventModelAdmin(VersionAdmin):
    list_display = ('name', 'client', 'status',)
    list_filter = ('status', 'client')
    search_fields = ('name', 'status')


class ShiftModelAdmin(VersionAdmin):
    list_display = ('name', 'event', 'status', )
    list_filter = ('event', 'status')
    search_fields = ('event__name', 'name', 'status')


class EventTypeModelAdmin(VersionAdmin):

    pass


admin.site.register(Event, EventModelAdmin)
admin.site.register(Shift, ShiftModelAdmin)
admin.site.register(EventType, EventTypeModelAdmin)
admin.site.register(ShiftEquipment)
admin.site.register(ShiftQualification)
admin.site.register(QuickQuote)
