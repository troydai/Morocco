from typing import Tuple


def sync_build(commit: dict = None, sha: str = None, create_job=False):
    from datetime import datetime, timedelta

    from azure.batch.models import BatchErrorException, JobState
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
        db.session.add(build_record)

    try:
        batch_client = get_batch_client()
        batch_job = batch_client.job.get(sha)
        if create_job and batch_job.state == JobState.completed:
            batch_client.job.delete(sha)
            batch_job = create_build_job(sha)
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


def sync_test_run(job_id: str):
    import requests
    import os.path
    from datetime import datetime, timedelta

    from azure.batch.models import JobState
    from azure.storage.blob.models import BlobPermissions

    from morocco.core import get_blob_storage_client
    from morocco.batch import get_job, list_tasks

    from ..models import DbTestRun, DbTestCase
    from ..application import db

    storage = get_blob_storage_client()

    test_run = DbTestRun.query.filter_by(id=job_id).first()
    if not test_run:
        return "Test run job not found", 404

    test_run_job = get_job(job_id)
    test_run.state = test_run_job.state.value

    if test_run_job.state == JobState.completed:
        for task in list_tasks(job_id):
            if task.id == 'test-creator':
                continue

            test_case = DbTestCase.query.filter_by(id=DbTestCase.get_full_name(task, test_run)).one_or_none()
            if test_case:
                continue

            test_case = DbTestCase(task, test_run)

            if not test_case.passed:
                # only load output of failed tests for performance reason
                container_name = 'output'
                blob_name = os.path.join(job_id, task.id, 'stdout.txt')
                sas = storage.generate_blob_shared_access_signature(container_name, blob_name,
                                                                    permission=BlobPermissions(read=True),
                                                                    protocol='https',
                                                                    expiry=(datetime.utcnow() + timedelta(hours=1)))
                url = storage.make_blob_url(container_name, blob_name, sas_token=sas, protocol='https')

                response = requests.request('GET', url)
                test_case.output = '\n'.join(response.text.split('\n')[58:-3])

            db.session.add(test_case)
    db.session.commit()

    return test_run


def on_github_push(payload: dict) -> str:
    from morocco.main import DbBuild
    from morocco.core import get_source_control_commits

    if payload['ref'] != 'refs/heads/master':
        return 'Skip push on branch other than master.'

    last_build = DbBuild.query.order_by(DbBuild.commit_date.desc()).first()
    commits = get_source_control_commits(since=last_build.commit_date.strftime('%Y-%m-%dT%H:%M:%SZ'))
    for commit in commits[:-1]:
        sync_build(commit, create_job=True)

    return 'Success: {} build scheduled'.format(len(commits) - 1)


def on_batch_callback(request, db_build_model) -> Tuple[str, int]:
    from morocco.core import get_batch_client
    from morocco.batch import get_metadata
    secret = request.form.get('secret')
    if not secret:
        return 'Missing secret', 403

    sha = request.form.get('sha')
    if not sha:
        return 'Missing commit sha', 400

    build_record = db_build_model.query.filter_by(id=sha).first()
    if not build_record:
        return 'Build found', 404

    batch_client = get_batch_client()
    job = batch_client.job.get(sha)
    if not job:
        return 'Cloud job is not found', 400

    expect_secret = get_metadata(job.metadata, 'secret')
    if expect_secret != secret:
        return 'Invalid secret', 403

    sync_build(sha=sha, create_job=False)

    return 'OK', 200
