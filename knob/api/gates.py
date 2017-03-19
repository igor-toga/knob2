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
from oslo_log import log as logging
from webob import exc

from knob.common import serializers
from knob.common import wsgi
from knob.common.exception import KnobException
from knob.objects import gate as obj

LOG = logging.getLogger(__name__)

class GateController(object):
    """WSGI controller for SSH gates in Knob v1 API.

    Implements the API actions.
    """

    REQUEST_SCOPE = 'gates'

    def __init__(self, options):
        self.options = options
        #self.rpc_client = rpc_client.EngineClient()


    def index(self, req):
        """List SSH gates."""
        """
        whitelist = {
            'server_id': util.PARAM_TYPE_SINGLE,
        }
        params = util.get_allowed_params(req.params, whitelist)
        sds = self.rpc_client.list_software_deployments(req.context, **params)
        """
        print ('gate list method get called')
        # TODO howto pass internalURL

        #myctx #= context.get_admin_context()
        ctx = req.context        
        nets = ctx.neutron_client.list_networks()
        
        # replace key to the key client expects to see
        return {'gates': nets['networks']}

    def show(self, req, gate_id):
        """Gets detailed information for a SSH gate."""
        #sd = self.rpc_client.show_software_deployment(req.context,
        #   
        print ('------------in show ---------------------- %s ' % gate_id)
        sd = 1 
        return {'software_deployment': sd}

    #def create(self, req, body):
    def create(self, req, body):
        """Create a new SSH gate."""
        
        print ('------------in create ---------------------- ')
        create_data = dict((k, body.get(k)) for k in (
            'name', 'net_id', 'public_net_id','key'))
        create_data['flavor'] = 'm1.tiny'
        create_data['image'] = 'cirros-0.3.5-x86_64-disk'
        create_data['security_groups'] = 'default'
        
        ctx = req.context
        
        if 'public_net_id' not in create_data:
            raise exc.HTTPBadRequest('Not supplied required parameter')
 
        """
         create neutron port first
         create service VM with provided parameters and given port
         create floating ip
         attach VM port to floating ip
        """
        port_id = 'e89f6467-00b7-42a3-8b03-8107bd5f428c'
        #port_id = ctx.neutron_client.create_port(create_data)
        
        create_data['port-id'] = port_id
        # update network configuration with given port id
        #vm_id = ctx.nova_client.create_service_vm(create_data)
        # create fip and to attach to given port
        
        #fip_id = ctx.neutron_client.associate_fip(port_id, create_data['public_net_id'])
        vm_id = '74dcc644-527b-4f77-839f-70463126f0f1'
        fip_id = 'cad16a3c-2c70-4f76-ba0b-1f6ef31e7930'

        # DB update 
        gate_ref = obj.Gate.create(
                ctx,dict(name=create_data['name'],
                             server_id=vm_id,
                             fip_id=fip_id,
                             tenant_id=''))
        
        gate_id = gate_ref['id']
        LOG.debug('Gate %s is create successfully' % gate_id)
        return gate_id

    
    def delete(self, req, gate_id):
        """Delete an existing SSH gate."""
        
        print ('------------in delete ---------------------- %s ' % gate_id)
        ctx = req.context
        # lookup correct gate by id
        gate_ref = obj.Gate.get_by_id(ctx, gate_id)
        vm_id = gate_ref['vm_id']
        fip_id = gate_ref['fip_id']
        ctx.neutron_client.disassociate_fip(fip_id)
        ctx.nova_client.remove_service_vm(vm_id)
        
        obj.Gate.delete(ctx,gate_id)
        
        res = None
        if res is not None:
            raise exc.HTTPBadRequest(res['Error'])

        raise exc.HTTPNoContent()


def create_resource(options):
    """SSH gates resource factory method."""
    deserializer = wsgi.JSONRequestDeserializer()
    serializer = serializers.JSONResponseSerializer()
    return wsgi.Resource(
        GateController(options), deserializer, serializer)
