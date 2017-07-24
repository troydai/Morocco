from collections import namedtuple

from azure.batch import BatchServiceClient
from azure.storage.blob import BlockBlobService
from azure.batch.models import CloudPool

BatchAccountInfo = namedtuple('BatchAccountInfo', ['account', 'key', 'endpoint'])
SourceControlInfo = namedtuple('SourceControlInfo', ['url', 'branch'])
StorageAccountInfo = namedtuple('StorageAccountInfo', ['account', 'key'])
AutomationActorInfo = namedtuple('AutomationActorInfo', ['account', 'key', 'tenant'])


def get_source_control_info() -> SourceControlInfo:
    return _read_section_from_config(SourceControlInfo, prefix='SOURCE')


def get_storage_account_info() -> StorageAccountInfo:
    return _read_section_from_config(StorageAccountInfo, prefix='STORAGE')


def get_automation_actor_info() -> AutomationActorInfo:
    return _read_section_from_config(AutomationActorInfo, prefix='AUTOMATION')


def get_batch_account_info() -> BatchAccountInfo:
    return _read_section_from_config(BatchAccountInfo, prefix='BATCH')


def get_batch_client() -> BatchServiceClient:
    from azure.batch.batch_auth import SharedKeyCredentials
    account_info = get_batch_account_info()

    cred = SharedKeyCredentials(account_info.account, account_info.key)
    return BatchServiceClient(cred, account_info.endpoint)


def get_batch_pool(usage: str) -> CloudPool:
    build_pool = next(pool for pool in get_batch_client().pool.list() if
                      next(m.value for m in pool.metadata if m.name == 'usage') == usage)

    if not build_pool:
        raise EnvironmentError('Fail to find a pool.')

    return build_pool


def get_blob_storage_client() -> BlockBlobService:
    account_info = get_storage_account_info()
    return BlockBlobService(account_info.account, account_info.key)


def _read_section_from_config(named_tuple_type, prefix: str):
    from morocco.main import app

    try:
        fields = {f: 'MOROCCO_{}_{}'.format(prefix, f).upper() for f in named_tuple_type._fields}
        kwargs = {f: app.config[env_name] for f, env_name in fields.items()}
        return named_tuple_type(**kwargs)
    except KeyError as ex:
        raise EnvironmentError('Missing environment settings. {}'.format(ex))
