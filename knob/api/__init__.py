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


import routes
import six

from knob.api import gates
from knob.api import targets
from knob.api import associates
from knob.api import services
from knob.common import wsgi


from debtcollector import removals
from knob.api.middleware import fault
from knob.api.middleware import ssl
from knob.api.middleware import version_negotiation as vn
from knob.api import versions
from knob.common.exception import KnobException


def version_negotiation_filter(app, conf, **local_conf):
    return vn.VersionNegotiationFilter(versions.Controller, app,
                                       conf, **local_conf)


def faultwrap_filter(app, conf, **local_conf):
    return fault.FaultWrapper(app)


@removals.remove(message='Use oslo_middleware.http_proxy_to_wsgi instead.',
                 version='6.0.0', removal_version='8.0.0')
def sslmiddleware_filter(app, conf, **local_conf):
    return ssl.SSLMiddleware(app)


class API(wsgi.Router):

    """WSGI router for knob v1 REST API requests."""

    def __init__(self, conf, **local_conf):
        self.conf = conf
        mapper = routes.Mapper()
        default_resource = wsgi.Resource(wsgi.DefaultMethodController(),
                                         wsgi.JSONRequestDeserializer())

        def connect(controller, path_prefix, routes):
            """Connects list of routes to given controller with path_prefix.
            This function connects the list of routes to the given
            controller, prepending the given path_prefix. Then for each URL it
            finds which request methods aren't handled and configures those
            to return a 405 error. Finally, it adds a handler for the
            OPTIONS method to all URLs that returns the list of allowed
            methods with 204 status code.
            """
            # register the routes with the mapper, while keeping track of which
            # methods are defined for each URL
            urls = {}
            for r in routes:
                url = path_prefix + r['url']
                methods = r['method']
                if isinstance(methods, six.string_types):
                    methods = [methods]
                methods_str = ','.join(methods)
                mapper.connect(r['name'], url, controller=controller,
                               action=r['action'],
                               conditions={'method': methods_str})
                if url not in urls:
                    urls[url] = methods
                else:
                    urls[url] += methods

            # now register the missing methods to return 405s, and register
            # a handler for OPTIONS that returns the list of allowed methods
            for url, methods in urls.items():
                all_methods = ['HEAD', 'GET', 'POST', 'PUT', 'PATCH', 'DELETE']
                missing_methods = [m for m in all_methods if m not in methods]
                allowed_methods_str = ','.join(methods)
                mapper.connect(url,
                               controller=default_resource,
                               action='reject',
                               allowed_methods=allowed_methods_str,
                               conditions={'method': missing_methods})
                if 'OPTIONS' not in methods:
                    mapper.connect(url,
                                   controller=default_resource,
                                   action='options',
                                   allowed_methods=allowed_methods_str,
                                   conditions={'method': 'OPTIONS'})

        

        # Gates
        gate_resource = gates.create_resource(conf)
        connect(controller=gate_resource,
                path_prefix='/gates',
                routes=[
                    {
                        'name': 'gate_index',
                        'url': '',
                        'action': 'index',
                        'method': 'GET'
                    },
                    {
                        'name': 'gate_create',
                        'url': '',
                        'action': 'create',
                        'method': 'POST'
                    },
                    {
                        'name': 'gate_show',
                        'url': '/{gate_id}',
                        'action': 'show',
                        'method': 'GET'
                    },
                    {
                        'name': 'gate_delete',
                        'url': '/{gate_id}',
                        'action': 'delete',
                        'method': 'DELETE'
                    }
                ])

        # Targets
        target_resource = targets.create_resource(conf)
        connect(controller=target_resource,
                path_prefix='/targets',
                routes=[
                    {
                        'name': 'target_index',
                        'url': '',
                        'action': 'index',
                        'method': 'GET'
                    },
                    {
                        'name': 'target_create',
                        'url': '',
                        'action': 'create',
                        'method': 'POST'
                    },
                    {
                        'name': 'target_show',
                        'url': '/{target_id}',
                        'action': 'show',
                        'method': 'GET'
                    },
                    {
                        'name': 'target_delete',
                        'url': '/{target_id}',
                        'action': 'delete',
                        'method': 'DELETE'
                    }
                ])
        
        # Associates
        associate_resource = associates.create_resource(conf)
        connect(controller=associate_resource,
                path_prefix='/associates',
                routes=[
                    {
                        'name': 'associate_index',
                        'url': '',
                        'action': 'index',
                        'method': 'GET'
                    },
                    {
                        'name': 'associate_create',
                        'url': '',
                        'action': 'create',
                        'method': 'POST'
                    },
                    {
                        'name': 'associate_show',
                        'url': '/{associate_id}',
                        'action': 'show',
                        'method': 'GET'
                    },
                    {
                        'name': 'associate_delete',
                        'url': '/{associate_id}',
                        'action': 'delete',
                        'method': 'DELETE'
                    }
                ])
        
        # Services
        service_resource = services.create_resource(conf)
        with mapper.submapper(
            controller=service_resource,
            path_prefix='/services'
        ) as sa_mapper:

            sa_mapper.connect("service_index",
                              "",
                              action="index",
                              conditions={'method': 'GET'})

        # now that all the routes are defined, add a handler for
        super(API, self).__init__(mapper)
