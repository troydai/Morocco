# pylint: disable=no-member, invalid-name, too-few-public-methods, too-many-locals


def init_database(app):
    import os
    from typing import Union
    from collections import namedtuple

    from flask_login import UserMixin
    from flask_migrate import Migrate
    from flask_sqlalchemy import SQLAlchemy

    from azure.batch.models import CloudTask, CloudJob, JobState
    from azure.storage.blob.models import BlobPermissions

    from morocco.util import get_logger
    from morocco.core import get_blob_storage_client
    from morocco.batch import get_metadata, get_job, list_tasks
    from morocco.exceptions import SecretError

    if 'MOROCCO_DATABASE_URI' not in os.environ:
        raise EnvironmentError('Missing environment MOROCCO_DATABASE_URI')

    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ['MOROCCO_DATABASE_URI']
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db = SQLAlchemy(app)

    class DbUser(db.Model, UserMixin):
        id = db.Column(db.String, primary_key=True)

        def __init__(self, user_id: str):
            self.id = user_id

        def __repr__(self):
            return '<User {}>'.format(self.id)

    class DbBuild(db.Model):
        id = db.Column(db.String, primary_key=True)
        creation_time = db.Column(db.DateTime)
        state = db.Column(db.String)
        tests = db.relationship('DbTestRun', backref='build', lazy='dynamic')

        view_type = namedtuple('BuildView', ['id', 'creation_time', 'state'])

        def __init__(self, job: CloudJob):
            self.id = job.id
            self.creation_time = job.creation_time
            self.update(job)

        def update(self, job: CloudJob):
            self.state = job.state.value

        def get_view(self):
            return self.view_type(self.id, str(self.creation_time), self.state)._asdict()

        def __repr__(self):
            return '<Build {}>'.format(self.id)

    class DbTestRun(db.Model):
        id = db.Column(db.String, primary_key=True)
        creation_time = db.Column(db.DateTime)
        live = db.Column(db.Boolean)
        total_tests = db.Column(db.Integer)
        failed_tests = db.Column(db.Integer)
        state = db.Column(db.String)

        build_id = db.Column(db.String, db.ForeignKey('db_build.id'))
        test_cases = db.relationship('DbTestCase', backref='test_run', lazy='dynamic')

        view_type = namedtuple('TestRunView', ['id', 'creation_time', 'state', 'total_tests', 'failed_tests'])

        def __init__(self, job: CloudJob):
            from morocco.batch import get_metadata

            self.id = job.id
            self.creation_time = job.creation_time
            self.build_id = get_metadata(job.metadata, 'build')
            self.live = get_metadata(job.metadata, 'live') == 'True'
            self.state = job.state.value

            self.total_tests = 0
            self.failed_tests = 0

        def __repr__(self):
            return '<TestRun {}>'.format(self.id)

        def get_pass_percentage(self) -> Union[int, None]:
            if not hasattr(self, '_pass_percentage'):
                all_tests = list(self.test_cases)
                total = len(all_tests)
                failed = len([t for t in all_tests if not t.passed])

                setattr(self, '_pass_percentage', int((total - failed) * 100 / total) if total else 0)

            return getattr(self, '_pass_percentage')

        def get_view(self):
            return self.view_type(self.id, str(self.creation_time), self.state, self.total_tests, self.failed_tests)

    class DbTestCase(db.Model):  # pylint: disable=too-many-instance-attributes, too-few-public-methods
        id = db.Column(db.String, primary_key=True)
        passed = db.Column(db.Boolean)
        output = db.Column(db.String)
        test_run_id = db.Column(db.String, db.ForeignKey('db_test_run.id'))
        module = db.Column(db.String)
        state = db.Column(db.String)
        test_method = db.Column(db.String)
        test_class = db.Column(db.String)
        test_full_name = db.Column(db.String)
        test_duration = db.Column(db.Integer)  # in seconds

        def __init__(self, test_task: CloudTask, db_test_run: DbTestRun):
            self.test_run = db_test_run

            self.id = self.get_full_name(test_task, db_test_run)
            self.passed = test_task.execution_info.exit_code == 0

            _, self.test_method, test_class_full = test_task.display_name.split(' ')
            self.test_class_full = test_class_full.strip('()')

            parts = self.test_class_full.split('.')
            self.test_class = parts[-1]
            try:
                if self.test_class_full.startswith('azure.cli.command_modules.'):
                    self.module = parts[3].upper()
                else:
                    self.module = parts[2].upper()
            except IndexError:
                self.module = 'N/A'

            self.test_full_name = '{}.{}'.format(self.test_class_full, self.test_method)
            self.test_duration = int((test_task.execution_info.end_time -
                                      test_task.execution_info.start_time).total_seconds())
            self.state = test_task.state.value

        @staticmethod
        def get_full_name(test_task: CloudTask, db_test_run: DbTestRun):
            return db_test_run.id + '.' + test_task.id

    class DbProjectSetting(db.Model):
        __tablename__ = 'db_projectsetting'
        id = db.Column(db.Integer, primary_key=True)
        name = db.Column(db.String)
        value = db.Column(db.String)

        def __repr__(self):
            return '<ProjectSetting(name={},value={})>'.format(self.name, self.value)

    def find_user(user_id: str):
        return DbUser.query.filter_by(id=user_id).first()

    def get_or_add_user(user_id: str):
        logger = get_logger('db')

        user = find_user(user_id)
        if not user:
            user = DbUser(user_id)
            db.session.add(user)
            db.session.commit()

            logger.info('create the user {} in the database.'.format(user_id))
        else:
            logger.info('find the user {} in the database.'.format(user_id))

        return user

    def update_build(job_id: str) -> None:
        get_or_add_build(job_id).update(get_job(job_id))
        db.session.commit()

    def get_or_add_test_run(job_id: str) -> DbTestRun:
        logger = get_logger('db')
        logger.info('get_or_add_test_run({})'.format(job_id))

        test_run = DbTestRun.query.filter_by(id=job_id).first()
        if not test_run:
            test_run = DbTestRun(get_job(job_id))
            db.session.add(test_run)
            db.session.commit()

        return test_run

    def update_test_run_protected(job_id: str, secret: str) -> Union[DbTestRun, None]:
        logger = get_logger('_db')
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
        from datetime import datetime, timedelta
        import requests

        logger = get_logger('_db')
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

    funcs = (find_user, get_or_add_user, update_build, get_or_add_test_run, update_test_run, update_test_run_protected)

    Migrate(app, db)

    return db, (DbUser, DbBuild, DbTestRun, DbTestCase, DbProjectSetting), funcs
