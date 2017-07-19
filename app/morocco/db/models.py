from typing import Union
from collections import namedtuple

from flask_sqlalchemy import SQLAlchemy
from azure.batch.models import CloudTask, CloudJob


# SQLAlchemy is banana
# pylint: disable=no-member, invalid-name


def create_db() -> SQLAlchemy:
    from morocco.main import app
    return SQLAlchemy(app)


db = create_db()


def get_db() -> SQLAlchemy:
    return db


class DbUser(db.Model):  # pylint: disable=too-few-public-methods
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
