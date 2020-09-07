from apps.accounts.models import User
from apps.events.models import Event, Shift


def get_event_shift_status(self, request):
    """ Util function return the event/Shift status according
        to the logged in user who creates the event/shift
    """
    if request.user.user_type == User.SUPPLIER:
        return Event.QUOTATION
    else:
        return Event.ESTIMATION


def update_event_status_from_shift(event_id):
    """ function to update Event status from shifts, this takes highest
        working status from shift and returns new event status
        :params: `event_id`
    """
    _event = Event.objects.get(id=event_id)
    shifts = Shift.objects.filter(event__id=event_id)
    if shifts.filter(status=Shift.COMPLETED).exists():
        _event.status = Event.COMPLETED
    elif shifts.filter(status=Shift.ONGOING).exists():
        _event.status = Event.ONGOING
    elif shifts.filter(status=Shift.CONFIRMATION).exists():
        _event.status = Event.CONFIRMATION
    elif shifts.filter(status=Shift.QUOTATION).exists():
        _event.status = Event.QUOTATION
    elif shifts.filter(status=Shift.REQUEST_QUOTATION).exists():
        _event.status = Event.REQUEST_QUOTATION
    elif shifts.filter(status=Shift.ESTIMATION).exists():
        _event.status = Event.ESTIMATION
    _event.save()
    return _event.status
