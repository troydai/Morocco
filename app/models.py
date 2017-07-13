import os
import logging
from collections import namedtuple

from azure.batch import BatchServiceClient
from azure.storage.blob import BlockBlobService

logger = logging.getLogger(__name__)
BatchAccountInfo = namedtuple('BatchAccountInfo', ['account', 'key', 'endpoint'])
BatchPoolInfo = namedtuple('BatchPoolInfo',
                           ['id', 'usage', 'sku', 'image', 'vmsize', 'dedicated', 'lowpri', 'maxtasks'])
SourceControlInfo = namedtuple('SourceControlInfo', ['url', 'branch'])
StorageAccountInfo = namedtuple('StorageAccountInfo', ['account', 'key'])
GeneralSettings = namedtuple('GeneralSettings', ['batch', 'source', 'storage'])


def get_setting_from_file():
    from .consts import EnvironmentVariableNames

    file_path = os.getenv(EnvironmentVariableNames.setting_file)
    if not file_path:
        return None

    file_path = os.path.expanduser(file_path)

    if not os.path.isfile(file_path):
        return None

    try:
        with open(file_path, 'r') as settings_file:
            import yaml
            return yaml.load(settings_file)
    except IOError:
        logger.error('Fail to read setting file {}.'.format(file_path))
        raise EnvironmentError('Fail to read setting file.')


MOROCCO_SETTINGS_FROM_FILE = get_setting_from_file()


def get_batch_account_info() -> BatchAccountInfo:
    if MOROCCO_SETTINGS_FROM_FILE:
        logger.info('Read batch account info from settings file.')
        return _read_section_from_file(BatchAccountInfo, 'azurebatch')

    logging.info('Read Azure Batch info from environment.')
    return _read_section_from_env(BatchAccountInfo)


def get_source_control_info() -> SourceControlInfo:
    if MOROCCO_SETTINGS_FROM_FILE:
        logging.info('Read source control info from settings file.')
        return _read_section_from_file(SourceControlInfo, 'gitsource')
    logging.info('Read source control info from environment.')
    return _read_section_from_env(SourceControlInfo)


def get_storage_account_info() -> StorageAccountInfo:
    if MOROCCO_SETTINGS_FROM_FILE:
        logging.info('Read storage account info from settings file.')
        return _read_section_from_file(StorageAccountInfo, 'azurestorage')

    logging.info('Read storage account info from environment.')
    return _read_section_from_env(StorageAccountInfo)


def get_batch_pools_from_file():
    try:
        pool_settings = MOROCCO_SETTINGS_FROM_FILE['pools']
        return [BatchPoolInfo(**each) for each in pool_settings]
    except KeyError:
        logger.error('Fail to parse setting file.')
        raise EnvironmentError('Fail to parse settings file.')


def get_batch_client(account_info: BatchAccountInfo = None) -> BatchServiceClient:
    from azure.batch.batch_auth import SharedKeyCredentials
    account_info = account_info or get_batch_account_info()
    cred = SharedKeyCredentials(account_info.account, account_info.key)
    return BatchServiceClient(cred, account_info.endpoint)


def get_blob_storage_client(account_info: StorageAccountInfo = None) -> BlockBlobService:
    account_info = account_info or get_storage_account_info()
    return BlockBlobService(account_info.account, account_info.key)


def _read_section_from_file(named_tuple_type, section_name: str):
    try:
        settings = MOROCCO_SETTINGS_FROM_FILE[section_name]
        return named_tuple_type(**settings)
    except KeyError:
        logger.error('Fail to section {} from settings file.'.format(section_name))
        raise EnvironmentError('Fail to read section from settings file.')


def _read_section_from_env(named_tuple_type, prefix: str = None):
    try:
        prefix = prefix or 'MOROCCO_BATCH_'
        fields = ['{}{}'.format(prefix, f.upper()) for f in named_tuple_type._fields]
        kwargs = {f: os.environ[f] for f in fields}
        return named_tuple_type(**kwargs)
    except KeyError as ex:
        raise EnvironmentError('Missing environment settings. {}'.format(ex))
