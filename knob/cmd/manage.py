#
# All Rights Reserved.
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

"""CLI interface for knob management."""

import sys

from oslo_config import cfg
from oslo_log import log

from knob.common import config
from knob.common import context
from knob.common.i18n import _
#from knob.common import messaging
from knob.common import service_utils
from knob.db.sqlalchemy import api as db_api
from knob.objects import service as service_objects
#from knob.rpc import client as rpc_client
from knob.common import version


CONF = cfg.CONF


def do_db_version():
    """Print database's current migration level."""
    print(db_api.db_version(db_api.get_engine()))


def do_db_sync():
    """Place a database under migration control and upgrade.

    Creating first if necessary.
    """
    db_api.db_sync(db_api.get_engine(), CONF.command.version)


class ServiceManageCommand(object):
    def service_list(self):
        ctxt = context.get_admin_context()
        services = [service_utils.format_service(service)
                    for service in service_objects.Service.get_all(ctxt)]

        print_format = "%-16s %-16s %-36s %-10s %-10s %-10s %-10s"
        print(print_format % (_('Hostname'),
                              _('Binary'),
                              _('Engine_Id'),
                              _('Host'),
                              _('Topic'),
                              _('Status'),
                              _('Updated At')))

        for svc in services:
            print(print_format % (svc['hostname'],
                                  svc['binary'],
                                  svc['engine_id'],
                                  svc['host'],
                                  svc['topic'],
                                  svc['status'],
                                  svc['updated_at']))

    def service_clean(self):
        ctxt = context.get_admin_context()
        for service in service_objects.Service.get_all(ctxt):
            svc = service_utils.format_service(service)
            if svc['status'] == 'down':
                service_objects.Service.delete(ctxt, svc['id'])
        print(_('Dead engines are removed.'))

    @staticmethod
    def add_service_parsers(subparsers):
        service_parser = subparsers.add_parser('service')
        service_parser.set_defaults(command_object=ServiceManageCommand)
        service_subparsers = service_parser.add_subparsers(dest='action')
        list_parser = service_subparsers.add_parser('list')
        list_parser.set_defaults(func=ServiceManageCommand().service_list)
        remove_parser = service_subparsers.add_parser('clean')
        remove_parser.set_defaults(func=ServiceManageCommand().service_clean)


def do_migrate():
    """
    messaging.setup()
    client = rpc_client.EngineClient()
    ctxt = context.get_admin_context()
    try:
        client.migrate_convergence_1(ctxt, CONF.command.stack_id)
    except exception.NotFound:
        raise Exception(_("Stack with id %s can not be found.")
                        % CONF.command.stack_id)
    except exception.ActionInProgress:
        raise Exception(_("The stack or some of its nested stacks are "
                          "in progress. Note, that all the stacks should be "
                          "in COMPLETE state in order to be migrated."))
    """


def add_command_parsers(subparsers):
    # db_version parser
    parser = subparsers.add_parser('db_version')
    parser.set_defaults(func=do_db_version)

    # db_sync parser
    parser = subparsers.add_parser('db_sync')
    parser.set_defaults(func=do_db_sync)
    # positional parameter, can be skipped. default=None
    parser.add_argument('version', nargs='?')

    ServiceManageCommand.add_service_parsers(subparsers)

command_opt = cfg.SubCommandOpt('command',
                                title='Commands',
                                help=_('Show available commands.'),
                                handler=add_command_parsers)


def main():
    log.register_options(CONF)
    log.setup(CONF, "knob-manage")
    CONF.register_cli_opt(command_opt)
    try:
        default_config_files = cfg.find_config_files('knob', 'knob-manage')
        CONF(sys.argv[1:], project='knob', prog='knob-manage',
             version=version.version_info.version_string(),
             default_config_files=default_config_files)
        config.set_config_defaults()
    except RuntimeError as e:
        sys.exit("ERROR: %s" % e)

    try:
        CONF.command.func()
    except Exception as e:
        sys.exit("ERROR: %s" % e)
