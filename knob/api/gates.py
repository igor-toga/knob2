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
import uuid

from oslo_config import cfg
from oslo_log import log as logging
from webob import exc

from knob.api import deploy_key as engine
from knob.common import exception
from knob.common import serializers
from knob.common import wsgi
from knob.objects import gate as gate_obj
from knob.objects import target as target_obj
from knob.objects import key as key_obj

LOG = logging.getLogger(__name__)
MGMT_KEY_PREFIX = 'mgmt-key-'
KEY_STORE_PATH = '/etc/knob/keys/'

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
            'port_id': gate.port_id,
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

    def format_key(self, key):
        result = {
            'id': key.id,
            'name': key.name,
            'gate_id': key.gate_id,
            'created_at': key.created_at 
            }
        return result


    def index(self, req):
        """List SSH gates."""
        LOG.info ('List all gates')

        ctx = req.context        
        gates = gate_obj.Gate.get_all(ctx)
        result = [self.format_gate(gate) for gate in gates]
        
        return {'gates': result}

    def show(self, req, gate_id):
        """Gets detailed information for a SSH gate."""
        LOG.info ('Show information about gate: %s ' % gate_id)
        ctx = req.context
        gates = gate_obj.Gate.get_by_id(ctx, gate_id) 
        return {'gates': gates}

    def _create_keypair(self, ctx, name):
        # create new key
        key_name = MGMT_KEY_PREFIX + name
        # create key and store at nova DB
        key = ctx.nova_client.keypair_create(key_name)
        return key
        
    def _store_keypair(self, ctx, gate_id, key):
        # store private key for further usage
        stream = open(KEY_STORE_PATH+key['name'], 'w')
        stream.write(key['private_key'])
        stream.close()
        
        # DB update: store mgmt key along with gate
        key_obj.Key.create(
            ctx,dict(name=key['name'],
                     content=key['public_key'],
                     gate_id=gate_id))
        
    def _delete_keypair(self, ctx, name):
        key_name = MGMT_KEY_PREFIX + name
        # remove nova key
        ctx.nova_client.keypair_delete(key_name)
        
        # remove private key file
        key_path = KEY_STORE_PATH+key_name
        os.remove(key_path)
        
        # remove knob key reference
        key_obj.Key.delete_by_name(ctx, key_name)
        
        

    def create(self, req, body):
        """Create a new SSH gate."""        
        LOG.info ('Creating new gate ')
        create_data = dict((k, body.get(k)) for k in (
            'name', 'net_id', 'public_net_id', 'flavor', 'image', 'security_groups'))
        
        ctx = req.context
        
        project_id = ctx.keystone_client.projects.list(name=ctx.tenant_name)[0].id
        LOG.debug('Identify project id: %s from name' % project_id)
        
        if 'public_net_id' not in create_data:
            raise exc.HTTPBadRequest('Not supplied required parameter')
        
        if create_data['image'] is None:
            create_data['image'] = cfg.CONF.gate.image

        if create_data['flavor'] is None:
            create_data['flavor'] = cfg.CONF.gate.flavor
   
        if create_data['security_groups'] is None:
            create_data['security_groups'] = cfg.CONF.gate.security_groups
        
        # add controller host as 'allowed' to security group once
        ctx.neutron_client.update_security_groups(project_id, 
                                                  create_data['security_groups'],
                                                  create_data['public_net_id'])
        # create key
        key_class = self._create_keypair(ctx, create_data['name'])
        key = key_class.to_dict()
        create_data['key_name'] = key['name']
        LOG.info('Created management key for upcoming service gate')
                
        # create port
        port_id = ctx.neutron_client.create_port(create_data)
        create_data['port-id'] = port_id
        LOG.info('Created neutron port to deploy gate on it')
        
        # update network configuration with given port id
        server_id = ctx.nova_client.create_service_vm(create_data)
        if server_id is None:
           LOG.info('Gate: %s is not running need to clear resources')
           return {'gates': None}
        else:
           LOG.info('Service gate is up and running')

        # create fip and to attach to given port
        fip_id = ctx.neutron_client.associate_fip(port_id, create_data['public_net_id'])
        LOG.info('Attached floating IP to make service gate accessible from outside')

        # DB update: crete new gate 
        gate_ref = gate_obj.Gate.create(
                ctx,dict(name=create_data['name'],
                             server_id=server_id,
                             fip_id=fip_id,
                             port_id=port_id,
                             tenant_id=project_id))
        LOG.info('Update service database')
        
        # store keypair for further use
        self._store_keypair(ctx, gate_ref['id'], key)
        LOG.info('Store private key locally')
        
        result = self.format_gate(gate_ref)
        LOG.info('Gate: %s is created successfully' % gate_ref.name)
        return {'gates': result}
    
    def delete(self, req, gate_id):
        """Delete an existing SSH gate."""
        
        LOG.info ('Deleting gate: %s ' % gate_id)
        ctx = req.context
        # lookup correct gate by id
        gate_ref = gate_obj.Gate.get_by_id(ctx, gate_id)
        server_id = gate_ref['server_id']
        fip_id = gate_ref['fip_id']
        port_id = gate_ref['port_id']
        # remove server
        LOG.info ('Removing service VM with ID: %s ' % server_id)
        ctx.nova_client.remove_service_vm(server_id)
        
        # disassociate fip & delete port
        LOG.info ('Disassociate floating ip: %s ' % fip_id)
        ctx.neutron_client.disassociate_fip(fip_id)
        
        # remove neutron port explicitly
        LOG.info ('Deleting knob service port: %s ' % port_id)
        ctx.neutron_client.delete_port(port_id)

        #remove mgmt key pair
        LOG.info ('Deleting mgmt. public key from Nova: %s ' % gate_ref['name'])
        self._delete_keypair(ctx,  gate_ref['name'])
        
        # remove gate object from DB
        LOG.info ('Delete gate entry from service database')
        gate_obj.Gate.delete(ctx, gate_id)
        LOG.info('Gate: %s is created successfully' % gate_id)
        
    def add_target(self, req, gate_id, body):
        """Add target to gate."""
        data = dict((k, body.get(k)) for k in (
            'server_id', 'gate_id', 'name','routable'))
        LOG.info ('Add target: %s to gate %s ' % (data['name'], gate_id))
        ctx = req.context
        # verify if target VM exists
        try:
            ctx.nova_client.get_server(data['server_id'])
        except exception.EntityNotFound:
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
        LOG.info ('Remove target: %s from gate %s ' % (target_id, gate_id))
        ctx = req.context
        # verify if target VM exists
        try:
            ctx.nova_client.get_server(target_id)
        except exception.EntityNotFound:
            return {'targets': None}
        
        #verify if gate_id exists
        target_ref = target_obj.Target.get_all_by_args(ctx, gate_id, target_id)
        if target_ref is not None:
            target_obj.Target.delete(ctx,target_id)
        
    def list_targets(self, req, gate_id):
        """List targets on gate."""
        LOG.info ('List targets on gate: %s' % gate_id)

        ctx = req.context
        targets = target_obj.Target.get_all_by_args(ctx, gate_id)
        result = [self.format_target(target) for target in targets]
        return {'targets': result}
    
    def add_key(self, req, gate_id, body):
        """Add key to gate."""
        data = dict((k, body.get(k)) for k in (
            'name', 'key_content'))
        
        LOG.info ('Add key: %s to gate %s ' % 
               (data['name'], gate_id))
        ctx = req.context
        # DB update 
        key_ref = key_obj.Key.create(
            ctx,dict(name=data['name'],
                     content=data['key_content'],
                     gate_id=gate_id))
        
        gate_ref = gate_obj.Gate.get_by_id(ctx, gate_id)
        server_id = gate_ref['server_id']
        server_ip = ctx.nova_client.get_ip(server_id, 'private', 4,'floating')
        
        key_name = KEY_STORE_PATH + MGMT_KEY_PREFIX + gate_ref['name']
        config = {
            'private_key_file': key_name,
            'username': cfg.CONF.gate.user,
            'append': True,
            'host': server_ip,
            'key': data['key_content']
            }
        engine.deploy_key(config)
        

        LOG.debug('Key record: %s is created successfully' % key_ref.name)
        result = self.format_key(key_ref) 
        return {'keys': result}
        
    def remove_key(self, req, gate_id, key_id):
        """Remove key from gate."""
        LOG.info ('Remove key: %s from gate %s ' % (key_id, gate_id))
        ctx = req.context
        
        #verify if gate_id exists
        key_ref = key_obj.Key.get_all_by_args(ctx, gate_id, key_id)
        if key_ref is not None:
            key_obj.Key.delete(ctx,key_id)
            
            gate_ref = gate_obj.Gate.get_by_id(ctx, gate_id)
            server_id = gate_ref['server_id']
            server_ip = ctx.nova_client.get_ip(server_id, 'private', 4,'floating')
            
            key_name = KEY_STORE_PATH + MGMT_KEY_PREFIX + gate_ref['name']
            config = {
                'private_key_file': key_name,
                'username': cfg.CONF.gate.user,
                'append': False,
                'host': server_ip,
                'key': key_ref['content']
                }
            engine.deploy_key(config)
        
    def list_keys(self, req, gate_id):
        """List keys on gate."""
        LOG.info ('List keys on gate: %s' % gate_id)

        ctx = req.context
        keys = key_obj.Key.get_all_by_args(ctx, gate_id)
        result = [self.format_key(key) for key in keys]
        return {'keys': result}

        
def create_resource(options):
    """SSH gates resource factory method."""
    deserializer = wsgi.JSONRequestDeserializer()
    serializer = serializers.JSONResponseSerializer()
    return wsgi.Resource(
        GateController(options), deserializer, serializer)
