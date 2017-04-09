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

import collections

from novaclient import client as nova_client
from novaclient import exceptions
from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import uuidutils
from oslo_utils import excutils
from retrying import retry
import six
from six.moves.urllib import parse as urlparse

import requests

from knob.common import exception
from knob.common.i18n import _
from knob.common.i18n import _LW

LOG = logging.getLogger(__name__)


NOVA_API_VERSION = "2.1"
CLIENT_NAME = 'nova'



def retry_if_connection_err(exception):
    return isinstance(exception, requests.ConnectionError)


def retry_if_result_is_false(result):
    return result is False


class NovaClient(object):

    deferred_server_statuses = ['BUILD',
                                'HARD_REBOOT',
                                'PASSWORD',
                                'REBOOT',
                                'RESCUE',
                                'RESIZE',
                                'REVERT_RESIZE',
                                'SHUTOFF',
                                'SUSPENDED',
                                'VERIFY_RESIZE']



    def __init__(self, sess):
        self._client = nova_client.Client(NOVA_API_VERSION, session=sess)
    
    def client(self):
        if self._client is None:
            raise exception.NotFound('nova object not found')
        return self._client

    def keypair_create(self, key_name):
        client = self.client()
        key = client.keypairs.create(key_name)
        return key
    
    def keypair_delete(self, key_name):
        client = self.client()
        client.keypairs.delete(key_name)

    def create_service_vm(self, data):
        #nics = [{"net-id": net_id, "v4-fixed-ip": ''}]
        
        client = self.client()  
        # verify keypair
        key=data['key']
        if client.keypairs.get(key) is None:
            LOG.warning(_LW('Provided key with name (%(name)s)'), 
                        {'name': key})
            return None
        
        image = client.images.find(name=data['image'])
        flavor = client.flavors.find(name=data['flavor'])
        server_ref = None
        try:
            nics = [{'port-id': data['port-id']}]
            server_ref = client.servers.create(
                name=data['name'], 
                image=image, 
                flavor=flavor, 
                nics=nics,
                security_groups=[data['security_groups']], 
                key_name=key)
            print ('returned: %s' % server_ref)
        finally:
            if server_ref is not None:
                server_id = server_ref.id
        
        try:
            print ('server_id: %s' % server_id)
            # wait till server is ready
            self._check_active(server_id)
            
        except exception.ResourceInError as ex:
            LOG.warning(_LW('Instance (%(server)s) not found: %(ex)s'),
                        {'server': server_id, 'ex': ex})
        except exception.ResourceUnknownStatus as ex:
            LOG.warning(_LW('Instance (%(server)s) bad status while creating: %(ex)s'),
                        {'server': server_id, 'ex': ex})
        
        print('service is up')
        return server_id
    
    def remove_service_vm(self, server_id):
        self.client().servers.delete(server_id)
        
        try:
            # wait till server is down
            self.check_delete_server_complete(server_id)
        except exception.ServiceNotFound as ex:
            LOG.warning(_LW('Instance (%(server)s) bad status while deleting: %(ex)s'),
                        {'server': server_id, 'ex': ex})
        print('successfully removed VM with server_id: %s' % server_id)
        return
    
    #--------------------------------------------------------------
    def is_not_found(self, ex):
        return isinstance(ex, exceptions.NotFound)

    def is_conflict(self, ex):
        return isinstance(ex, exceptions.Conflict)
    
    @excutils.exception_filter
    def ignore_not_found(self, ex):
        """Raises the exception unless it is a not-found."""
        return self.is_not_found(ex)

    @excutils.exception_filter
    def ignore_conflict_and_not_found(self, ex):
        """Raises the exception unless it is a conflict or not-found."""
        return self.is_conflict(ex) or self.is_not_found(ex)

    def is_unprocessable_entity(self, ex):
        http_status = (getattr(ex, 'http_status', None) or
                       getattr(ex, 'code', None))
        return (isinstance(ex, exceptions.ClientException) and
                http_status == 422)

    @retry(stop_max_attempt_number=max(cfg.CONF.client_retry_limit + 1, 0),
           retry_on_exception=retry_if_connection_err)
    def get_server(self, server):
        """Return fresh server object.

        Substitutes Nova's NotFound for Heat's EntityNotFound,
        to be returned to user as HTTP error.
        """
        try:
            return self.client().servers.get(server)
        except exceptions.NotFound:
            raise exception.EntityNotFound(entity='Server', name=server)

    def fetch_server(self, server_id):
        """Fetch fresh server object from Nova.

        Log warnings and return None for non-critical API errors.
        Use this method in various ``check_*_complete`` resource methods,
        where intermittent errors can be tolerated.
        """
        server = None
        try:
            server = self.client().servers.get(server_id)
        except exceptions.OverLimit as exc:
            LOG.warning(_LW("Received an OverLimit response when "
                            "fetching server (%(id)s) : %(exception)s"),
                        {'id': server_id,
                         'exception': exc})
        except exceptions.ClientException as exc:
            if ((getattr(exc, 'http_status', getattr(exc, 'code', None)) in
                 (500, 503))):
                LOG.warning(_LW("Received the following exception when "
                            "fetching server (%(id)s) : %(exception)s"),
                            {'id': server_id,
                             'exception': exc})
            else:
                raise
        return server


    def get_ip(self, server_id, net_type, ip_version):
        """Return the server's IP of the given type and version."""
        server = self.get_server(server_id)
        if net_type in server.addresses:
            for ip in server.addresses[net_type]:
                if ip['version'] == ip_version:
                    return ip['addr']

    def get_status(self, server):
        """Return the server's status.

        :param server: server object
        :returns: status as a string
        """
        # Some clouds append extra (STATUS) strings to the status, strip it
        return server.status.split('(')[0]

    @retry(stop_max_attempt_number=cfg.CONF.max_interface_check_attempts,
           wait_fixed=500,
           retry_on_result=retry_if_result_is_false)
    def _check_active(self, server, res_name='Server'):
        """Check server status.

        Accepts both server IDs and server objects.
        Returns True if server is ACTIVE,
        raises errors when server has an ERROR or unknown to Heat status,
        returns False otherwise.

        :param res_name: name of the resource to use in the exception message

        """
        # not checking with is_uuid_like as most tests use strings e.g. '1234'
        if isinstance(server, six.string_types):
            server = self.fetch_server(server)
            if server is None:
                return False
            else:
                status = self.get_status(server)
        else:
            status = self.get_status(server)
            if status != 'ACTIVE':
                self.refresh_server(server)
                status = self.get_status(server)

        if status in self.deferred_server_statuses:
            return False
        elif status == 'ACTIVE':
            return True
        elif status == 'ERROR':
            fault = getattr(server, 'fault', {})
            raise exception.ResourceInError(
                resource_status=status,
                status_reason=_("Message: %(message)s, Code: %(code)s") % {
                    'message': fault.get('message', _('Unknown')),
                    'code': fault.get('code', _('Unknown'))
                })
        else:
            raise exception.ResourceUnknownStatus(
                resource_status=server.status,
                result=_('%s is not active') % res_name)

    def find_flavor_by_name_or_id(self, flavor):
        """Find the specified flavor by name or id.

        :param flavor: the name of the flavor to find
        :returns: the id of :flavor:
        """
        return self._find_flavor_id(self.context.tenant_id,
                                    flavor)

    def _find_flavor_id(self, tenant_id, flavor):
        # tenant id in the signature is used for the memoization key,
        # that would differentiate similar resource names across tenants.
        return self.get_flavor(flavor).id

    def get_flavor(self, flavor_identifier):
        """Get the flavor object for the specified flavor name or id.

        :param flavor_identifier: the name or id of the flavor to find
        :returns: a flavor object with name or id :flavor:
        """
        try:
            flavor = self.client().flavors.get(flavor_identifier)
        except exceptions.NotFound:
            flavor = self.client().flavors.find(name=flavor_identifier)

        return flavor

    def get_host(self, host_name):
        """Get the host id specified by name.

        :param host_name: the name of host to find
        :returns: the list of match hosts
        :raises: exception.EntityNotFound
        """

        host_list = self.client().hosts.list()
        for host in host_list:
            if host.host_name == host_name and host.service == self.COMPUTE:
                return host

        raise exception.EntityNotFound(entity='Host', name=host_name)

    def get_keypair(self, key_name):
        """Get the public key specified by :key_name:

        :param key_name: the name of the key to look for
        :returns: the keypair (name, public_key) for :key_name:
        :raises: exception.EntityNotFound
        """
        try:
            return self.client().keypairs.get(key_name)
        except exceptions.NotFound:
            raise exception.EntityNotFound(entity='Key', name=key_name)

    @retry(stop_max_attempt_number=cfg.CONF.max_interface_check_attempts,
           wait_fixed=500,
           retry_on_result=retry_if_result_is_false)
    def check_delete_server_complete(self, server_id):
        """Wait for server to disappear from Nova."""
        try:
            server = self.fetch_server(server_id)
        except Exception as exc:
            self.ignore_not_found(exc)
            return True
        if not server:
            return False
        task_state_in_nova = getattr(server, 'OS-EXT-STS:task_state', None)
        # the status of server won't change until the delete task has done
        if task_state_in_nova == 'deleting':
            return False

        status = self.get_status(server)
        if status in ("DELETED", "SOFT_DELETED"):
            return True
        if status == 'ERROR':
            fault = getattr(server, 'fault', {})
            message = fault.get('message', 'Unknown')
            code = fault.get('code')
            errmsg = _("Server %(name)s delete failed: (%(code)s) "
                       "%(message)s") % dict(name=server.name,
                                             code=code,
                                             message=message)
            raise exception.ServiceNotFound(resource_status=status,
                                            status_reason=errmsg)
        return False

    def rename(self, server, name):
        """Update the name for a server."""
        server.update(name)

    def server_to_ipaddress(self, server):
        """Return the server's IP address, fetching it from Nova."""
        try:
            server = self.client().servers.get(server)
        except exceptions.NotFound as ex:
            LOG.warning(_LW('Instance (%(server)s) not found: %(ex)s'),
                        {'server': server, 'ex': ex})
        else:
            for n in sorted(server.networks, reverse=True):
                if len(server.networks[n]) > 0:
                    return server.networks[n][0]

    @retry(stop_max_attempt_number=max(cfg.CONF.client_retry_limit + 1, 0),
           retry_on_exception=retry_if_connection_err)
    def absolute_limits(self):
        """Return the absolute limits as a dictionary."""
        limits = self.client().limits.get()
        return dict([(limit.name, limit.value)
                    for limit in list(limits.absolute)])


    def interface_detach(self, server_id, port_id):
        server = self.fetch_server(server_id)
        if server:
            server.interface_detach(port_id)
            return True
        else:
            return False

    def interface_attach(self, server_id, port_id=None, net_id=None, fip=None):
        server = self.fetch_server(server_id)
        if server:
            server.interface_attach(port_id, net_id, fip)
            return True
        else:
            return False

    @retry(stop_max_attempt_number=cfg.CONF.max_interface_check_attempts,
           wait_fixed=500,
           retry_on_result=retry_if_result_is_false)
    def check_interface_detach(self, server_id, port_id):
        server = self.fetch_server(server_id)
        if server:
            interfaces = server.interface_list()
            for iface in interfaces:
                if iface.port_id == port_id:
                    return False
        return True

    @retry(stop_max_attempt_number=cfg.CONF.max_interface_check_attempts,
           wait_fixed=500,
           retry_on_result=retry_if_result_is_false)
    def check_interface_attach(self, server_id, port_id):
        server = self.fetch_server(server_id)
        if server:
            interfaces = server.interface_list()
            for iface in interfaces:
                if iface.port_id == port_id:
                    return True
        return False

    def _list_extensions(self):
        extensions = self.client().list_extensions.show_all()
        return set(extension.alias for extension in extensions)

    def has_extension(self, alias):
        """Check if specific extension is present."""
        return alias in self._list_extensions()

