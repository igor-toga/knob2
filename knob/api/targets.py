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

from webob import exc
from oslo_log import log as logging
#from knob.api.openstack.v1 import util
from knob.common import serializers
from knob.common import wsgi
from knob.common import exception
from knob.objects import gate as gate_obj
from knob.objects import target as target_obj

from knob.common.i18n import _LW

LOG = logging.getLogger(__name__)


class TargetController(object):
    """WSGI controller for SSH targets in Knob v1 API.

    Implements the API actions.
    """

    REQUEST_SCOPE = 'targets'

    def __init__(self, options):
        self.options = options
    
    
    def format_config(self, data):
        config = """
Host %s
  HostName %s
  User %s
  ForwardAgent yes
  IdentityFile %s
  StrictHostKeyChecking no
  UserKnownHostsFile=/dev/null
  ProxyCommand ssh -i %s -o StrictHostKeyChecking=no cirros@%s nc %%h %%p
  """ % (
            data['target_name'],
            data['target_ip'],
            data['user'],
            data['target_key_file'],
            data['gate_key_file'],
            data['gate_ip'],
            
            )
        return config
    
    def generate_config(self, req, body):
        """generate config for given target and gate"""
        
        data = dict((k, body.get(k)) for k in (
            'gate_id', 'gate_key_file', 'user',
            'target_id', 'target_key_file'))
 
        ctx = req.context
        try:
            target_ip = ctx.nova_client.get_ip(data['target_id'], 'private', 4, 'fixed')
            target_ref = target_obj.Target.get_by_id(ctx, data['target_id'])
        
            gate_ref = gate_obj.Gate.get_by_id(ctx, data['gate_id'])
            server_id = gate_ref['server_id']
            gate_ip = ctx.nova_client.get_ip(server_id, 'private', 4, 'floating')
            # complete data collection with info from objects
            data['target_ip'] = target_ip
            data['target_name'] = target_ref['name']
            data['gate_ip'] = gate_ip
            data['gate_name'] = gate_ref['name']
        except exception.EntityNotFound as exc:
            LOG.warning(_LW("Target %(name)s not found "),
                        {'name': exc.name})
            return None
        
        config = self.format_config(data)
        
        return {'config': config}

    

def create_resource(options):
    """SSH targets resource factory method."""
    deserializer = wsgi.JSONRequestDeserializer()
    serializer = serializers.JSONResponseSerializer()
    return wsgi.Resource(
        TargetController(options), deserializer, serializer)
