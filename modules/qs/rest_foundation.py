#!/Library/Frameworks/Python.framework/Versions/2.7/bin/python
"""Base-level API interaction tools to be extended upon for different uses.
Generally, the intent is for extension towards the QS API, but this module
is designed to interaction with *any* REST API easier.
"""

import requests
import qs

GET = 'GET'
PUT = 'PUT'
POST = 'POST'
DELETE = 'DELETE'


class RestRequest(object):
    """Generic base request for subclassing to handle any REST API.

    This class handles the actual process of making a request, allowing
    subclasses to only have to focus on making requests for the specific API
    that's being targetted.
    This class also handles logging, via api_logging, so subclasses should
    assume that all necessary data is being logged.
    Note that this class cannot be used by itself to make a request - it
    requires a subclass to set base_url.

    Static Attributes:
        Base attributes that will be included in all requests, and that should
        be overriden in subclasses and set per-request (if necessary) in
        prepare() or by overriding make_request():
            base_url
            base_params
            base_request_data
            base_headers

    Instance Attributes:
        uri: The URI string that the request is being made at. This will be
            appended to base_uri and so should be specific to the request.
            Generally, uri should begin with '/'.
        params: A dictionary of request-specific params to include.
        headers: A dictionary of request-specific headers to include.
        request_data: A dictionary of request-specific data to include.
        critical: A boolean indicating whether or not to exit if this request
            fails.
        Silent: A boolean indicating whether or not this request should be
            logged or stay silent.
        verb: The HTTP verb to use, in all caps, such as: 'GET' or 'POST'
        base_uri:

        (filled after make_request())
        response: Raw, complete Request object. To check if the request has
            been made, check if response is not None.
        successful: A boolean indicating whether the request was successfulful.
        data: The data cleaned from the request. This carries the actual body.
            of the data, and subclasses should ensure that if there's usable
            data in the response, self.data reflects this. If there was an
            error, data will be {} to avoid errors in iterators that use it.

    Args:
        description: a description of this request. It should be in the form of
            "{verb} {noun}", like "GET data" or "POST results".
        uri: the uri of the resource to make the request at, beginning with '/'
        kwargs can include:
            silent to set request to silent
    """
    base_url = ''
    base_params = {}
    base_request_data = {}
    base_headers = {}

    def __init__(self, description, uri, **kwargs):
        self.description = description
        self.uri = uri

        self.params = {}
        self.request_data = {}
        self.headers = {}
        self.silent = True if kwargs.get('silent') is True else False
        self.critical = False
        self.verb = 'GET'

        self.response = None
        self.data = None
        self.successful = None

    def make_request(self):
        """Make the request at the uri with specified data and params.

        If silent is False, then the data will be logged before and after the
        request with vital information. If critical is True, then if the
        request fails, sys.exit() will be called.

        Returns:
            The data received in the response. This reflects the actual body
            of the data, such as a list of students, not the successful tag.
        """
        self._before_request()
        self._log_before()

        qs.rate_limiting.register_request(self._full_url())
        self.response = requests.request(
            self.verb,
            self._full_url(),
            params=self._full_params(),
            data=self._full_data(),
            headers=self._full_headers())
        qs.rate_limiting.register_response(self.response)

        self._process_response()
        self._after_response()
        self._log_after()
        return self.data

    def set_api_key(self, api_key):
        self.api_key = api_key
        self.params.update({'apiKey': api_key})

    def _before_request(self):
        """Hook to make any modifications to the request before making it."""
        pass

    def _after_response(self):
        """Hook after response (and after _process_response)"""
        pass

    def _process_response(self):
        """Process the response after the fact and collect necessary info.
        This should be overridden to extract more info than given here.
        """
        self.successful = self._get_successful()
        self.data = self._get_data()

    def _get_data(self):
        """Return to fill self.data based on the content of the response."""
        return self.response.json() if self.successful else {}

    def _get_successful(self):
        return self.response.status_code == 200

    def _log_before(self):
        if self.silent: return
        qs.logger.info(self, self._log_dict(), is_request=True)

    def _log_after(self):
        # TODO: include response_type in log
        if self.silent: return
        args = [self, self._log_dict()]
        kwargs = {'is_response': True}
        if self.successful:
            qs.logger.info(*args, **kwargs)
        else:
            if self.critical:
                qs.logger.critical(*args, **kwargs)
            else:
                qs.logger.error(*args, cc_print=True, **kwargs)

    def _log_dict(self):
        """The dict-based description of this request, mainly for logging

        #TODO: add the full URL with params so that it can be repeated via curl
        """
        desc = {
            'URI': self.uri,
            'full URI': self._full_url(),
            'params': self._full_params(),
            'request body': self._full_data(),
            'headers': self._full_headers(),
            'verb': self.verb
        }
        if self.response:
            desc['HTTP status code'] = self.response.status_code
            desc['successful'] = self.successful
            desc['response data'] = self.data
        if self.successful is False:
            desc['response body'] = self.response.text
            try:
                desc['response JSON'] = self.response.json()
            except ValueError:
                desc['response JSON'] = "Invalid JSON"
        return desc

    def _full_url(self):
        return self.base_url + self.uri

    def _full_params(self):
        return qs.merge(self.base_params, self.params)

    def _full_data(self):
        return qs.merge(self.base_request_data, self.request_data)

    def _full_headers(self):
        return qs.merge(self.base_headers, self.headers)

    def __repr__(self):
        return '<{} {} at {}>'.format(
            self.__class__.__name__,
            self.description,
            self.uri)


class APIWrapper(object):
    """Generic class for making a wrapper around a REST API.

    For now, this only supports APIs that authenticate with an API key or do
    not authenticate at all.

    The only constants within an API wrapper of a specific class is those that
    are passed as params to the __init__ function. If any value that was used
    to instantiate the objet changes, then a new APIWrapper should be made.

    Attributes:
        identifier: the identifier of the server/app being accessed
        api_key: the API key for accessing that server, as per the API key
            store
    Args:
        identifier: the identifier of the server/app being accessed. This will
            be used to store and retrieve the API key from the API key store.
            If the identifier is not already stored in the API key store, set
            it via commandline with `qs.api_keys.set('identifier', 'value')`
    """

    def __init__(self, identifier):
        self.identifier = identifier
        self.api_key = qs.api_keys.get(identifier)
