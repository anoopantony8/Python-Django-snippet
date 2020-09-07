from django.utils.translation import ugettext as _

STATUS = (
    (1, _('Completed')),
    (2, _('Inprogress')),
    (3, _('Pending'))
)

EVENT_STATUS = (
    (1, _('Estimation')),
    (2,_('Request Quotation')),
    (3, _('Quotation')),
    (4, _('Confirmation')),
    (5, _('Completed')),
    (6, _('Declined'))
)
