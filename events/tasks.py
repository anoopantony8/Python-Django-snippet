import urllib.parse
from datetime import datetime, timedelta

from celery import shared_task

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.utils.translation import ugettext as _
from django.utils import timezone

from apps.events.models import Event
from apps.invoice.utils import generate_invoice


@shared_task
def send_invoice_email(event):

    event = Event.objects.get(id=event)
    html_content = render_to_string(
        'events/email/invoice-mail.html', {
            'event': Event}
    )
    plain_content = strip_tags(html_content)
    subject = _("Invoice - " + event.name)

    my_email = EmailMultiAlternatives(
        subject, plain_content, settings.DEFAULT_FROM_EMAIL, [
            event.client.user.email, ]
    )
    pdf = generate_invoice(event)
    my_email.attach('invoice.pdf', pdf, 'application/pdf')
    my_email.attach_alternative(html_content, "text/html")
    my_email.send(fail_silently=False)
