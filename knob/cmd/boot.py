#!/usr/bin/env python
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

"""Knob API Server.

An OpenStack ReST API to Knob.
"""

import eventlet
eventlet.monkey_patch(os=False)

import sys

from oslo_config import cfg
import oslo_i18n as i18n
from oslo_log import log as logging
from oslo_reports import guru_meditation_report as gmr
from oslo_service import systemd
import six

from knob.common import config
from knob.common.i18n import _LI
#from knob.common import messaging
#from knob.common import profiler
from knob.common import wsgi
from knob.common import version
from knob.common import context
from knob.common import exception
from knob.objects import service as objects


i18n.enable_lazy()

LOG = logging.getLogger('knob.api')
CONF = cfg.CONF

def do_create_service_ref(context, host, binary, topic, 
                          rpc_version=None, obj_version = None):
    service_ref = objects.Service.create(
                context,
                dict(host=host,
                     topic=topic,
                     binary=binary)
            )
    service_id = service_ref['id']
    LOG.debug('Service %s is started' % service_id)

def create_service_ref(host, binary, topic):
    ctxt = context.get_admin_context()
    service_ref = objects.Service.get_all_by_args(ctxt, 
                                        host=host,
                                        binary=binary,
                                        topic=topic)
        
    if not service_ref:
        do_create_service_ref(ctxt, host, binary, topic)
            
def launch_api(setup_logging=True):
    if setup_logging:
        logging.register_options(cfg.CONF)
    cfg.CONF(project='knob', prog='knob-api',
             version=version.version_info.version_string())
    if setup_logging:
        logging.setup(cfg.CONF, 'knob-api')
    config.set_config_defaults()
    #messaging.setup()
    create_service_ref(binary='knob-api', host=CONF.host,
                       topic='knob-api')
    app = config.load_paste_app()

    port = cfg.CONF.knob_api.bind_port
    host = cfg.CONF.knob_api.bind_host
    LOG.info(_LI('Starting Knob REST API on %(host)s:%(port)s'),
             {'host': host, 'port': port})
    #profiler.setup('knob-api', host)
    gmr.TextGuruMeditation.setup_autorun(version)
    server = wsgi.Server('knob-api', cfg.CONF.knob_api)
    server.start(app, default_port=port)
    return server


def main():
    try:
        server = launch_api()
        systemd.notify_once()
        server.wait()
    except RuntimeError as e:
        msg = six.text_type(e)
        sys.exit("ERROR: %s" % msg)
