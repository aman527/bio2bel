# -*- coding: utf-8 -*-

import logging
import os
from configparser import ConfigParser
from functools import wraps
from urllib.request import urlretrieve

from .constants import BIO2BEL_DIR, DEFAULT_CACHE_CONNECTION, DEFAULT_CONFIG_PATH
from .models import Action

log = logging.getLogger(__name__)

__all__ = [
    'get_data_dir',
    'get_connection',
    'bio2bel_populater',
    'make_downloader',
]


def get_data_dir(module_name):
    """Ensures the appropriate Bio2BEL data directory exists for the given module, then returns the file path

    :param str module_name: The name of the module. Ex: 'chembl'
    :return: The module's data directory
    :rtype: str
    """
    module_name = module_name.lower()
    data_dir = os.path.join(BIO2BEL_DIR, module_name)
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


def get_connection(module_name, connection=None):
    """Return the SQLAlchemy connection string if it is set

    Order of operations:

    1. Return the connection if given as a parameter
    2. Check the environment for BIO2BEL_{module_name}_CONNECTION
    3. Look in the bio2bel config file for module-specific connection. Create if doesn't exist. Check the
       module-specific section for ``connection``
    4. Look in the bio2bel module folder for a config file. Don't create if doesn't exist. Check the default section
       for ``connection``
    5. Check the environment for BIO2BEL_CONNECTION
    6. Check the bio2bel config file for default
    7. Fall back to standard default cache connection

    :param str module_name: The name of the module to get the configuration for
    :param Optional[str] connection: get the SQLAlchemy connection string
    :return: The SQLAlchemy connection string based on the configuration
    :rtype: str
    """
    module_name = module_name.lower()

    # 1. Use given connection
    if connection is not None:
        return connection

    # 2. Check the environment for the module
    bio2bel_module_env = 'BIO2BEL_{}_CONNECTION'.format(module_name.upper())
    bio2bel_module_env_value = os.environ.get(bio2bel_module_env)
    if bio2bel_module_env_value is not None:
        log.debug('loaded connection from environment (%s): %s', bio2bel_module_env, bio2bel_module_env_value)
        return bio2bel_module_env_value

    # 4. Check the global Bio2BEL configuration for module-specific connection information
    global_config = ConfigParser()
    local_config = ConfigParser()

    if os.path.exists(DEFAULT_CONFIG_PATH):
        global_config.read(DEFAULT_CONFIG_PATH)
        if global_config.has_option(module_name, 'connection'):
            global_module_connection = global_config.get(module_name, 'connection')
            log.debug('loading connection string from global configuration (%s): %s', DEFAULT_CONFIG_PATH,
                      global_module_connection)
            return global_module_connection

    # 5. Check if there is module-specific configuration
    module_config_path = os.path.join(BIO2BEL_DIR, module_name, 'config.ini')
    if os.path.exists(module_config_path):
        local_config.read(module_config_path)
        if local_config.has_option(local_config.default_section, 'connection'):
            local_module_connection = local_config.get(local_config.default_section, 'connection')
            log.debug('loading connection string from local configuration (%s)', module_config_path,
                      local_module_connection)
            return local_module_connection

    # 6. Check if there is a global connection
    global_environ_connection = os.environ.get('BIO2BEL_CONNECTION')
    if global_environ_connection is not None:
        log.debug('loading global bio2bel connection from environ: %s', global_environ_connection)
        return global_environ_connection

    # 7. Use the global configuration file's global default cache connection string
    if not os.path.exists(DEFAULT_CONFIG_PATH):
        log.debug('creating config file: %s', DEFAULT_CONFIG_PATH)
        config_writer = ConfigParser()
        with open(DEFAULT_CONFIG_PATH, 'w') as f:
            config_writer.set(config_writer.default_section, 'connection', DEFAULT_CACHE_CONNECTION)
            config_writer.write(f)

    log.debug('fetching global bio2bel config from %s', DEFAULT_CONFIG_PATH)
    config = ConfigParser()
    config.read(DEFAULT_CONFIG_PATH)

    if not config.has_option(config.default_section, 'connection'):
        log.debug('creating default connection string %s', DEFAULT_CACHE_CONNECTION)
        return DEFAULT_CACHE_CONNECTION

    default_connection = config.get(config.default_section, 'connection')
    log.debug('load default connection string from %s', default_connection)

    return default_connection


def bio2bel_populater(resource, session=None):
    """Apply this decorator to a function so Bio2BEL's database gets populated automatically

    :param str resource: The name of the Bio2BEL package to populate
    :param Optional[sqlalchemy.orm.Session] session: A pre-built session

    Usage:

    >>> from bio2bel.utils import bio2bel_populater
    >>>
    >>> @bio2bel_populater('hgnc')
    >>> def populate_hgnc(...):
    >>>     ...
    """

    def wrap_bio2bel_func(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            Action.store_populate(resource, session=session)
            return f(*args, **kwargs)

        return wrapped

    return wrap_bio2bel_func


def make_downloader(url, path):
    """Makes a function that downloads the data for you, or uses a cached version at the given path

    :param str url: The URL of some data
    :param str path: The path of the cached data, or where data is cached if it does not already exist
    :return: A function that downloads the data and returns the path of the data
    :rtype: (bool -> str)
    """

    def download_data(force_download=False):
        """Downloads the data

        :param bool force_download: If true, overwrites a previously cached file
        :rtype: str
        """
        if os.path.exists(path) and not force_download:
            log.info('using cached data at %s', path)
        else:
            log.info('downloading %s to %s', url, path)
            urlretrieve(url, path)

        return path

    return download_data
