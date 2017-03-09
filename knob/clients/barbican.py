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
from barbicanclient import client as barbican_client
from barbicanclient import containers
from barbicanclient import exceptions

from knob.common import exception


class BarbicanClient(object):

    def __init__(self, sess):
        self._client = barbican_client.Client('1.0', session=sess)

    def client(self):
        if self._client is None:
            raise exception.NotFound("object not found")
        return self._client
        
    def is_not_found(self, ex):
        return (isinstance(ex, exceptions.HTTPClientError) and
                ex.status_code == 404)

    def create_generic_container(self, **props):
        return containers.Container(
            self.client().containers._api, **props)

    def create_certificate(self, **props):
        return containers.CertificateContainer(
            self.client.containers._api, **props)

    def create_rsa(self, **props):
        return containers.RSAContainer(
            self.client().containers._api, **props)

    def get_secret_by_ref(self, secret_ref):
        try:
            secret = self.client().secrets.get(secret_ref)
            # Force lazy loading. TODO(therve): replace with to_dict()
            secret.name
            return secret
        except Exception as ex:
            if self.is_not_found(ex):
                raise exception.EntityNotFound(
                    entity="Secret",
                    name=secret_ref)
            raise

    def get_container_by_ref(self, container_ref):
        try:
            # TODO(therve): replace with to_dict()
            return self.client().containers.get(container_ref)
        except Exception as ex:
            if self.is_not_found(ex):
                raise exception.EntityNotFound(
                    entity="Container",
                    name=container_ref)
            raise


