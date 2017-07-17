def _get_build_blob_container_url() -> str:
    from datetime import datetime, timedelta
    from azure.storage.blob import ContainerPermissions
    from ..models import get_blob_storage_client

    storage_client = get_blob_storage_client()
    storage_client.create_container('builds', fail_on_exist=False)
    return storage_client.make_blob_url(
        container_name='builds',
        blob_name='',
        protocol='https',
        sas_token=storage_client.generate_container_shared_access_signature(
            container_name='builds',
            permission=ContainerPermissions(list=True, write=True),
            expiry=(datetime.utcnow() + timedelta(days=1))))


def create_build_job(branch: str) -> str:
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
    from ..models import get_batch_client, get_source_control_info, get_batch_pool
    from ..util import get_command_string, get_logger, generate_build_id

    batch_client = get_batch_client()
    source_control_info = get_source_control_info()

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
        'git clone -b {} -- {} gitsrc'.format(branch, source_control_info.url),
        'pushd {}'.format(remote_source_dir),
        './scripts/batch/build_all.sh'
    ]

    build_container_url = _get_build_blob_container_url()

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
