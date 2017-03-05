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


def gate_get(context, deployment_id):
    result = context.session.query(
        models.Gate).get(deployment_id)
    if (result is not None and context is not None and
        context.tenant_id not in (result.tenant,
                                  result.stack_user_project_id)):
        result = None

    if not result:
        raise exception.NotFound(_('Deployment with id %s not found') %
                                 deployment_id)
    return result


def gate_get_all(context, server_id=None):
    sd = models.Gate
    query = context.session.query(
        sd
    ).filter(sqlalchemy.or_(
             sd.tenant == context.tenant_id,
             sd.stack_user_project_id == context.tenant_id)
             ).order_by(sd.created_at)
    if server_id:
        query = query.filter_by(server_id=server_id)
    return query.all()


def gate_update(context, deployment_id, values):
    deployment = gate_get(context, deployment_id)
    update_and_save(context, deployment, values)
    return deployment


def gate_delete(context, deployment_id):
    deployment = gate_get(context, deployment_id)
    session = context.session
    with session.begin(subtransactions=True):
        session.delete(deployment)


def target_create(context, values):
    obj_ref = models.Target()
    obj_ref.update(values)
    session = context.session

    with session.begin():
        obj_ref.save(session)

    return obj_ref


def target_get(context, deployment_id):
    result = context.session.query(
        models.Target).get(deployment_id)
    if (result is not None and context is not None and
        context.tenant_id not in (result.tenant,
                                  result.stack_user_project_id)):
        result = None

    if not result:
        raise exception.NotFound(_('Deployment with id %s not found') %
                                 deployment_id)
    return result


def target_get_all(context, server_id=None):
    sd = models.Target
    query = context.session.query(
        sd
    ).filter(sqlalchemy.or_(
             sd.tenant == context.tenant_id,
             sd.stack_user_project_id == context.tenant_id)
             ).order_by(sd.created_at)
    if server_id:
        query = query.filter_by(server_id=server_id)
    return query.all()


def target_update(context, deployment_id, values):
    deployment = target_get(context, deployment_id)
    update_and_save(context, deployment, values)
    return deployment


def target_delete(context, deployment_id):
    deployment = target_get(context, deployment_id)
    session = context.session
    with session.begin(subtransactions=True):
        session.delete(deployment)


def associate_create(context, values):
    obj_ref = models.Associate()
    obj_ref.update(values)
    session = context.session

    with session.begin():
        obj_ref.save(session)

    return obj_ref


def associate_get(context, deployment_id):
    result = context.session.query(
        models.Associate).get(deployment_id)
    if (result is not None and context is not None and
        context.tenant_id not in (result.tenant,
                                  result.stack_user_project_id)):
        result = None

    if not result:
        raise exception.NotFound(_('Deployment with id %s not found') %
                                 deployment_id)
    return result


def associate_get_all(context, server_id=None):
    sd = models.Associate
    query = context.session.query(
        sd
    ).filter(sqlalchemy.or_(
             sd.tenant == context.tenant_id,
             sd.stack_user_project_id == context.tenant_id)
             ).order_by(sd.created_at)
    if server_id:
        query = query.filter_by(server_id=server_id)
    return query.all()


def associate_update(context, deployment_id, values):
    deployment = associate_get(context, deployment_id)
    update_and_save(context, deployment, values)
    return deployment


def associate_delete(context, deployment_id):
    deployment = associate_get(context, deployment_id)
    session = context.session
    with session.begin(subtransactions=True):
        session.delete(deployment)



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


