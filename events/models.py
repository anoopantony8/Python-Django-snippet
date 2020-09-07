import reversion
import json
from django.contrib.gis.db.models import PointField
from django.db import models, transaction
from django.db.models.signals import post_save, post_delete
from django.db.models import Manager as GeoManager
from django.db.models import Sum, F, FloatField
from django.core import serializers
from django.dispatch import receiver
from django.utils.translation import ugettext as _
from django.contrib.gis.measure import Distance, D

from apps.accounts.models import Client, CrewManager, CrewProfile, UserQualification
from apps.common.models import (CrewAppBaseModel, CrewDepartment, Equipments,
                                Location, Qualification, Skills, SuplierSetting)

from .choices import STATUS
from apps.utils import calculate_hours
from .managers import EventManager


@reversion.register()
class EventType(CrewAppBaseModel):
    """ Model to save types of Events, Tagged to events when creating an Event
    """
    name = models.CharField(max_length=255, verbose_name=_("Event Name"))
    description = models.TextField(
        verbose_name="Description", null=True, blank=True)

    def __str__(self):
        return self.name


@reversion.register()
class Event(CrewAppBaseModel):
    ESTIMATION = 1
    REQUEST_QUOTATION = 2
    QUOTATION = 3
    CONFIRMATION = 4
    ONGOING = 5
    COMPLETED = 6
    DECLINED = 7

    STATUS = (
        (ESTIMATION, _('Estimation')),
        (REQUEST_QUOTATION, _('Request Quotation')),
        (QUOTATION, _('Quotation')),
        (CONFIRMATION, _('Confirmation')),
        (ONGOING, _('Ongoing')),
        (COMPLETED, _('Completed')),
        (DECLINED, _('Declined'))
    )
    name = models.CharField(max_length=255, verbose_name=_("Event Name"))
    event_type = models.ForeignKey(
        EventType, on_delete=models.CASCADE, null=True, blank=True)
    status = models.IntegerField(default=ESTIMATION, choices=STATUS)
    client = models.ForeignKey(Client, on_delete=models.CASCADE)
    start_date = models.DateTimeField(
        verbose_name="Start Date/Time", null=True, blank=True)
    end_date = models.DateTimeField(
        verbose_name="End Date/Time", null=True, blank=True)
    location = models.ManyToManyField(Location, blank=True)
    sub_total = models.FloatField(verbose_name=_("Sub total"), default=0)
    total_cost = models.FloatField(verbose_name=_("Cost/Budget"), default=0)
    comments = models.TextField(verbose_name="Comments", null=True, blank=True)
    po_number = models.CharField(max_length=255, verbose_name=_(
        "PO Number"), null=True, blank=True)
    ref_number = models.CharField(max_length=255, verbose_name=_(
        "Reference Number"), null=True, blank=True)
    discount = models.FloatField(_("Discount"), default=0.00)
    tax_percentage = models.FloatField(_("Tax Percentage"), default=0.00)
    is_archived = models.BooleanField(_("Archived"), default=False)

    objects = EventManager()

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.total_cost = float(self.sub_total) - float(self.discount) + \
            float(float(self.sub_total) * float(self.tax_percentage / 100))
        super().save(*args, **kwargs)


@reversion.register()
class EventLocation(CrewAppBaseModel):
    event = models.ForeignKey(Event, verbose_name=_(
        "Event Name"), on_delete=models.CASCADE)
    location_name = models.CharField(null=True, blank=True, max_length=255)
    coordinates = PointField()
    objects = GeoManager()


@reversion.register()
class Shift(CrewAppBaseModel):
    """ Shift Model
        Shift Status should mimic Event status for basic event status
    """
    ESTIMATION = 1
    REQUEST_QUOTATION = 2
    QUOTATION = 3
    CONFIRMATION = 4
    ONGOING = 5
    COMPLETED = 6
    DECLINED = 7
    # Shift Specific status
    CANCELLED = 8
    DELETED = 9

    STATUS = (
        (ESTIMATION, _('Estimation')),
        (REQUEST_QUOTATION, _('Request Quotation')),
        (QUOTATION, _('Quotation')),
        (CONFIRMATION, _('Confirmation')),
        (ONGOING, _('Ongoing')),
        (COMPLETED, _('Completed')),
        (DECLINED, _('Declined')),
        (CANCELLED, _('Cancelled')),
        (DELETED, _('Deleted')),
    )
    name = models.CharField(max_length=255, verbose_name=_("Shift Name"))
    event = models.ForeignKey(Event, on_delete=models.CASCADE)
    start_date = models.DateTimeField(
        verbose_name="Start Date/Time", null=True, blank=True)
    end_date = models.DateTimeField(
        verbose_name="End Date/Time", null=True, blank=True)
    total_shift_hours = models.FloatField(default=0.00)
    location = models.ForeignKey(
        Location, null=True, blank=True, on_delete=models.CASCADE)
    no_of_resources = models.PositiveIntegerField(default=1)
    status = models.IntegerField(default=ESTIMATION, choices=STATUS)
    department = models.ForeignKey(CrewDepartment, on_delete=models.CASCADE)
    # qualification = models.ManyToManyField(Qualification, blank=True,
    #                                        related_name='qualifications',)
    crew_manager = models.ForeignKey(CrewProfile, blank=True, null=True,
                                     related_name='crew_manager', on_delete=models.CASCADE)
    distance_rate = models.FloatField(default=0.00)
    travel_expenses = models.FloatField(default=0.00)
    qualification_charges = models.FloatField(default=0.00)
    equipment_charges = models.FloatField(default=0.00)
    total_shift_cost = models.FloatField(default=0.00)
    no_of_crew_chiefs = models.PositiveIntegerField(default=0)

    __original_location = None
    __original_no_of_resources = None

    def __init__(self, *args, **kwargs):
        super(Shift, self).__init__(*args, **kwargs)
        self.__original_location = self.location
        self.__original_no_of_resources = self.no_of_resources

    def __str__(self):
        return self.name

    def qualification_cost(self, *args, **kwargs):
        cost = self.qualification.all().aggregate(
            Sum('charge_rate'))['charge_rate__sum']
        return cost * self.no_of_resources

    def equipment_cost(self, *args, **kwargs):
        # TODO
        return 1

    def shift_cost(self, *args, **kwargs):
        cost = self.qualification_cost(
        ) + self.get_travel_expenses()['cost'] + self.equipment_cost()
        return cost

    def get_travel_expenses(self, *args, **kwargs):
        dist = self.location.coordinates.distance(
            self.department.location.coordinates)
        distance_in_km = dist * 100
        rate = float(SuplierSetting.objects.get().rate_per_km)
        cost = distance_in_km * rate * self.no_of_resources
        return {"distance_in_km": distance_in_km, "rate_per_km": rate, "cost": cost}

    def save(self, *args, **kwargs):
        self.total_shift_hours = calculate_hours(
            self.start_date, self.end_date)
        # #checks for location change to calculate distance
        if self.pk:
            if self.location != self.__original_location or \
                    self.no_of_resources != self.__original_no_of_resources:
                # ToChange
                dist = self.location.coordinates.distance(
                    self.department.location.coordinates)
                distance_in_km = dist * 100
                ####
                if self.distance_rate == 0.00:
                    self.distance_rate = float(
                        SuplierSetting.objects.get().rate_per_km)
                self.travel_expenses = distance_in_km * \
                    self.distance_rate * self.no_of_resources
        else:
            dist = self.location.coordinates.distance(
                self.department.location.coordinates)
            distance_in_km = dist * 100
            self.distance_rate = float(
                SuplierSetting.objects.get().rate_per_km)
            self.travel_expenses = distance_in_km * \
                self.distance_rate * self.no_of_resources
        super().save(*args, **kwargs)


@receiver(post_delete, sender=Shift, dispatch_uid="update_event_cost")
@receiver(post_save, sender=Shift, dispatch_uid="update_event_cost")
def update_event_cost(sender, instance, **kwargs):
    event = instance.event
    event.sub_total = Shift.objects.filter(event=event).aggregate(
        Sum('total_shift_cost'))['total_shift_cost__sum']
    event.save()


@reversion.register()
class ShiftEquipment(CrewAppBaseModel):
    shift = models.ForeignKey(Shift, verbose_name=_(
        "Shift"), on_delete=models.CASCADE, related_name="shift_equipment")
    equipment = models.ForeignKey(Equipments, verbose_name=_(
        "Equipment"), on_delete=models.CASCADE, related_name="equipments")
    count = models.PositiveIntegerField(default=1)
    equipment_shift_charge = models.FloatField(
        _("Equipment Shift Charge"), default=0.00)
    equipment_cost = models.FloatField(_("Equipment Cost"), default=0.00)

    def __str__(self):
        return f'shift:{self.shift}, equipment:{self.equipment.name}({self.count})'

    def total_cost(self, *args, **kwargs):
        return self.equipment.charge_rate * self.count

    def save(self, *args, **kwargs):
        if self.equipment_shift_charge == 0.00:
            self.equipment_shift_charge = self.equipment.charge_rate
        self.equipment_cost = int(
            self.equipment_shift_charge) * int(self.count)
        super().save(*args, **kwargs)


@reversion.register()
class ShiftQualification(CrewAppBaseModel):
    shift = models.ForeignKey(Shift, verbose_name=_(
        "Shift"), on_delete=models.CASCADE, related_name="shift_qualification")
    qualification = models.ForeignKey(
        Qualification, null=True, blank=True, on_delete=models.CASCADE,
        related_name='qualification'
    )
    charge_rate = models.FloatField(_("Charge Rate"), default=0.00)
    # crew-chief details, only for Qualifications
    add_chief_charge_rate = models.FloatField(
        _("Addln. Chief Charge Rate"), default=0.00
    )
    total_add_chief_charge = models.FloatField(
        _("Total Addln. Chief Charge"), default=0.00
    )
    no_of_resources = models.PositiveIntegerField(default=0)
    qualification_cost = models.FloatField(_("Total Cost"), default=0.00)

    def __str__(self):
        return f'shift:{self.shift}, qualification:{self.qualification.name}'

    def save(self, *args, **kwargs):
        if self.charge_rate == 0.00:
            # set defualts
            self.charge_rate = self.qualification.charge_rate
            self.add_chief_charge_rate = self.qualification.chief_addl_charge_rate

        if self.shift.no_of_crew_chiefs > 0:
            self.total_add_chief_charge = (
                self.add_chief_charge_rate * self.shift.total_shift_hours * self.shift.no_of_crew_chiefs
            )
        self.qualification_cost = (
            self.charge_rate * self.shift.total_shift_hours * self.shift.no_of_resources
        )
        super().save(*args, **kwargs)


@receiver(post_save, sender=ShiftEquipment, dispatch_uid="update_shift_costs_by_equipments")
def update_shift_equipment_costs(sender, instance, **kwargs):
    instance.shift.equipment_charges = ShiftEquipment.objects.filter(
        shift=instance.shift).aggregate(Sum('equipment_cost'))['equipment_cost__sum']
    instance.shift.total_shift_cost = instance.shift.travel_expenses + \
        instance.shift.equipment_charges + instance.shift.qualification_charges
    instance.shift.save()


@receiver(post_save, sender=ShiftQualification, dispatch_uid="update_shift_costs_by_qualification")
def update_shift_qualification_costs(sender, instance, **kwargs):
    instance.shift.qualification_charges = ShiftQualification.objects.filter(
        shift=instance.shift
    ).aggregate(total_cost=Sum(F('qualification_cost') + F('total_add_chief_charge'))
    )['total_cost']
    instance.shift.total_shift_cost = instance.shift.travel_expenses + \
        instance.shift.equipment_charges + instance.shift.qualification_charges
    instance.shift.save()


@receiver(post_save, sender=Shift, dispatch_uid="find_crew")
def find_crew(sender, instance, **kwargs):
    # shift_qualification_ids = ShiftQualification.objects.filter(
    #     shift=instance).values_list('qualification__id', flat=True)
    # crew = UserQualification.objects.filter(
    #     qualification__id__in=shift_qualification_ids).values_list('profile__id', flat=True).distinct()
    from apps.scheduler.tasks import create_suggested_schedule, delete_and_create_schedule
    # transaction.on_commit(lambda: create_suggested_schedule.apply_async(
    #     args=[list(crew), instance.id]))
    # new code
    transaction.on_commit(lambda: delete_and_create_schedule.apply_async(args=[instance.id]))


class QuickQuote(CrewAppBaseModel):
    first_name = models.CharField(max_length=255, verbose_name=_("First Name"))
    last_name = models.CharField(max_length=255, verbose_name=_("Last Name"))
    email = models.EmailField(
        max_length=255, verbose_name=_("Email"), null=True, blank=True)
    phone = models.CharField(max_length=30, verbose_name=_('Phone Number'))
    event_details = models.TextField(null=True, blank=True, verbose_name=_('Event Details')
                                     )
