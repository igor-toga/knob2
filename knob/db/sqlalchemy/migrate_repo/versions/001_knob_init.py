# Copyright 2012 OpenStack Foundation
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
import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey
from sqlalchemy import Integer, MetaData, String, Table


def define_tables(meta):

    services = Table(
        'services', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('host', String(length=255)),
        Column('binary', String(length=255)),
        Column('topic', String(length=255)),
        Column('modified_at', DateTime(timezone=False)),

        mysql_engine='InnoDB'
    )
    gates = Table(
        'gates', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('name', String(length=255), nullable=False),
        Column('fip_id', String(length=36), nullable=False),
        Column('port_id', String(length=36), nullable=False),
        Column('server_id', String(length=36), nullable=False),
        Column('tenant_id', String(length=36)),
        mysql_engine='InnoDB'
        )
    targets = Table(
        'targets', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('server_id', String(length=36), primary_key=True, nullable=False),
        Column('name', String(length=255)),
        Column('gate_id', Integer,
                          ForeignKey('gates.id'),
                          index=True,
                          nullable=False),
        Column('routable', Boolean),
        mysql_engine='InnoDB'
        )
    keys = Table(
        'gate_keys', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', String(length=36), primary_key=True, nullable=False),
        #Column('id', Integer, primary_key=True, nullable=False),
        Column('name', String(length=255)),
        Column('content', String(length=1024)),
        Column('gate_id', Integer,
                          ForeignKey('gates.id'),
                          index=True,
                          nullable=False),
        mysql_engine='InnoDB'
        )
    
    return [services,
            gates,
            targets,
            keys,
            ]


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    # create all tables
    # Take care on create order for those with FK dependencies
    tables = define_tables(meta)

    for table in tables:
        table.create()

    if migrate_engine.name == "mysql":
        tables = ["services",
                  "gates",
                  "targets",
                  "gate_keys",
                  ]

        migrate_engine.execute("SET foreign_key_checks = 0")
        for table in tables:
            migrate_engine.execute(
                "ALTER TABLE %s CONVERT TO CHARACTER SET utf8" % table)
        migrate_engine.execute("SET foreign_key_checks = 1")
        migrate_engine.execute(
            "ALTER DATABASE %s DEFAULT CHARACTER SET utf8" %
            migrate_engine.url.database)
        migrate_engine.execute("ALTER TABLE %s Engine=InnoDB" % table)
