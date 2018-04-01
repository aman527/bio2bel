# -*- coding: utf-8 -*-

from abc import ABC, abstractmethod

from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from .models import Action
from .utils import get_connection

__all__ = [
    'Bio2BELMissingNameError',
    'Bio2BELModuleCaseError',
    'Bio2BELMissingModelsError',
    'AbstractManager',
]


class Bio2BELMissingNameError(TypeError):
    """Raised when an abstract manager is subclassed and instantiated without overriding the module name"""


class Bio2BELModuleCaseError(TypeError):
    """Raised when the module name in a subclassed and instantiated manager is not all lowercase"""

class Bio2BELMissingModelsError(TypeError):
    """Raises when trying to build a flask admin app with no models defined"""

class AbstractManagerConnectionMixin(object):
    """Represents the connection-building aspect of the abstract manager. Minimally requires the definition of the
    class-level variable, ``module_name``

    Example for InterPro:

    >>> from bio2bel.abstractmanager import AbstractManagerConnectionMixin
    >>> class Manager(AbstractManagerConnectionMixin):
    >>>     module_name = 'interpro'


    In general, this class won't be used directly except in the situation where the connection should be loaded
    in a different way and it can be used as a mixin.
    """

    #: This represents the module name. Needs to be lower case
    module_name = ...

    def __init__(self, connection=None):
        """
        :param Optional[str] connection: SQLAlchemy connection string
        """
        if not self.module_name or not isinstance(self.module_name, str):
            raise Bio2BELMissingNameError('module_name class variable not set on {}'.format(self.__class__.__name__))

        if self.module_name != self.module_name.lower():
            raise Bio2BELModuleCaseError('module_name class variable should be lowercase')

        self.connection = self.get_connection(connection=connection)
        self.engine = create_engine(self.connection)
        self.session_maker = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)
        self.session = scoped_session(self.session_maker)

    @classmethod
    def get_connection(cls, connection=None):
        """Gets the default connection string by wrapping :func:`bio2bel.utils.get_connection` and passing
        :data:`module_name` to it.

        :param Optional[str] connection: A custom connection to pass through
        :rtype: str
        """
        return get_connection(cls.module_name, connection=connection)


class AbstractManagerBase(ABC, AbstractManagerConnectionMixin):

    def __init__(self, connection=None, check_first=True):
        """
        :param Optional[str] connection: SQLAlchemy connection string
        :param bool check_first: Defaults to True, don't issue CREATEs for tables already present
         in the target database. Defers to :meth:`bio2bel.abstractmanager.AbstractManager.create_all`
        """
        super().__init__(connection=connection)
        self.create_all(check_first=check_first)

    @property
    @abstractmethod
    def base(self):
        """Returns the abstract base. Usually sufficient to return an instance that is module-level.

        :rtype: sqlalchemy.ext.declarative.api.DeclarativeMeta

        How to build an instance of :class:`sqlalchemy.ext.declarative.api.DeclarativeMeta`:

        >>> from sqlalchemy.ext.declarative import declarative_base
        >>> Base = declarative_base()

        Then just override this abstractmethod like:

        >>> def base(self):
        >>>     return Base
        """

    def create_all(self, check_first=True):
        """Create the empty database (tables)

        :param bool check_first: Defaults to True, don't issue CREATEs for tables already present
         in the target database. Defers to :meth:`sqlalchemy.sql.schema.MetaData.create_all`
        """
        self.base.metadata.create_all(self.engine, checkfirst=check_first)


class AbstractManagerFlaskMixin(AbstractManagerConnectionMixin):
    """Mixin for making the AbstractManager build a Flask application"""

    #: Represents a list of SQLAlchemy classes to make a Flask-Admin interface
    flask_admin_models = ...

    def _add_admin(self, app, **kwargs):
        """Adds a Flask Admin interface to an application

        :param flask.Flask app: A Flask application
        :param kwargs:
        :rtype: flask_admin.Admin
        """
        if self.flask_admin_models is ...:
            raise Bio2BELMissingModelsError

        from flask_admin import Admin
        from flask_admin.contrib.sqla import ModelView

        admin = Admin(app, **kwargs)

        for Model in self.flask_admin_models:
            admin.add_view(ModelView(Model, self.session))

        return admin

    def get_flask_admin_app(self, url=None):
        """Creates a Flask application

        :type url: Optional[str]
        :rtype: flask.Flask
        """
        from flask import Flask

        app = Flask(__name__)
        self._add_admin(app, url=(url or '/'))
        return app


class AbstractManager(AbstractManagerFlaskMixin, AbstractManagerBase):
    """Managers handle the database construction, population and querying.

    :cvar str module_name: The name of the module represented by this manager

    Needs several hooks/abstract methods to be set/overridden, but ultimately reduces redundant code

    Example for InterPro:

    >>> from sqlalchemy.ext.declarative import declarative_base
    >>> from bio2bel.abstractmanager import AbstractManager
    >>> Base = declarative_base()
    >>> class Manager(AbstractManager):
    >>>     module_name = 'interpro'
    >>>
    >>>     @property
    >>>     def base(self):
    >>>         return Base
    >>>
    >>>     def populate(self):
    >>>         ...

    Bio2BEL managers can be used as a context manager to automatically clean up the connection resources at the end of
    the context, as well:

    >>> manager = Manager()
    >>> with manager:
    >>>     # Create models, query them, make commits
    """

    @classmethod
    def ensure(cls, connection=None):
        """Checks and allows for a Manager to be passed to the function.

        :param connection: can be either a already build manager or a connection string to build a manager with.
        :type connection: Optional[str or AbstractManager]
        """
        if connection is None or isinstance(connection, str):
            return cls(connection=connection)

        if isinstance(connection, cls):
            return connection

        raise TypeError('passed invalid type: {}'.format(connection.__class__.__name__))

    @abstractmethod
    def populate(self, *args, **kwargs):
        """Populate method should be overridden"""

    def _count_model(self, model):
        """Helps count the number of a given model in the database

        :param sqlalchemy.ext.declarative.api.DeclarativeMeta model: A SQLAlchemy model class
        :rtype: int
        """
        return self.session.query(model).count()

    def drop_all(self, check_first=True):
        """Create the empty database (tables)

        :param bool check_first: Defaults to True, only issue DROPs for tables confirmed to be
          present in the target database. Defers to :meth:`sqlalchemy.sql.schema.MetaData.drop_all`
        """
        self.base.metadata.drop_all(self.engine, checkfirst=check_first)
        Action.store_drop(self.module_name)

    def __repr__(self):
        return '<{module_name}Manager url={url}>'.format(
            module_name=self.module_name.capitalize(),
            url=self.engine.url
        )
