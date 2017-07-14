from typing import List
from azure.batch import BatchServiceClient
from azure.storage.blob import BlockBlobService
from .models import SourceControlInfo


def get_build_blob_container_url(storage_client: BlockBlobService) -> str:
    from datetime import datetime, timedelta
    from azure.storage.blob import ContainerPermissions

    storage_client.create_container('builds', fail_on_exist=False)
    return storage_client.make_blob_url(
        container_name='builds',
        blob_name='',
        protocol='https',
        sas_token=storage_client.generate_container_shared_access_signature(
            container_name='builds',
            permission=ContainerPermissions(list=True, write=True),
            expiry=(datetime.utcnow() + timedelta(days=1))))


def create_build_job(batch_client: BatchServiceClient,
                     storage_client: BlockBlobService,
                     source_control_info: SourceControlInfo) -> str:
    """
    Schedule a build job in the given pool. returns the container for build output and job reference.

    Building and running tests are two separate jobs so that the testing job can relies on job preparation tasks to
    prepare test environment. The product and test build is an essential part of the preparation. The jobs can't be
    combined because the preparation task has to be defined by the time the job is created. However neither the product
    or the test package is ready then.
    """
    from azure.batch.models import (TaskAddParameter, JobAddParameter, PoolInformation, OutputFile,
                                    OutputFileDestination, OutputFileUploadOptions, OutputFileUploadCondition,
                                    OutputFileBlobContainerDestination, OnAllTasksComplete)
    from .models import get_batch_pool
    from .util import get_command_string, get_logger, generate_build_id

    remote_source_dir = 'gitsrc'
    logger = get_logger('build')
    build_id = generate_build_id()
    pool = get_batch_pool('build')
    if not pool:
        logger.error('Cannot find a build pool. Please check the pools list in config file.')
        raise ValueError('Fail to find a build pool.')

    logger.info('Creating build job %s in pool %s', build_id, pool.id)
    batch_client.job.add(JobAddParameter(id=build_id,
                                         pool_info=PoolInformation(pool.id),
                                         on_all_tasks_complete=OnAllTasksComplete.terminate_job))
    logger.info('Job %s is created.', build_id)

    build_commands = [
        'git clone -b {} -- {} gitsrc'.format(source_control_info.branch, source_control_info.url),
        'pushd {}'.format(remote_source_dir),
        './scripts/batch/build_all.sh'
    ]

    build_container_url = get_build_blob_container_url(storage_client)

    output_file = OutputFile('{}/artifacts/**/*.*'.format(remote_source_dir),
                             OutputFileDestination(OutputFileBlobContainerDestination(build_container_url, build_id)),
                             OutputFileUploadOptions(OutputFileUploadCondition.task_success))

    build_task = TaskAddParameter(id='build',
                                  command_line=get_command_string(*build_commands),
                                  display_name='Build all product and test code.',
                                  output_files=[output_file])

    batch_client.task.add(build_id, build_task)
    logger.info('Build task is added to job %s', build_id)

    return build_id


def create_test_job(build_id: str, run_live: bool = False) -> str:  # pylint: disable=too-many-locals
    import sys
    from datetime import datetime, timedelta
    from azure.batch.models import (JobPreparationTask, JobAddParameter, JobManagerTask, OnAllTasksComplete,
                                    PoolInformation, EnvironmentSetting, ResourceFile)
    from azure.storage.blob.models import ContainerPermissions
    from .util import get_logger, get_command_string
    from .models import (get_batch_client, get_batch_account_info, get_blob_storage_client, get_automation_actor_info,
                         get_batch_pool)

    logger = get_logger('test')

    batch_account = get_batch_account_info()
    batch_client = get_batch_client(batch_account)
    storage_client = get_blob_storage_client()
    automation_actor = get_automation_actor_info()
    job_id = 'test-{}'.format(datetime.utcnow().strftime('%Y%m%d-%H%M%S'))

    def _list_build_resource_files() -> List[ResourceFile]:
        """ List the files belongs to the target build in the build blob container """
        if not storage_client.get_container_properties('builds'):
            logger.error('The build container %s is not found.', 'builds')
            sys.exit(2)

        sas = storage_client.generate_container_shared_access_signature(container_name='builds',
                                                                        permission=ContainerPermissions(read=True),
                                                                        expiry=(datetime.utcnow() + timedelta(days=1)))
        logger.info('Container %s is found and read only SAS token is generated.', 'builds')

        build_blobs = storage_client.list_blobs(container_name='builds', prefix=build_id)
        return [ResourceFile(blob_source=storage_client.make_blob_url('builds', blob.name, 'https', sas),
                             file_path=blob.name[len(build_id) + 1:]) for blob in build_blobs]

    def _create_output_container_folder() -> str:
        """ Create output storage container """
        output_container_name = 'output-{}'.format(job_id)
        storage_client.create_container(container_name=output_container_name)

        return storage_client.make_blob_url(
            container_name=output_container_name,
            blob_name='',
            protocol='https',
            sas_token=storage_client.generate_container_shared_access_signature(
                container_name=output_container_name,
                permission=ContainerPermissions(list=True, write=True),
                expiry=(datetime.utcnow() + timedelta(days=1))))

    # create automation job
    resource_files = _list_build_resource_files()
    if not resource_files:
        logger.error('The build %s is not found in the builds container', build_id)
        raise ValueError('Fail to find build {}'.format(build_id))

    prep_task = JobPreparationTask(get_command_string('./app/install.sh'),
                                   resource_files=resource_files,
                                   wait_for_success=True)

    env_settings = [EnvironmentSetting(name='AZURE_BATCH_KEY', value=batch_account.key),
                    EnvironmentSetting(name='AZURE_BATCH_ENDPOINT', value=batch_account.endpoint)]

    manage_task = JobManagerTask('test-creator',
                                 get_command_string('$AZ_BATCH_NODE_SHARED_DIR/app/schedule.sh'),
                                 'Automation tasks creator',
                                 kill_job_on_completion=False,
                                 environment_settings=env_settings)

    output_container_url = _create_output_container_folder()

    job_environment = [EnvironmentSetting(name='AUTOMATION_OUTPUT_CONTAINER', value=output_container_url)]
    if run_live:
        job_environment.append(EnvironmentSetting(name='AZURE_TEST_RUN_LIVE', value='True'))
        job_environment.append(EnvironmentSetting(name='AUTOMATION_SP_NAME', value=automation_actor.account))
        job_environment.append(EnvironmentSetting(name='AUTOMATION_SP_PASSWORD', value=automation_actor.key))
        job_environment.append(EnvironmentSetting(name='AUTOMATION_SP_TENANT', value=automation_actor.tenant))

    # create automation job
    batch_client.job.add(JobAddParameter(
        id=job_id,
        pool_info=PoolInformation(get_batch_pool('test').id),
        display_name='Automation on build {}. Live: {}'.format(build_id, run_live),
        common_environment_settings=job_environment,
        job_preparation_task=prep_task,
        job_manager_task=manage_task,
        on_all_tasks_complete=OnAllTasksComplete.terminate_job))

    logger.info('Job %s is created with preparation task and manager task.', job_id)
    return job_id
