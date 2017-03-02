# Copyright 2012, Red Hat, Inc.
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

"""
Client side of the scheduler manager RPC API.
"""

from oslo_config import cfg
from oslo_serialization import jsonutils

from knob import rpc


CONF = cfg.CONF


class ClientAPI(rpc.RPCAPI):
    """Client side of the rpc API.

    API version history:

        1.0 - Initial version.
    """

    RPC_API_VERSION = '1.0'

    def _compat_ver(self, current, legacy):
        if self.client.can_send_version(current):
            return current
        else:
            return legacy

    def create_consistencygroup(self, ctxt, topic, group,
                                request_spec_list=None,
                                filter_properties_list=None):
        version = self._compat_ver('1.0')
        cctxt = self.client.prepare(version=version)
        request_spec_p_list = []
        for request_spec in request_spec_list:
            request_spec_p = jsonutils.to_primitive(request_spec)
            request_spec_p_list.append(request_spec_p)

        return cctxt.cast(ctxt, 'create_consistencygroup',
                          topic=topic,
                          group=group,
                          request_spec_list=request_spec_p_list,
                          filter_properties_list=filter_properties_list)

    
    def update_service_capabilities(self, ctxt,
                                    service_name, host,
                                    capabilities):
        # FIXME(flaper87): What to do with fanout?
        version = self._compat_ver('1.0')
        cctxt = self.client.prepare(fanout=True, version=version)
        cctxt.cast(ctxt, 'update_service_capabilities',
                   service_name=service_name, host=host,
                   capabilities=capabilities)
