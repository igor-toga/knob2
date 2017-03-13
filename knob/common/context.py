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
import os
from keystoneauth1.identity import v3
from keystoneauth1 import session

from oslo_config import cfg
from oslo_context import context
from oslo_log import log as logging
from oslo_middleware import request_id as oslo_request_id
from oslo_utils import importutils
import six
import oslo_messaging

from knob.common import exception
from knob.common import policy
from knob.common import wsgi
from knob.db.sqlalchemy import api as db_api
from knob.clients import neutron
from knob.clients import barbican
from knob.clients import nova

LOG = logging.getLogger(__name__)


class RequestContext(context.RequestContext):
    """Stores information about the security context.

    Under the security context the user accesses the system, as well as
    additional request information.
    """

    def __init__(self, roles=None, is_admin=None, read_only=False,
                 show_deleted=False, overwrite=True, request_id=None,
                 **kwargs):
        """Initialisation of the request context.

        :param overwrite: Set to False to ensure that the greenthread local
            copy of the index is not overwritten.
        """
        super(RequestContext, self).__init__(is_admin=is_admin,
                                             read_only=read_only,
                                             show_deleted=show_deleted,
                                             request_id=request_id,
                                             roles=roles,
                                             overwrite=overwrite,
                                             **kwargs)

        
        
        self._session = None
        self._neutron_client = None
        self._barbican_client = None
        self._nova_client = None
        auth = v3.Password(auth_url=os.environ['OS_AUTH_URL'],
                           username=os.environ['OS_USERNAME'],
                           password=os.environ['OS_PASSWORD'],
                           project_name=os.environ['OS_PROJECT_NAME'],
                           user_domain_id=os.environ['OS_USER_DOMAIN_ID'],
                           project_domain_name=os.environ['OS_PROJECT_DOMAIN_ID'])
        
        # sess = session.Session(auth=auth, verify='/path/to/ca.cert')
        self._keystone_session = session.Session(auth=auth, verify=False)
        self.policy = policy.Enforcer()

        if is_admin is None:
            self.is_admin = self.policy.check_is_admin(self)
        else:
            self.is_admin = is_admin

        # context scoped cache dict where the key is a class of the type of
        # object being cached and the value is the cache implementation class
        self._object_cache = {}


    @property
    def session(self):
        if self._session is None:
            self._session = db_api.get_session()
        return self._session

    @property
    def neutron_client(self):
        if self._neutron_client is None:
            self._neutron_client = neutron.NeutronClient(self._keystone_session)
        return self._neutron_client
        
    @property
    def barbican_client(self):
        if self._barbican_client is None:
            self._barbican_client = barbican.BarbicanClient(self._keystone_session)
        return self._barbican_client
    
    @property
    def nova_client(self):
        if self._nova_client is None:
            self._nova_client = nova.nova_client(self._keystone_session)
        return self._nova_client


def get_admin_context(show_deleted=False):
    return RequestContext(is_admin=True, show_deleted=show_deleted)


class ContextMiddleware(wsgi.Middleware):

    def __init__(self, app, conf, **local_conf):
        # Determine the context class to use
        self.ctxcls = RequestContext
        if 'context_class' in local_conf:
            self.ctxcls = importutils.import_class(local_conf['context_class'])

        super(ContextMiddleware, self).__init__(app)

    def process_request(self, req):
        """Constructs an appropriate context from extracted auth information.

        Extract any authentication information in the request and construct an
        appropriate context from it.
        """
        environ = req.environ
        req_id = environ.get(oslo_request_id.ENV_REQUEST_ID)

        req.context = self.ctxcls.from_environ(
            environ,
            request_id=req_id)


def ContextMiddleware_filter_factory(global_conf, **local_conf):
    """Factory method for paste.deploy."""
    conf = global_conf.copy()
    conf.update(local_conf)

    def filter(app):
        return ContextMiddleware(app, conf)

    return filter


def request_context(func):
    @six.wraps(func)
    def wrapped(self, ctx, *args, **kwargs):
        try:
            return func(self, ctx, *args, **kwargs)
        except exception.KnobException:
            raise oslo_messaging.rpc.dispatcher.ExpectedException()
    return wrapped
