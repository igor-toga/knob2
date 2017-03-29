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
"""Implementation of SQLAlchemy backend."""
from oslo_config import cfg
from oslo_db import options
from oslo_db.sqlalchemy import enginefacade
from oslo_db.sqlalchemy import utils
from oslo_log import log as logging
from oslo_utils import encodeutils
from oslo_utils import timeutils
#import osprofiler.sqlalchemy
import six
import sqlalchemy

from knob.common import exception
from knob.common.i18n import _
from knob.db.sqlalchemy import migration
from knob.db.sqlalchemy import models

CONF = cfg.CONF
options.set_defaults(CONF)

_facade = None
db_context = enginefacade.transaction_context()

LOG = logging.getLogger(__name__)


# TODO(sbaker): fix tests so that sqlite_fk=True can be passed to configure
db_context.configure()


def get_facade():
    global _facade
    if _facade is None:

        # FIXME: get_facade() is called by the test suite startup,
        # but will not be called normally for API calls.
        # osprofiler / oslo_db / enginefacade currently don't have hooks
        # to talk to each other, however one needs to be added to oslo.db
        # to allow access to the Engine once constructed.
        db_context.configure(**CONF.database)
        _facade = db_context.get_legacy_facade()
        #_facade = db_session.EngineFacade(
        #        CONF.database.connection,
        #        **dict(CONF.database))
        #_facade = create_engine(CONF.database)
        # if CONF.profiler.enabled:
        #    if CONF.profiler.trace_sqlalchemy:
        #        osprofiler.sqlalchemy.add_tracing(sqlalchemy,
        #                                          _facade.get_engine(),
        #                                          "db")
    return _facade


def get_engine():
    return get_facade().get_engine()


def get_session():
    return get_facade().get_session()
    


def update_and_save(context, obj, values):
    with context.session.begin(subtransactions=True):
        for k, v in six.iteritems(values):
            setattr(obj, k, v)


def delete_softly(context, obj):
    """Mark this object as deleted."""
    update_and_save(context, obj, {'deleted_at': timeutils.utcnow()})


def soft_delete_aware_query(context, *args, **kwargs):
    """Stack query helper that accounts for context's `show_deleted` field.

    :param show_deleted: if True, overrides context's show_deleted field.
    """

    query = context.session.query(*args)
    show_deleted = kwargs.get('show_deleted') or context.show_deleted

    if not show_deleted:
        query = query.filter_by(deleted_at=None)
    return query


def gate_create(context, values):
    obj_ref = models.Gate()
    obj_ref.update(values)
    session = context.session

    with session.begin():
        obj_ref.save(session)

    return obj_ref


def gate_get(context, gate_id):
    result = context.session.query(
        models.Gate).get(gate_id)

    if not result:
        raise exception.NotFound(_('Gate with id %s not found') %
                                 gate_id)
    return result

def gate_get_by_name(context, name):
    return (context.session.query(models.Gate).
            filter_by(name=name).one_or_none())
    
def gate_get_all(context, tenant_id=None):
    query = context.session.query(models.Gate)
    if tenant_id:
        query = query.filter_by(tenant_id=tenant_id)
    return query.all()


def gate_update(context, deployment_id, values):
    deployment = gate_get(context, deployment_id)
    update_and_save(context, deployment, values)
    return deployment


def gate_delete(context, gate_id):
    gate = gate_get(context, gate_id)
    session = context.session
    with session.begin(subtransactions=True):
        session.delete(gate)


def target_get_all_by_args(context, gate_id, target_id):
    if target_id is not None:
        return (context.session.query(models.Target).
                filter_by(gate_id=gate_id).
                filter_by(target_id=target_id).all())
    else:
        return (context.session.query(models.Target).
                filter_by(gate_id=gate_id).all())


def target_create(context, values):
    obj_ref = models.Target()
    obj_ref.update(values)
    session = context.session

    with session.begin():
        obj_ref.save(session)

    return obj_ref


def target_get(context, target_id):
    result = context.session.query(
        models.Target).get(target_id)

    if not result:
        raise exception.NotFound(_('Target with id %s not found') %
                                 target_id)
    return result


def target_delete(context, deployment_id):
    deployment = target_get(context, deployment_id)
    session = context.session
    with session.begin(subtransactions=True):
        session.delete(deployment)


def key_create(context, values):
    obj_ref = models.Key()
    obj_ref.update(values)
    session = context.session

    with session.begin():
        obj_ref.save(session)

    return obj_ref


def key_get(context, key_id):
    result = context.session.query(
        models.Key).get(key_id)
    
    if not result:
        raise exception.NotFound(_('Key with id %s not found') %
                                 key_id)
    return result



def key_delete(context, gate_id):
    key = key_get(context, gate_id)
    session = context.session
    with session.begin(subtransactions=True):
        session.delete(key)


def key_get_all_by_args(context, gate_id, key_id):
    if key_id is not None:
        return (context.session.query(models.Key).
                filter_by(gate_id=gate_id).
                filter_by(target_id=key_id).all())
    else:
        return (context.session.query(models.Key).
                filter_by(gate_id=gate_id).all())


def service_create(context, values):
    service = models.Service()
    service.update(values)
    service.save(context.session)
    return service


def service_update(context, service_id, values):
    service = service_get(context, service_id)
    values.update({'updated_at': timeutils.utcnow()})
    service.update(values)
    service.save(context.session)
    return service


def service_delete(context, service_id, soft_delete=True):
    service = service_get(context, service_id)
    session = context.session
    with session.begin():
        if soft_delete:
            delete_softly(context, service)
        else:
            session.delete(service)


def service_get(context, service_id):
    result = context.session.query(models.Service).get(service_id)
    if result is None:
        raise exception.EntityNotFound(entity='Service', name=service_id)
    return result


def service_get_all(context):
    return (context.session.query(models.Service).
            filter_by(deleted_at=None).all())


def service_get_all_by_args(context, host, binary, topic):
    return (context.session.query(models.Service).
            filter_by(host=host).
            filter_by(binary=binary).
            filter_by(topic=topic).all())



def db_sync(engine, version=None):
    """Migrate the database to `version` or the most recent version."""
    if version is not None and int(version) < db_version(engine):
        raise exception.Error(_("Cannot migrate to lower schema version."))

    return migration.db_sync(engine, version=version)


def db_version(engine):
    """Display the current database version."""
    return migration.db_version(engine)


