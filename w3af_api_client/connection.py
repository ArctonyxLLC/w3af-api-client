import requests
import logging
import json
import six
from requests.compat import urljoin

# These two lines enable debugging at httplib level
# (requests->urllib3->http.client) You will see the REQUEST, including HEADERS
# and DATA, and RESPONSE with HEADERS but without DATA.
# The only thing missing will be the response.body which is not logged.
if six.PY3:
    import http.client as http_client
else:
    # Python 2
    import http.client as http_client


from . import __VERSION__
from .utils.constants import ISSUE_URL
from .scan import Scan
from .utils.exceptions import (APIException,
                                              ForbiddenException,
                                              NotFoundException,
                                              BadRequestException)


api_logger = logging.getLogger(__name__)

API_EXCEPTIONS = {400: BadRequestException,
                  403: ForbiddenException,
                  404: NotFoundException}


class Connection(object):

    def __init__(self, api_url, verbose=False, timeout=5, verify=True):
        self.api_url = api_url
        self.session = None
        self.timeout = timeout

        self.set_verbose(verbose)
        self.configure_requests(verify)
        self.can_access_api()

    def can_access_api(self):
        """
        :return: True when we can access the REST API
        """
        try:
            version_dict = self.get_version()
        except Exception as e:
            msg = 'An exception was raised when connecting to REST API: "%s"'
            raise APIException(msg % e)
        else:
            """
            This is an example response from the REST API
            {
                "branch": "develop",
                "dirty": "Yes",
                "revision": "f1cae98161 - 24 Jun 2015 16:29",
                "version": "1.7.2"
            }
            """
            if 'version' in version_dict:
                # Yup, this looks like a w3af REST API
                return True

            msg = 'Unexpected HTTP response when connecting to REST API'
            raise APIException(msg)

    def get_version(self):
        code, version_dict = self.send_request('/version')
        return version_dict

    def set_verbose(self, verbose):
        # Get level based on verbose boolean
        level = logging.DEBUG if verbose else logging.CRITICAL

        # Configure my own logger
        api_logger.setLevel(level=level)

        ch = logging.StreamHandler()
        ch.setLevel(level)

        formatter = logging.Formatter('%(message)s')
        ch.setFormatter(formatter)
        api_logger.addHandler(ch)

        # Configure the loggers for urllib3, requests and httplib
        requests_log = logging.getLogger("requests.packages.urllib3")
        requests_log.setLevel(level)
        requests_log.propagate = True

        requests_log = logging.getLogger("requests")
        requests_log.setLevel(level)

        http_client.HTTPConnection.debuglevel = 1 if verbose else 0

    def configure_requests(self, verify):
        self.session = requests.Session()
        self.session.verify = verify

        headers = {'Content-Type': 'application/json',
                   'Accept': 'application/json',
                   'User-Agent': 'REST API Client %s' % __VERSION__}
        self.session.headers.update(headers)

    def send_request(self, path, json_data=None, method='GET'):
        full_url = urljoin(self.api_url, path)

        if method == 'GET':
            response = self.session.get(full_url, timeout=self.timeout)

        elif method == 'DELETE':
            response = self.session.delete(full_url, timeout=self.timeout)

        elif method == 'POST':
            data = json.dumps(json_data)
            response = self.session.post(full_url, data=data,
                                         timeout=self.timeout)

        else:
            raise ValueError('Invalid HTTP method: "%s"' % method)

        try:
            json_data = response.json()
        except ValueError:
            msg = ('REST API service did not return JSON, if this issue'
                   ' persists please create an issue in the w3af framework'
                   ' repository at %s. The response body starts with: "%s"')
            raise APIException(msg % (ISSUE_URL, response.content[:20]))

        pretty_json = json.dumps(json_data, indent=4)
        msg = 'Received %s HTTP response from the wire:\n%s'
        api_logger.debug(msg % (response.status_code, pretty_json))

        #
        # Error handling
        #
        if response.status_code in API_EXCEPTIONS:
            error = json_data.get('message', None)
            exception_klass = API_EXCEPTIONS.get(response.status_code)

            if error is not None:
                raise exception_klass(error)
            else:
                msg = ('REST API service did not return the expected "message"'
                       ' attribute for the %s response. Please create a new'
                       ' issue in the w3af framework repository at %s with'
                       ' this JSON data:\n\n%s')
                dump = json.dumps(json_data, indent=4)
                args = (response.status_code, ISSUE_URL, dump)
                raise APIException(msg % args)

        return response.status_code, json_data

    def get_scans(self):
        """
        :return: A list with all the Scan instances available in the remote API
        """
        code, data = self.send_request('/scans/', method='GET')

        if code != 200:
            msg = 'Failed to retrieve scans. Unexpected code %s'
            raise APIException(msg % code)

        scans = data.get('items', None)

        if scans is None:
            raise APIException('Failed to retrieve scans, no "items" in JSON.')

        scan_instances = []
        for scan_json in scans:
            scan_id = scan_json['id']
            scan_status = scan_json['status']
            scan = Scan(self, scan_id=scan_id, status=scan_status)
            scan_instances.append(scan)

        return scan_instances
