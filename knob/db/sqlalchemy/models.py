# Copyright (c) 2011 X.commerce, a business unit of eBay Inc.
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2011 Piston Cloud Computing, Inc.
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

"""
SQLAlchemy models for knob data.
"""
import uuid

from oslo_config import cfg
from oslo_db.sqlalchemy import models
from oslo_utils import timeutils
from sqlalchemy import Column, Integer, String, Text, schema
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import ForeignKey, DateTime, Boolean
from sqlalchemy.orm import relationship, backref, validates
from sqlalchemy import PrimaryKeyConstraint


CONF = cfg.CONF
BASE = declarative_base()


class KnobBase(models.TimestampMixin,
                 models.ModelBase):
    """Base class for Knob Models."""

    __table_args__ = {'mysql_engine': 'InnoDB'}

    # TODO(rpodolyaka): reuse models.SoftDeleteMixin in the next stage
    #                   of implementing of BP db-cleanup
    deleted_at = Column(DateTime)
    deleted = Column(Boolean, default=False)
    metadata = None

    def delete(self, session):
        """Delete this object."""
        self.deleted = True
        self.deleted_at = timeutils.utcnow()
        self.save(session=session)


class Service(BASE, KnobBase):
    """Represents a running service on a host."""

    __tablename__ = 'services'
    id = Column(Integer, primary_key=True, nullable=False)
    host = Column(String(255))  # , ForeignKey('hosts.id'))
    binary = Column(String(255))
    topic = Column(String(255))
    modified_at = Column(DateTime)


class Gate(BASE, KnobBase):
    """Represents a Ssh gates (VM hosts)"""

    __tablename__ = 'gates'
    id = Column(Integer, primary_key=True, nullable=False)
    name = Column(String(255), nullable=False)  # , ForeignKey('hosts.id'))
    fip_id = Column(String(36), nullable=False)
    server_id = Column(String(36), nullable=False)
    tenant_id = Column(String(36))
    
    keys = relationship("Key", backref="gate")
    targets = relationship("Target", backref="gate")

    
class Key(BASE, KnobBase):
    """Represents a Ssh associates that allowed to work with service."""

    __tablename__ = 'gate_keys'
    id = Column(String(36), primary_key=True, 
                default=lambda: str(uuid.uuid4()))
    name = Column(String(length=255))
    content = Column(String(length=1024))
    gate_id = Column(Integer, ForeignKey('gates.id', name='gate_fk'),index=True,nullable=False)
    
    #gate = relationship("Gate", backref="keys")

class Target(BASE, KnobBase):
    """Represents a Ssh targets on for specified service."""

    __tablename__ = 'targets'
    server_id = Column(String(length=36), primary_key=True, nullable=False)
    name = Column(String(length=255))
    gate_id = Column(Integer, ForeignKey('gates.id',name='gate_fk'),index=True,nullable=False)
    routable = Column(Boolean)
    #_table_args__ = (PrimaryKeyConstraint(server_id, gate_id),)
    
    #gate = relationship("Gate", backref="targets")


def register_models():
    """Register Models and create metadata.

    TODO: understand if required to mimic cinder here
    Called from knob.db.sqlalchemy.__init__ as part of loading the driver,
    it will never need to be called explicitly elsewhere unless the
    connection is lost and needs to be reestablished.
    """
    from sqlalchemy import create_engine
    models = (Service,
              Gate,
              Key,
              Target
              )
    engine = create_engine(CONF.database.connection, echo=False)
    for model in models:
        model.metadata.create_all(engine)
