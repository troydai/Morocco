def sync_build(commit: dict = None, sha: str = None, create_job=False):
    from datetime import datetime, timedelta

    from azure.batch.models import BatchErrorException
    from azure.storage.blob.models import BlobPermissions

    from morocco.core.services import (get_source_control_commit, get_source_control_commits, get_batch_client,
                                       get_blob_storage_client)
    from morocco.main import DbBuild, db
    from morocco.batch import create_build_job

    if not dict and not sha:
        raise ValueError('Missing commit')

    if not commit:
        if sha == '<latest>':
            commit = get_source_control_commits()[0]
        else:
            commit = commit or get_source_control_commit(sha)

    sha = commit['sha']

    build_record = DbBuild.query.filter_by(id=sha).one_or_none()
    if build_record:
        build_record.update_commit(commit)
    else:
        build_record = DbBuild(commit=commit)
        db.session.add(DbBuild(commit))

    try:
        batch_job = get_batch_client().job.get(sha)
    except BatchErrorException:
        if create_job:
            batch_job = create_build_job(sha)
        else:
            batch_job = None

    if batch_job:
        # build job can be deleted. it is not required to keep data in sync
        build_task = get_batch_client().task.get(job_id=sha, task_id='build')
        if not build_task:
            return 'Cloud task for the build is not found', 400
        build_record.state = build_task.state.value

    storage = get_blob_storage_client()
    blob = 'azure-cli-{}.tar'.format(sha)
    if storage.exists(container_name='builds', blob_name=blob):
        build_record.build_download_url = storage.make_blob_url(
            'builds', blob_name=blob, protocol='https', sas_token=storage.generate_blob_shared_access_signature(
                'builds', blob, BlobPermissions(read=True), expiry=datetime.utcnow() + timedelta(days=365)))

    db.session.commit()

    return build_record
