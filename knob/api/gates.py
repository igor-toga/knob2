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
from knob.objects import gate as gate_obj
from knob.objects import target as target_obj
from knob.objects import key as key_obj

LOG = logging.getLogger(__name__)

class GateController(object):
    """WSGI controller for SSH gates in Knob v1 API.

    Implements the API actions.
    """

    REQUEST_SCOPE = 'gates'

    def __init__(self, options):
        self.options = options
        #self.rpc_client = rpc_client.EngineClient()

    def format_gate(self, gate):
        result = {
            'id': gate.id,
            'name': gate.name,
            'server_id': gate.server_id,
            'fip_id': gate.fip_id,
            'tenant_id': gate.tenant_id,
            'created_at': gate.created_at 
            }
        return result

    def format_target(self, target):
        result = {
            'name': target.name,
            'gate_id': target.gate_id,
            'server_id': target.server_id,
            'routable': target.routable,
            'created_at': target.created_at 
            }
        return result


    def index(self, req):
        """List SSH gates."""
        print ('--------index -------------------------------')

        ctx = req.context        
        gates = gate_obj.Gate.get_all(ctx)
        result = [self.format_gate(gate) for gate in gates]
        
        return {'gates': result}

    def show(self, req, gate_id):
        """Gets detailed information for a SSH gate."""
        print ('------------in show ---------------------- %s ' % gate_id)
        ctx = req.context
        gates = gate_obj.Gate.get_by_id(ctx, gate_id) 
        return {'gates': gates}

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
        #server_id = ctx.nova_client.create_service_vm(create_data)
        # create fip and to attach to given port
        
        #fip_id = ctx.neutron_client.associate_fip(port_id, create_data['public_net_id'])
        server_id = '74dcc644-527b-4f77-839f-70463126f0f1'
        fip_id = 'cad16a3c-2c70-4f76-ba0b-1f6ef31e7930'

        # DB update 
        gate_ref = gate_obj.Gate.create(
                ctx,dict(name=create_data['name'],
                             server_id=server_id,
                             fip_id=fip_id,
                             tenant_id=''))
        
        LOG.debug('Gate: %s is created successfully' % gate_ref.name)
        result = self.format_gate(gate_ref) 
        return {'gates': result}
    

    
    def delete(self, req, gate_id):
        """Delete an existing SSH gate."""
        
        print ('------------in delete ---------------------- %s ' % gate_id)
        ctx = req.context
        # lookup correct gate by id
        gate_ref = gate_obj.Gate.get_by_id(ctx, gate_id)
        server_id = gate_ref['server_id']
        fip_id = gate_ref['fip_id']
        gate_id = gate_ref['id']
        #ctx.neutron_client.disassociate_fip(fip_id)
        #ctx.nova_client.remove_service_vm(server_id)
        
        gate_obj.Gate.delete(ctx,gate_id)
        
    def add_target(self, req, gate_id, body):
        """Add target to gate."""
        data = dict((k, body.get(k)) for k in (
            'server_id', 'gate_id', 'name','routable'))
        print ('------------in add_target: %s to gate %s ' % (data['name'], gate_id))
        ctx = req.context
        # verify if target VM exists
        try:
            ctx.nova_client.get_server(data['server_id'])
        except exc.EntityNotFound:
            return {'targets': None}
        
        # verify if gate exists
        gate_ref = gate_obj.Gate.get_by_id(ctx, gate_id)
        if gate_ref is not None:
            # DB update 
            target_ref = target_obj.Target.create(
                ctx,dict(server_id=data['server_id'],
                         gate_id=data['gate_id'],
                         name=data['name'],
                         routable=data['routable']))
            
            LOG.debug('Target: %s is created successfully' % target_ref.name)
            result = self.format_target(target_ref) 
            return {'targets': result}
        else:
            return {'targets': None}
        
    def remove_target(self, req, gate_id, target_id):
        """Remove target to gate."""
        print ('------------in remove_target: %s to gate %s ' % (target_id, gate_id))
        ctx = req.context
        # verify if target VM exists
        try:
            ctx.nova_client.get_server(target_id)
        except exc.EntityNotFound:
            return {'targets': None}
        
        #verify if gate_id exists
        target_ref = target_obj.Target.get_all_by_args(ctx, gate_id, target_id)
        if target_ref is not None:
            target_obj.Target.delete(ctx,target_id)
        
    def list_targets(self, req, gate_id):
        """List targets on gate."""
        print ('--------list targets on gate: %s' % gate_id)

        ctx = req.context        
        targets = target_obj.Target.get_all_by_args(ctx, gate_id)
        result = [self.format_target(target) for target in targets]
        return {'targets': result}
    
    def add_key(self, req, gate_id, body):
        """Add key to gate."""
        data = dict((k, body.get(k)) for k in (
            'name', 'key_content'))
        
        print ('------------in add_key: %s to gate %s ' % 
               (data['name'], gate_id))
        ctx = req.context
        # DB update 
        key_ref = key_obj.Key.create(
            ctx,dict(name=data['name'],
                     key_content=data['key_content'],
                     gate=gate_id))
        
        LOG.debug('Key record: %s is created successfully' % key_ref.name)
        result = self.format_target(key_ref) 
        return {'keys': result}
        
    def remove_key(self, req, gate_id, key):
        """Remove key to gate."""
        print ('------------in remove_key: %s to gate %s ' % (key, gate_id))
        ctx = req.context
        
        key_ref = key_obj.Key.get_by_name(ctx, key)
        key_id = key_ref['id']
        key_obj.Key.delete(ctx,key_id)
        
    def list_keys(self, req):
        """List keys on gate."""
        print ('--------list keys -------------------------------')

        ctx = req.context        
        keys = key_obj.Key.get_all(ctx)
        result = [self.format_key(key) for key in keys]
        return {'keys': result}

        
def create_resource(options):
    """SSH gates resource factory method."""
    deserializer = wsgi.JSONRequestDeserializer()
    serializer = serializers.JSONResponseSerializer()
    return wsgi.Resource(
        GateController(options), deserializer, serializer)
