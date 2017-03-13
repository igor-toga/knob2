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

#from knob.api.openstack.v1 import util
from knob.common import context
from knob.common import serializers
from knob.common import wsgi
from knob.common.exception import KnobException


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

        #self.context = context.get_admin_context()
        ctx = req.context        
        nets = ctx.neutron_client.list_networks()
        
        # replace key to the key client expects to see
        return {'gates': nets['networks']}

    def show(self, req, deployment_id):
        """Gets detailed information for a SSH gate."""
        #sd = self.rpc_client.show_software_deployment(req.context,
        #                                              deployment_id)
        sd = 1 
        return {'software_deployment': sd}

    def create(self, req, body):
        """Create a new SSH gate."""
        """
        create_data = dict((k, body.get(k)) for k in (
            'config_id', 'server_id', 'input_values',
            'action', 'status', 'status_reason', 'stack_user_project_id'))
 
        sd = self.rpc_client.create_software_deployment(req.context,
                                                        **create_data)
        """
        sd = 1
        return {'software_deployment': sd}

    def delete(self, req, deployment_id):
        """Delete an existing SSH gate."""
        #res = self.rpc_client.delete_software_deployment(req.context,
        #                                                 deployment_id)

        res = 1
        if res is not None:
            raise exc.HTTPBadRequest(res['Error'])

        raise exc.HTTPNoContent()


def create_resource(options):
    """SSH gates resource factory method."""
    deserializer = wsgi.JSONRequestDeserializer()
    serializer = serializers.JSONResponseSerializer()
    return wsgi.Resource(
        GateController(options), deserializer, serializer)
