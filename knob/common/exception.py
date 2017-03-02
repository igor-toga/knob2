# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""Knob base exception handling.

Includes decorator for re-raising Knob-type exceptions.

SHOULD include dedicated exception logging.

"""

import sys

from oslo_config import cfg
from oslo_log import log as logging
from oslo_versionedobjects import exception as obj_exc
from oslo_utils import reflection
import six
import webob.exc
from webob.util import status_generic_reasons
from webob.util import status_reasons

from knob.common.i18n import _, _LE


LOG = logging.getLogger(__name__)

exc_log_opts = [
    cfg.BoolOpt('fatal_exception_format_errors',
                default=False,
                help='Make exception message format errors fatal.'),
]

CONF = cfg.CONF
CONF.register_opts(exc_log_opts)


class ConvertedException(webob.exc.WSGIHTTPException):
    def __init__(self, code=500, title="", explanation=""):
        self.code = code
        # There is a strict rule about constructing status line for HTTP:
        # '...Status-Line, consisting of the protocol version followed by a
        # numeric status code and its associated textual phrase, with each
        # element separated by SP characters'
        # (http://www.faqs.org/rfcs/rfc2616.html)
        # 'code' and 'title' can not be empty because they correspond
        # to numeric status code and its associated text
        if title:
            self.title = title
        else:
            try:
                self.title = status_reasons[self.code]
            except KeyError:
                generic_code = self.code // 100
                self.title = status_generic_reasons[generic_code]
        self.explanation = explanation
        super(ConvertedException, self).__init__()


class Error(Exception):
    pass


class KnobException(Exception):
    """Base Knob Exception

    To correctly use this class, inherit from it and define
    a 'message' property. That message will get printf'd
    with the keyword arguments provided to the constructor.

    """
    message = _("An unknown exception occurred.")
    code = 500
    headers = {}
    safe = False

    def __init__(self, message=None, **kwargs):
        self.kwargs = kwargs
        self.kwargs['message'] = message

        if 'code' not in self.kwargs:
            try:
                self.kwargs['code'] = self.code
            except AttributeError:
                pass

        for k, v in self.kwargs.items():
            if isinstance(v, Exception):
                self.kwargs[k] = six.text_type(v)

        if self._should_format():
            try:
                message = self.message % kwargs

            except Exception:
                exc_info = sys.exc_info()
                # kwargs doesn't match a variable in the message
                # log the issue and the kwargs
                LOG.exception(_LE('Exception in string format operation'))
                for name, value in kwargs.items():
                    LOG.error(_LE("%(name)s: %(value)s"),
                              {'name': name, 'value': value})
                if CONF.fatal_exception_format_errors:
                    six.reraise(*exc_info)
                # at least get the core message out if something happened
                message = self.message
        elif isinstance(message, Exception):
            message = six.text_type(message)

        # NOTE(luisg): We put the actual message in 'msg' so that we can access
        # it, because if we try to access the message via 'message' it will be
        # overshadowed by the class' message attribute
        self.msg = message
        super(KnobException, self).__init__(message)

    def _should_format(self):
        return self.kwargs['message'] is None or '%(message)' in self.message

    def __unicode__(self):
        return six.text_type(self.msg)


class HTTPExceptionDisguise(Exception):
    """Disguises HTTP exceptions.

    They can be handled by the webob fault application in the wsgi pipeline.
    """

    def __init__(self, exception):
        self.exc = exception
        self.tb = sys.exc_info()[2]


class RequestLimitExceeded(KnobException):
    msg_fmt = _('Request limit exceeded: %(message)s')


class Invalid(KnobException):
    message = _("Unacceptable parameters.")
    code = 400


class InvalidInput(KnobException):
    message = _("Unacceptable parameters.")
    code = 400


class NotFound(KnobException):
    message = _("Resource could not be found.")
    code = 404
    safe = True

class NotAuthorized(KnobException):
    message = _("Not authorized.")
    code = 403


class AdminRequired(NotAuthorized):
    message = _("User does not have admin privileges")


class ObjectUpdateForbidden(KnobException):
    message = _("Unable to update the following object fields: %(fields)s")


class SIGHUPInterrupt(KnobException):
    message = _("System SIGHUP signal received.")


class InvalidContentType(KnobException):
    message = _("Invalid content type %(content_type)s")


class ServiceNotFound(NotFound):

    def __init__(self, message=None, **kwargs):
        if kwargs.get('host', None):
            self.message = _("Service %(service_id)s could not be "
                             "found on host %(host)s.")
        else:
            self.message = _("Service %(service_id)s could not be found.")
        super(ServiceNotFound, self).__init__(None, **kwargs)


class DbObjectDuplicateEntry(KnobException):
    message = _("Failed to create a duplicate %(object_type)s: "
                "for attribute(s) %(attributes)s with value(s) %(values)s")

    def __init__(self, object_class, db_exception):
        super(DbObjectDuplicateEntry, self).__init__(
            object_type=reflection.get_class_name(object_class,
                                                  fully_qualified=False),
            attributes=db_exception.columns,
            values=db_exception.value)


class PrimaryKeyMissing(KnobException):
    message = _("For class %(object_type)s missing primary keys: "
                "%(missing_keys)s")

    def __init__(self, object_class, missing_keys):
        super(PrimaryKeyMissing, self).__init__(
            object_type=reflection.get_class_name(object_class,
                                                  fully_qualified=False),
            missing_keys=missing_keys
        )

class EntityNotFound(KnobException):
    msg_fmt = _("The %(entity)s (%(name)s) could not be found.")

    def __init__(self, entity=None, name=None, **kwargs):
        self.entity = entity
        self.name = name
        super(EntityNotFound, self).__init__(entity=entity, name=name,
                                             **kwargs)

class Forbidden(KnobException):
    msg_fmt = _("You are not authorized to use %(action)s.")

    def __init__(self, action='this action'):
        super(Forbidden, self).__init__(action=action)


class AuthorizationFailure(KnobException):
    msg_fmt = _("Authorization failed.")
