def create_test_job(build_id: str, run_live: bool = False) -> str:  # pylint: disable=too-many-locals
    import sys
    from datetime import datetime, timedelta
    from azure.batch.models import (JobPreparationTask, JobAddParameter, JobManagerTask, OnAllTasksComplete,
                                    PoolInformation, EnvironmentSetting, ResourceFile)
    from azure.storage.blob.models import ContainerPermissions
    from morocco.util import get_logger, get_command_string
    from morocco.models import (get_batch_client, get_batch_account_info, get_blob_storage_client, get_automation_actor_info,
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
