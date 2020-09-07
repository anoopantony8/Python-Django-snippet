import json
import logging

import requests
from django.contrib import messages
from django.core.cache import cache
from django.db import connection
from django.utils import six
from django.conf import settings
from django.utils.translation import ugettext_lazy as _

from apps.content.models import RetailerConfig
from apps.products.models import Product
from core.kinesis.tasks.producer import Publisher

from core.utils import get_default_retailer_currency
from etailpet.utils.constants import MAILCHIMP_REQUEST_TIMEOUT, KINESIS_ACTION_PRODUCT_IMPORT_MAILCHIMP
from integrations.mailchimp.helpers import get_mailchimp_oauth2_redirect_uri

# Standard logger for third_party_api_call events
logger = logging.getLogger('third_party_api_call_logger')


class MailChimpHelperClient:
    """
    MailChimp integration
    """
    # URLs
    OAUTH2_AUTHORIZE_URI = "https://login.mailchimp.com/oauth2/authorize"
    OAUTH2_ACCESS_TOKEN_URI = "https://login.mailchimp.com/oauth2/token"
    OAUTH2_BASE_URL = "https://login.mailchimp.com/oauth2/"
    OAUTH2_METADATA_URL = "https://login.mailchimp.com/oauth2/metadata"

    BATCH_URL = "/3.0/batches"
    STORES_URL = "/3.0/ecommerce/stores"
    LISTS_URL = "/3.0/lists"
    CAMPAIGN_URL = "/3.0/campaigns"

    DATA_STORE_URL_CACHE_KEY = "mail_chimp_api_url"

    # Status codes
    GENERIC_SUCCESS_CODE = 200
    BAD_REQUEST_CODE = 400

    def __init__(self, *args, **kwargs):
        self.retailer_config = RetailerConfig.get_solo()

    def get_log_data(self, extra_data={}):
        default_log_data = {
            'client': "mailchimp",
            'schema_name': connection.schema_name,
            'customer_email': "",
            "request_body": "",
            "response_body": "",
            "response_time": float(0.00),  # elapsed.total_seconds()
            "request_url": "",
            "request_method": "",
            "response_code": "",  # response.status_code
            "timeout": MAILCHIMP_REQUEST_TIMEOUT,
            "exception_msg": "",
            "exception_type": ""  # e.__class__.__name__
        }
        default_log_data.update(extra_data)
        return default_log_data

    #common function to send api request to mailchimp server
    def make_api_request(self, url, data, method="POST"):
        json_data = {}
        try:
            url = self.get_api_endpoint() + url
            logger.info("Sending request to MailChimp: %s - %s - %s", url, method, data, extra=self.get_log_data())
            response = self.get_api_response(url, data, method)
            json_data = json.loads(response.text)
            extra_data = {
                "request_body": str(data),
                "response_body": str(json_data),
                "response_time": response.elapsed.total_seconds(),
                "request_url": url,
                "response_code": response.status_code,
            }
            logger.info('API Request & Response', extra=self.get_log_data(extra_data))
        except Exception as e:
            extra_data = {
                "exception_msg": six.text_type(e),
                "exception_type": e.__class__.__name__,
                "request_method": method,
                "request_body": data,
                "request_url": url,
            }
            logger.error('Exception: Request', extra=self.get_log_data(extra_data), exc_info=True)
        return json_data

    #function to get response from mailchimp
    def get_api_response(self, url, data, method):
        if method == "GET":
            response = requests.get(url, params=data,
                                    headers={"content-type": "application/json",
                                             "Authorization": "OAuth " + self.retailer_config.mailchimp_access_token},
                                    timeout=MAILCHIMP_REQUEST_TIMEOUT)
        else:
            response = requests.post(url, data=json.dumps(data),
                                     headers={"content-type": "application/json",
                                              "Authorization": "OAuth " + self.retailer_config.mailchimp_access_token},
                                     timeout=MAILCHIMP_REQUEST_TIMEOUT)
        return response
    
    #function to post data to mailchimp in baches
    def create_in_batches(self, data, url, method="POST"):
        operations_data = []
        for d in data:
            operations_data.append({
                "method": "POST",
                "body": str(d),
                "path": url
            })
        return self.make_api_request(self.BATCH_URL, {"operations": operations_data})

    #function to create products in mailchimp ecommerce
    def create_products(self, store_id, product):
        data = {
            "id": product.id,
            "title": product.name,
            "variants": [{
                "id": product.product.id,
                "title": product.product.name,
            }]
        }
        return self.make_api_request(MailChimpHelperClient.STORES_URL + "/" + store_id + "/products", data)

    #function to create customers in mailchimp ecommerce
    def create_customer(self, customer, store_id):
        data = {
            "id": str(customer.email),
            "email_address": customer.email,
            "opt_in_status": True,
            "first_name": customer.first_name,
            "last_name": customer.last_name,
        }
        return self.make_api_request(MailChimpHelperClient.STORES_URL + "/" + store_id + "/customers", data)

    #function to create order in mailchimp ecommerce
    def create_order(self, order, customer, campaign_id=None):
        line_data = []
        store_id = self.create_store(order.store)
        if store_id:
            for line in order.lines.all():
                product_id = str(line.retailer_product.product.internal_item_number)
                product_title = str(line.retailer_product.product.title)
                products_data = {
                    "id": product_id,
                    "title": product_title,
                    "vendor": str(line.retailer_product.product.brand.name),
                    "variants": [{
                        "id": product_id,
                        "title": product_title,
                    }]
                }
                mailchimp_product = self.make_api_request(
                    MailChimpHelperClient.STORES_URL + "/" + store_id + "/products", products_data)
                line_data.append({
                    "id": str(line.id),
                    "product_id": product_id,
                    "product_variant_id": product_id,
                    "quantity": line.quantity,
                    "price": str(line.line_price_incl_tax)
                })
            # batch_data = self.create_in_batches(json.dumps(list(set(products_data))),
            #                                     MailChimpHelperClient.STORES_URL + "/" + store_id + "/products")
            mailchimp_customer_response = self.create_customer(customer, store_id)
            if campaign_id:
                data = {
                    "id": str(order.id),
                    "customer": {
                        "id": str(customer.email)
                    },
                    "currency_code": get_default_retailer_currency(),
                    "order_total": str(order.total_incl_tax),
                    "lines": line_data,
                    "campaign_id": campaign_id
                }
            else:
                data = {
                    "id": str(order.id),
                    "customer": {
                        "id": str(customer.email)
                    },
                    "currency_code": get_default_retailer_currency(),
                    "order_total": str(order.total_incl_tax),
                    "lines": line_data,
                }
            self.make_api_request(MailChimpHelperClient.STORES_URL + "/" + store_id + "/orders", data)

    #function to create stores in mailchimp ecommerce
    def create_store(self, store):
        store_id = "{}_{}".format(store.retailer.schema_name, store.id)
        data = {
            "id": str(store_id),
            "list_id": self.retailer_config.mail_chimp_list_id,
            "name": store.name,
            "domain": store.retailer.domain_url,
            "email_address": store.email,
            "currency_code": get_default_retailer_currency()
        }
        try:
            mailchimp_store = self.make_api_request(MailChimpHelperClient.STORES_URL + "/" + str(store_id), {}, "GET")
            if mailchimp_store.get('status', '') == 404:
                mailchimp_store = self.make_api_request(MailChimpHelperClient.STORES_URL, data)
                store_id = mailchimp_store['id']
            elif mailchimp_store.get('id'):
                store_id = mailchimp_store['id']
            else:
                logger.error('Exception: Request', extra=self.get_log_data({'response_body': mailchimp_store}))
                return None
        except Exception as e:
            extra_data = {
                "exception_msg": six.text_type(e),
                "exception_type": e.__class__.__name__
            }
            logger.error('Exception: Request', extra=self.get_log_data(extra_data), exc_info=True)
            return None
        return store_id

    #function to create list/audience in mailchimp
    def create_list(self, retailer):
        mailchimp_list_id = None
        if retailer.get_default_store:
            store = retailer.get_default_store
            contact = {
                "company": retailer.name,
                "address1": store.street1,
                "city": store.city,
                "state": store.state,
                "zip": store.zipcode,
                "country": retailer.origin_country
            }
            data = {
                "name": retailer.name + " List",
                "contact": contact,
                "permission_reminder": "You're signed up for our updates",
                "campaign_defaults": {
                    "from_name": retailer.name,
                    "from_email": retailer.email,
                    "subject": retailer.name + " Campaign",
                    "language": "English"
                },
                "email_type_option": False
            }
            try:
                mailchimp_list = self.make_api_request(MailChimpHelperClient.LISTS_URL, {}, "GET")
                if mailchimp_list.get('lists') and len(mailchimp_list['lists']) and mailchimp_list['lists'][0].get('id'):
                    self.retailer_config.mail_chimp_list_id = mailchimp_list['lists'][0]['id']
                    self.retailer_config.save()
                    mailchimp_list_id = self.retailer_config.mail_chimp_list_id
                elif mailchimp_list.get('lists') and len(mailchimp_list['lists']) == 0:
                    mailchimp_list = self.make_api_request(MailChimpHelperClient.LISTS_URL, data)
                    if mailchimp_list.get('id'):
                        self.retailer_config.mail_chimp_list_id = mailchimp_list["id"]
                        self.retailer_config.save()
                        mailchimp_list_id = self.retailer_config.mail_chimp_list_id
                    else:
                        extra_data = {
                            'response_body': str(mailchimp_list)
                        }
                        logger.error('Could not create list', extra=self.get_log_data(extra_data))
                else:
                    extra_data = {
                        'response_body': str(mailchimp_list)
                    }
                    logger.error('Could not create list', extra=self.get_log_data(extra_data))
            except Exception as e:
                extra_data = {
                    "exception_msg": six.text_type(e),
                    "exception_type": e.__class__.__name__
                }
                logger.error('Exception: Request', extra=self.get_log_data(extra_data), exc_info=True)
        return mailchimp_list_id

    @classmethod
    def delete_data_store_url(cls):
        cache.delete(cls.DATA_STORE_URL_CACHE_KEY)

    def get_api_endpoint(self):
        if cache.get("mail_chimp_api_url") is None:
            response = self.get_api_response(self.OAUTH2_METADATA_URL, {}, 'GET')
            json_response = response.json()
            cache.set(self.DATA_STORE_URL_CACHE_KEY, json_response["api_endpoint"])
            api_endpoint = json_response["api_endpoint"]
        else:
            api_endpoint = cache.get(self.DATA_STORE_URL_CACHE_KEY)
        return api_endpoint

    #function to get access token from mailchimp
    def connect_with_mailchimp(self, request, retailer, code):
        try:
            retailer_config = self.retailer_config
            redirect_uri = get_mailchimp_oauth2_redirect_uri(request, retailer)
            data = {
                "grant_type": "authorization_code",
                "client_id": retailer_config.mailchimp_client_id,
                "client_secret": retailer_config.mailchimp_client_secret,
                "redirect_uri": redirect_uri,
                "code": code,
            }
            response = requests.post(MailChimpHelperClient.OAUTH2_ACCESS_TOKEN_URI, data=data)
            if response.status_code == MailChimpHelperClient.GENERIC_SUCCESS_CODE:
                response = response.json()
                retailer_config.mailchimp_access_token = response['access_token']
                retailer_config.save()
            else:
                messages.error(request, _('Mailchimp connection has failed. Please try again later.'))
                return
            self.get_api_endpoint()

            if retailer_config.mailchimp_access_token and settings.KINESIS_ENABLED:
                producer = Publisher(topic=settings.KINESIS_STREAM_NAME, shard_id="1")
                data = dict()
                data['action'] = KINESIS_ACTION_PRODUCT_IMPORT_MAILCHIMP
                data['schema_name'] = request.tenant.schema_name
                producer.push(json.dumps(data))
            messages.success(request, _('Mailchimp connected successfully.'))
        except Exception as e:
            extra_data = {
                "exception_msg": six.text_type(e),
                "exception_type": e.__class__.__name__
            }
            logger.error('Exception: Request', extra=self.get_log_data(extra_data), exc_info=True)
            messages.error(request, _('Mailchimp connection has failed. Please try again later.'))

    #function to create orders in mailchimp ecommerce from POS system
    def create_order_from_pos(self, data, store_id):
        line_data = []
        customer_data = {
            "id": str(data["customer"]["email_address"]),
            "email_address": data["customer"]["email_address"],
            "opt_in_status": True,
            "first_name": data["customer"]["first_name"],
            "last_name": data["customer"]["last_name"],
        }
        customer_mailchimp_response = self.make_api_request(
            MailChimpHelperClient.STORES_URL + "/" + store_id + "/customers", customer_data)
        for line in data["lines"]:
            try:
                product = Product.objects.get(internal_item_number=line["etp_id"])
                products_data = {
                    "id": str(product.internal_item_number),
                    "title": str(product.title),
                    "vendor": str(product.brand.name),
                    "variants": [{
                        "id": str(product.internal_item_number),
                        "title": str(product.title),
                    }]
                }
                mailchimp_product = self.make_api_request(
                    MailChimpHelperClient.STORES_URL + "/" + store_id + "/products", products_data)
                line_data.append({
                    "id": "POS_" + str(line["id"]),
                    "product_id": str(line["etp_id"]),
                    "product_variant_id": str(line["etp_id"]),
                    "quantity": line["quantity"],
                    "price": str(line["line_total"])
                })
            except Exception as e:
                extra_data = {
                    "exception_msg": six.text_type(e),
                    "exception_type": e.__class__.__name__,
                    "data": str(line)
                }
                logger.error('Exception: Creating Product in MailChimp for POS order',
                             extra=self.get_log_data(extra_data), exc_info=True)
        if line_data:
            order_data = {
                "id": "POS_" + str(data["id"]),
                "customer": {
                    "id": str(data["customer"]["email_address"])
                },
                "currency_code": get_default_retailer_currency(),
                "order_total": data["total_collected"],
                "lines": line_data
            }
            order_mailchimp_response = self.make_api_request(
                MailChimpHelperClient.STORES_URL + "/" + store_id + "/orders",
                order_data)

    #function to get active campaigns in mailchimp
    def get_mailchimp_campaigns(self):
        campaigns = []
        mailchimp_campaigns = self.make_api_request(MailChimpHelperClient.CAMPAIGN_URL, {}, "GET")
        if mailchimp_campaigns.get('campaigns') and len(mailchimp_campaigns['campaigns']):
            i = 0
            for campaign in mailchimp_campaigns['campaigns']:
                if campaign['status'] == 'save':
                    campaigns.append({
                        "no": i + 1,
                        "id": campaign['id'],
                        "name": campaign['settings']['title']
                    })
        return campaigns
                   