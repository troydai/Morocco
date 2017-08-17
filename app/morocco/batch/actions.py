import os
import base64
from typing import Iterable
from datetime import datetime, timedelta

from flask import url_for

from azure.batch.models import (TaskAddParameter, JobAddParameter, JobPreparationTask, JobManagerTask, PoolInformation,
                                OutputFile, OutputFileDestination, OutputFileUploadOptions, OutputFileUploadCondition,
                                OutputFileBlobContainerDestination, OnAllTasksComplete, EnvironmentSetting,
                                ResourceFile, MetadataItem, CloudJob, CloudTask, TaskDependencies)
from azure.storage.blob import ContainerPermissions

from morocco.core import (get_batch_client, get_source_control_info, get_batch_pool, get_blob_storage_client,
                          get_automation_actor_info, get_batch_account_info)
from morocco.util import get_command_string, get_logger


def _get_build_blob_container_url() -> str:
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


def create_build_job(commit_sha: str) -> CloudJob:
    """
    Schedule a build job in the given pool. returns the container for build output and job reference.

    Building and running tests are two separate builds so that the testing job can relies on job preparation tasks to
    prepare test environment. The product and test build is an essential part of the preparation. The builds can't be
    combined because the preparation task has to be defined by the time the job is created. However neither the product
    or the test package is ready then.
    """
    batch_client = get_batch_client()
    source_control_info = get_source_control_info()

    remote_source_dir = 'gitsrc'
    logger = get_logger('build')
    pool = get_batch_pool('build')

    if not pool:
        logger.error('Cannot find a build pool. Please check the pools list in config file.')
        raise ValueError('Fail to find a build pool.')

    # secret is a random string used to verify the identity of caller when one task requests the service to do
    # something. the secret is saved to the job definition as metadata, and it is passed to some tasks as well.
    secret = base64.b64encode(os.urandom(64)).decode('utf-8')

    job_metadata = [MetadataItem('usage', 'build'),
                    MetadataItem('secret', secret),
                    MetadataItem('source_url', source_control_info.url),
                    MetadataItem('source_sha', commit_sha)]

    logger.info('Creating build job %s in pool %s', commit_sha, pool.id)
    batch_client.job.add(JobAddParameter(id=commit_sha,
                                         pool_info=PoolInformation(pool.id),
                                         on_all_tasks_complete=OnAllTasksComplete.terminate_job,
                                         metadata=job_metadata,
                                         uses_task_dependencies=True))
    logger.info('Job %s is created.', commit_sha)

    output_file_name = 'azure-cli-{}.tar'.format(commit_sha)
    build_commands = [
        'git clone --depth=50 {} {}'.format(source_control_info.url, remote_source_dir),
        'pushd {}'.format(remote_source_dir),
        'git checkout -qf {}'.format(commit_sha),
        './scripts/batch/build_all.sh',
        'tar cvzf {} ./artifacts'.format(output_file_name)
    ]

    build_container_url = _get_build_blob_container_url()

    output_file = OutputFile('{}/{}'.format(remote_source_dir, output_file_name),
                             OutputFileDestination(OutputFileBlobContainerDestination(build_container_url,
                                                                                      output_file_name)),
                             OutputFileUploadOptions(OutputFileUploadCondition.task_success))

    build_task = TaskAddParameter(id='build',
                                  command_line=get_command_string(*build_commands),
                                  display_name='Build all product and test code.',
                                  output_files=[output_file])

    cburl = 'curl -X post {} -H "X-Batch-Event: build.finished" --data-urlencode secret={} --data-urlencode sha={}'
    report_cmd = cburl.format(url_for('post_api_build', _external=True, _scheme='https'), secret, commit_sha)

    report_task = TaskAddParameter(id='report',
                                   command_line=get_command_string(report_cmd),
                                   depends_on=TaskDependencies(task_ids=[build_task.id]),
                                   display_name='Request service to pull result')

    batch_client.task.add(commit_sha, build_task)
    batch_client.task.add(commit_sha, report_task)
    logger.info('Build task is added to job %s', commit_sha)

    return batch_client.job.get(commit_sha)


def create_test_job(build_id: str, run_live: bool = False) -> str:  # pylint: disable=too-many-locals
    logger = get_logger('test')

    batch_account = get_batch_account_info()
    batch_client = get_batch_client()
    storage_client = get_blob_storage_client()
    automation_actor = get_automation_actor_info()
    job_id = 'test-{}'.format(datetime.utcnow().strftime('%Y%m%d-%H%M%S'))
    output_file_name = 'azure-cli-{}.tar'.format(build_id)

    def _list_build_resource_files() -> Iterable[ResourceFile]:
        """ List the files belongs to the target build in the build blob container """
        permission = ContainerPermissions(read=True)
        expiry = (datetime.utcnow() + timedelta(days=1))
        build_sas = storage_client.generate_container_shared_access_signature(container_name='builds',
                                                                              permission=permission,
                                                                              expiry=expiry)
        app_sas = storage_client.generate_container_shared_access_signature(container_name='app',
                                                                            permission=permission,
                                                                            expiry=expiry)

        return [ResourceFile(blob_source=storage_client.make_blob_url('builds', output_file_name, 'https', build_sas),
                             file_path=output_file_name),
                ResourceFile(blob_source=storage_client.make_blob_url('app', 'tangier.tar', 'https', app_sas),
                             file_path='tangier.tar')]

    def _create_output_container_folder() -> str:
        """ Create output storage container """
        # output_container_name = 'output-{}'.format(job_id)
        storage_client.create_container(container_name='output')

        return storage_client.make_blob_url(
            container_name='output',
            blob_name='',
            protocol='https',
            sas_token=storage_client.generate_container_shared_access_signature(
                container_name='output',
                permission=ContainerPermissions(list=True, write=True),
                expiry=(datetime.utcnow() + timedelta(days=1))))

    # create automation job
    resource_files = _list_build_resource_files()
    if not resource_files:
        logger.error('The build %s is not found in the builds container', build_id)
        raise ValueError('Fail to find build {}'.format(build_id))

    prep_task = JobPreparationTask(get_command_string('tar xvf {}'.format(output_file_name),
                                                      'mv ./artifacts/* ./',
                                                      'tar xvf tangier.tar',
                                                      './app/install.sh'),
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

    cburl = 'curl -X post {} -H "X-Batch-Event: test.finished" --data-urlencode job_id={}'
    report_cmd = cburl.format(url_for('api_hook', _external=True, _scheme='https'), job_id)
    report_cmd += ' --data-urlencode task_id='

    job_environment = [EnvironmentSetting(name='AUTOMATION_OUTPUT_CONTAINER', value=output_container_url),
                       EnvironmentSetting(name='AUTOMATION_REPORT_CMD', value=report_cmd)]
    if run_live:
        job_environment.append(EnvironmentSetting(name='AZURE_TEST_RUN_LIVE', value='True'))
        job_environment.append(EnvironmentSetting(name='AUTOMATION_SP_NAME', value=automation_actor.account))
        job_environment.append(EnvironmentSetting(name='AUTOMATION_SP_PASSWORD', value=automation_actor.key))
        job_environment.append(EnvironmentSetting(name='AUTOMATION_SP_TENANT', value=automation_actor.tenant))

    # secret is a random string used to verify the identity of caller when one task requests the service to do
    # something. the secret is saved to the job definition as metadata, and it is passed to some tasks as well.
    secret = base64.b64encode(os.urandom(64)).decode('utf-8')

    # metadata
    job_metadata = [MetadataItem('usage', 'test'),
                    MetadataItem('secret', secret),
                    MetadataItem('build', build_id),
                    MetadataItem('live', str(run_live))]

    # create automation job
    batch_client.job.add(JobAddParameter(
        id=job_id,
        pool_info=PoolInformation(get_batch_pool('test').id),
        display_name='Automation on build {}. Live: {}'.format(build_id, run_live),
        common_environment_settings=job_environment,
        job_preparation_task=prep_task,
        job_manager_task=manage_task,
        on_all_tasks_complete=OnAllTasksComplete.terminate_job,
        metadata=job_metadata,
        uses_task_dependencies=True))

    logger.info('Job %s is created with preparation task and manager task.', job_id)
    return job_id


def get_job(job_id: str) -> CloudJob:
    return get_batch_client().job.get(job_id)


def list_tasks(job_id: str) -> Iterable[CloudTask]:
    return get_batch_client().task.list(job_id)
