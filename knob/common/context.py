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
import datetime
import os
from keystoneauth1.identity import v3
from keystoneauth1 import token_endpoint
from keystoneauth1 import session
from keystoneclient import client as keystone_client

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


class MyRequestContext(context.RequestContext):
    """Stores information about the security context.

    Under the security context the user accesses the system, as well as
    additional request information.
    """
    def __init__(self, user_id=None, tenant_id=None, is_admin=None, roles=None,
                 timestamp=None, request_id=None, tenant_name=None,
                 user_name=None, overwrite=True, auth_token=None,
                 **kwargs):
        """Object initialization.
        :param overwrite: Set to False to ensure that the greenthread local
            copy of the index is not overwritten.
        :param kwargs: Extra arguments that might be present, but we ignore
            because they possibly came in from older rpc messages.
        """
        super(MyRequestContext, self).__init__(auth_token=auth_token,
                                          user=user_id, tenant=tenant_id,
                                          is_admin=is_admin,
                                          request_id=request_id,
                                          overwrite=overwrite,
                                          roles=roles)
        self.user_name = user_name
        self.tenant_name = tenant_name
        self._session = None
        self._neutron_client = None
        self._barbican_client = None
        self._nova_client = None
        
        self.policy = policy.Enforcer()

        if not timestamp:
            timestamp = datetime.datetime.utcnow()
        self.timestamp = timestamp
        #if self.is_admin is None:
        #    print('in context before policy')
        #    self.is_admin = policy.check_is_admin(self)
        #else:
        #    self.is_admin = is_admin
            
        if auth_token is not None:
            auth_url = cfg.CONF.auth_url
            password = cfg.CONF.os_privileged_user_password
            auth = v3.Password(auth_url=auth_url,
                           username=user_name,
                           password=password,
                           project_name=tenant_name,
                           user_domain_id='default',
                           project_domain_name='default')
            self._keystone_session = session.Session(auth=auth, verify=False)
            
                    
    @property
    def project_id(self):
        return self.tenant

    @property
    def tenant_id(self):
        return self.tenant

    @tenant_id.setter
    def tenant_id(self, tenant_id):
        self.tenant = tenant_id

    @property
    def user_id(self):
        return self.user

    @user_id.setter
    def user_id(self, user_id):
        self.user = user_id

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
            self._nova_client = nova.NovaClient(self._keystone_session)
        return self._nova_client


def get_admin_context(show_deleted=False):
    return MyRequestContext(is_admin=True, show_deleted=show_deleted)


class ContextMiddleware(wsgi.Middleware):

    def __init__(self, app, conf, **local_conf):
        # Determine the context class to use
        self.ctxcls = MyRequestContext
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
        print ('context')
        print(req.context)


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
