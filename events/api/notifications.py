from datetime import datetime, timedelta

from django.conf import settings
from django.utils.translation import ugettext as _
from pinax.notifications.models import NoticeType, queue, send, send_now

from apps.accounts.models import User
from apps.events.models import Event


def send_event_status_notification(instance, request):
    """ Send notifications when Event Status is changed.
    """

    # FIXME change notificxation logic

    time = f"{datetime.now()}"
    if instance.status == Event.QUOTATION:
        # supplier = Suppliers.objects.get(id=request.tenant.id)
        user = User.objects.filter(user_type=User.ASSOCIATE_USER)
        NoticeType.create(f"quotation_{instance.id}_{time[5:-7]}", _(
            instance.name), _(instance.name + " has been changed to quotation"))
        send(user, f"quotation_{instance.id}_{time[5:-7]}", {
            "from_user": settings.DEFAULT_FROM_EMAIL})
    if request.data['status'] == Event.CONFIRMATION:
        NoticeType.create(f"confirmation_{instance.id}_{time[5:-7]}", _(
            instance.name), _(instance.name + " has been changed to confirmation"))
        send([instance.client.user], f"confirmation_{instance.id}_{time[5:-7]}",
             {"from_user": settings.DEFAULT_FROM_EMAIL})
