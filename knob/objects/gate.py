# Copyright 2014 Intel Corp.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.


"""Gate object."""

from oslo_versionedobjects import base
from oslo_versionedobjects import fields

from knob.db.sqlalchemy import api as db_api
from knob.objects import base as knob_base


class Gate(
        knob_base.KnobObject,
        base.VersionedObjectDictCompat,
        base.ComparableVersionedObject,
):
    fields = {
        'id': fields.StringField(),
        'name': fields.StringField(),
        'fip_id': fields.StringField(),
        'server_id': fields.StringField(),
        'tenant_id': fields.StringField(),
        'created_at': fields.DateTimeField(read_only=True),
        'updated_at': fields.DateTimeField(nullable=True),
        'deleted_at': fields.DateTimeField(nullable=True),
    }

    @staticmethod
    def _from_db_object(context, deployment, db_deployment):
        for field in deployment.fields:
            deployment[field] = db_deployment[field]
        deployment._context = context
        deployment.obj_reset_changes()
        return deployment

    @classmethod
    def create(cls, context, values):
        return cls._from_db_object(
            context, cls(), db_api.gate_create(context, values))

    @classmethod
    def get_by_id(cls, context, gate_id):
        return cls._from_db_object(
            context, cls(),
            db_api.gate_get(context, gate_id))
        
    @classmethod
    def get_by_name(cls, context, gate_name):
        return cls._from_db_object(
            context, cls(),
            db_api.gate_get_by_name(context, gate_name))

    @classmethod
    def get_all(cls, context, server_id=None):
        return [cls._from_db_object(context, cls(), db_deployment)
                for db_deployment in db_api.gate_get_all(
                    context, server_id)]

    @classmethod
    def update_by_id(cls, context, gate_id, values):
        """Note this is a bit unusual as it returns the object.

        Other update_by_id methods return a bool (was it updated).
        """
        return cls._from_db_object(
            context, cls(),
            db_api.gate_update(context, gate_id, values))

    @classmethod
    def delete(cls, context, gate_id):
        db_api.gate_delete(context, gate_id)
