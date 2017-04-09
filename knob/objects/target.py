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


"""Target object."""

from oslo_versionedobjects import base
from oslo_versionedobjects import fields

from knob.db.sqlalchemy import api as db_api
from knob.objects import base as knob_base


class Target(
        knob_base.KnobObject,
        base.VersionedObjectDictCompat,
        base.ComparableVersionedObject,
):
    fields = {
        'server_id': fields.StringField(),
        'name': fields.StringField(nullable=True),
        'gate_id': fields.IntegerField(nullable=True),
        'routable': fields.BooleanField(),
        'created_at': fields.DateTimeField(read_only=True),
        'updated_at': fields.DateTimeField(nullable=True),
    }

    @staticmethod
    def _from_db_object(context, target, db_target):
        for field in target.fields:
            target[field] = db_target[field]
        target._context = context
        target.obj_reset_changes()
        return target

    @classmethod
    def create(cls, context, values):
        return cls._from_db_object(
            context, cls(), db_api.target_create(context, values))

    @classmethod
    def get_by_id(cls, context, target_id):
        return cls._from_db_object(
            context, cls(),
            db_api.target_get(context, target_id))
        
    @classmethod
    def delete(cls, context, target_id):
        db_api.target_delete(context, target_id)

    @classmethod
    def get_all_by_args(cls, context, gate_id, target_id=None):
        return [cls._from_db_object(context, cls(), db_target)
                for db_target in db_api.target_get_all_by_args(
                    context, gate_id, target_id)]
