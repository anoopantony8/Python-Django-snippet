import json
# import logging

from rest_framework.response import Response
from rest_framework import status
from oauth2_provider.contrib.rest_framework import TokenHasReadWriteScope
from tenant_schemas.utils import schema_context

from django.utils.translation import ugettext_lazy as _
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings

from mailchimp.client import MailChimpHelperClient
from api.views import TenantAPIView

# logger = logging.getLogger('third_party_api_call_logger')

@method_decorator(csrf_exempt, name="dispatch")
class MailChimpPOSView(TenantAPIView):
    permission_classes = [TokenHasReadWriteScope, ]

    def post(self, request, *args, **kwargs):
        post_data = request.data
        if self.request.tenant.is_mailchimp_enabled:
            try:
                data = json.loads(data_set.decode("utf-8"))
                with schema_context(self.request.tenant.schema_name):
                    mailchimp = MailChimpHelperClient()
                    retailer = get_object_or_404(Retailer, schema_name=self.request.tenant.schema_name)
                    retailer_config = RetailerConfig.get_solo()
                    if not retailer_config.mail_chimp_list_id:
                        mailchimp_list_id = mailchimp.create_list(retailer)
                        if mailchimp_list_id:
                            store = Store.objects.get(id=post_data['store_id'])
                            mailchimp_store = mailchimp.create_store(store)
                            if mailchimp_store:
                                mailchimp.create_order_from_pos(post_data, mailchimp_store)
                                return Response(status=status.HTTP_200_OK)
            except Exception as e:
                logger.error(e, exc_info=True)
        errors = {
            "mailChimp": _("MailChimp is not connected")
        }
        return Response(errors, status=404)        
