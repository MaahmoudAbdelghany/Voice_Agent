"""
Declarative Base and Metadata Configuration for Voice Agent Relational Database.

Defines the SQLAlchemy 2.0 DeclarativeBase with explicit naming conventions
for indexes and constraints, ensuring cross-database consistency between
SQLite and PostgreSQL.
"""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Standard naming conventions for constraints across database engines
POSTGRES_SQLITE_NAMING_CONVENTIONS = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy declarative models."""

    metadata = MetaData(naming_convention=POSTGRES_SQLITE_NAMING_CONVENTIONS)
