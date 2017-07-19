from datetime import datetime, timedelta
from typing import Union

from azure.batch.models import CloudJob, JobState
from azure.storage.blob.models import BlobPermissions

from morocco.models import get_blob_storage_client
from morocco.batch import get_metadata, get_job, list_tasks
from morocco.util import get_logger
from morocco.db.models import DbBuild, DbTestRun, DbUser
from morocco.exceptions import SecretError

# SQLAlchemy is banana
# pylint: disable=no-member


def get_or_add_user(user_id: str):
    from morocco.db.models import db

    logger = get_logger('db')
    user = DbUser.query.filter_by(id=user_id).first()
    if not user:
        user = DbUser(user_id)
        db.session.add(user)
        db.session.commit()
        logger.info('Create user {} in db.'.format(user_id))
    else:
        logger.info('Find user {} in db.'.format(user_id))


def get_or_add_build(job_id: str) -> DbBuild:
    from morocco.db.models import db

    logger = get_logger('db')
    logger.info('get_or_add_build({})'.format(job_id))

    build = DbBuild.query.filter_by(id=job_id).first()
    if not build:
        job = get_job(job_id)

        build = DbBuild(job)

        db.session.add(build)
        logger.info('Add DbBuild {}'.format(job_id))
        db.session.commit()
        logger.info('Commit DbBuild {}'.format(job_id))

        # Add the build to the database
        build = DbBuild.query.filter_by(id=job_id).first()

    logger.info('Return DbBuild {}'.format(job_id))
    return build


def update_build(job_id: str) -> None:
    from morocco.db.models import db

    get_or_add_build(job_id).update(get_job(job_id))
    db.session.commit()


def update_build_protected(job_id: str, secret: str) -> Union[DbBuild, None]:
    from morocco.db.models import db

    logger = get_logger('db')
    logger.info('update_build_protected({}, {})'.format(job_id, secret))

    if not secret:
        logger.warning('Missing secret. Request is rejected.')
        raise SecretError()

    build = DbBuild.query.filter_by(id=job_id).first()
    if not build:
        logger.warning('DbBuild {} is not found'.format(job_id))
        return None

    job = get_job(job_id)
    expect_secret = get_metadata(job.metadata, 'secret')
    if expect_secret != secret:
        logger.warning('Unmatched secret. Request is rejected.')
        raise SecretError()

    build.update(job)
    db.session.commit()
    logger.info('The build {} is updated'.format(job_id))

    return DbBuild.query.filter_by(id=job_id).first()


def get_or_add_test_run(job_id: str) -> DbTestRun:
    logger = get_logger('db')
    logger.info('get_or_add_test_run({})'.format(job_id))

    test_run = DbTestRun.query.filter_by(id=job_id).first()
    if not test_run:
        from morocco.db.models import db

        test_run = DbTestRun(get_job(job_id))
        db.session.add(test_run)
        db.session.commit()

    return test_run


def update_test_run_protected(job_id: str, secret: str) -> Union[DbTestRun, None]:
    logger = get_logger('db')
    logger.info('update_test_run_protected({}, {})'.format(job_id, secret))

    if not secret:
        logger.warning('Missing secret. Request is rejected.')
        raise SecretError()

    job = get_job(job_id)
    expect_secret = get_metadata(job.metadata, 'secret')
    if expect_secret != secret:
        logger.warning('Unmatched secret. Request is rejected.')
        raise SecretError()

    return update_test_run(job_id, job)


def update_test_run(job_id: str, job: CloudJob = None) -> Union[DbTestRun, None]:
    import os
    import requests
    from morocco.db.models import db, DbTestCase

    logger = get_logger('db')
    logger.info('update_test_run({})'.format(job_id))

    storage = get_blob_storage_client()

    test_run = DbTestRun.query.filter_by(id=job_id).first()
    if not test_run:
        logger.warning('The test run {} is not found'.format(job_id))
        return None

    test_run_job = job or get_job(job_id)
    test_run.state = test_run_job.state.value

    if test_run_job.state == JobState.completed:
        test_run.total_tests = 0
        test_run.failed_tests = 0

        for task in list_tasks(job_id):
            if task.id == 'test-creator':
                continue

            test_run.total_tests += 1
            test_case = DbTestCase(task, test_run)

            if not test_case.passed:
                test_run.failed_tests += 1
                container_name = 'output-' + test_run.id
                blob_name = os.path.join(task.id, 'stdout.txt')
                sas = storage.generate_blob_shared_access_signature(container_name, blob_name,
                                                                    permission=BlobPermissions(read=True),
                                                                    protocol='https',
                                                                    expiry=(datetime.utcnow() + timedelta(hours=1)))
                url = storage.make_blob_url(container_name, blob_name, sas_token=sas, protocol='https')

                response = requests.request('GET', url)
                test_case.output = '\n'.join(response.text.split('\n')[58:-3])

            db.session.add(test_case)

    db.session.commit()
    logger.info('The test run {} is updated'.format(job_id))

    return DbTestRun.query.filter_by(id=job_id).first()
