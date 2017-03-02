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
from knob.common import serializers
from knob.common import wsgi


class ServiceController(object):
    """WSGI controller for SSH gates in Knob v1 API.

    Implements the API actions.
    """

    REQUEST_SCOPE = 'services'

    def __init__(self, options):
        self.options = options
        #self.rpc_client = rpc_client.EngineClient()

    def default(self, req, **args):
        raise exc.HTTPNotFound()

    def index(self, req):
        """List SSH gates."""
        """
        whitelist = {
            'server_id': util.PARAM_TYPE_SINGLE,
        }
        params = util.get_allowed_params(req.params, whitelist)
        sds = self.rpc_client.list_software_deployments(req.context, **params)
        """
        sds = 1
        return {'software_deployments': sds}


def create_resource(options):
    """SSH services resource factory method."""
    deserializer = wsgi.JSONRequestDeserializer()
    serializer = serializers.JSONResponseSerializer()
    return wsgi.Resource(
        ServiceController(options), deserializer, serializer)
