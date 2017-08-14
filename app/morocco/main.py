# pylint: disable=invalid-name

import logging
import os
from collections import namedtuple
from datetime import datetime, timedelta
from typing import Union

from flask import Flask, render_template, request, redirect, url_for
from flask_login import LoginManager, login_required, UserMixin
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

from morocco.core import load_config
from morocco.util import get_logger
from morocco.batch import get_job, list_tasks
from morocco.core import get_blob_storage_client

from azure.batch.models import CloudJob, CloudTask, JobState
from azure.storage.blob.models import BlobPermissions

app = Flask(__name__)

if not app.debug:
    app.config['PREFERRED_URL_SCHEME'] = 'https'

if app.debug:
    logging.basicConfig(level=logging.DEBUG)

if not app.secret_key:
    app.secret_key = os.environ.get('MOROCCO_SECRET_KEY', 'session secret key for local testing')

# ======================================================================================================================

if 'MOROCCO_DATABASE_URI' not in os.environ:
    raise EnvironmentError('Missing environment MOROCCO_DATABASE_URI')

app.config['SQLALCHEMY_DATABASE_URI'] = os.environ['MOROCCO_DATABASE_URI']
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
migrate = Migrate(app, db)


class DbUser(db.Model, UserMixin):
    id = db.Column(db.String, primary_key=True)
    role = db.Column(db.String)

    def __init__(self, user_id: str):
        self.id = user_id

    def __repr__(self):
        return '<User {}: {}>'.format(self.id, self.role or 'N/A')

    def is_admin(self) -> bool:
        return self.is_authenticated and self.role == 'admin'


class DbBuild(db.Model):
    id = db.Column(db.String, primary_key=True)
    creation_time = db.Column(db.DateTime)
    state = db.Column(db.String)
    tests = db.relationship('DbTestRun', backref='build', lazy='dynamic', cascade='delete')

    commit_author = db.Column(db.String)
    commit_message = db.Column(db.String)
    commit_date = db.Column(db.DateTime)
    commit_url = db.Column(db.String)
    build_download_url = db.Column(db.String)
    suppressed = db.Column(db.Boolean)

    view_type = namedtuple('BuildView', ['id', 'creation_time', 'state'])

    def __init__(self, job: CloudJob = None, commit: dict = None):
        self.state = 'init'
        self.creation_time = datetime.utcnow()

        if job:
            self.id = job.id
            self.state = job.state.value
        elif commit:
            self.id = commit['sha']
            self.update_commit(commit)

    def update_commit(self, commit):
        self.commit_author = commit['commit']['author']['name']
        self.commit_date = datetime.strptime(commit['commit']['committer']['date'], '%Y-%m-%dT%H:%M:%SZ')
        self.commit_message = commit['commit']['message']
        self.commit_url = commit['html_url']

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
    test_cases = db.relationship('DbTestCase', backref='test_run', lazy='dynamic', cascade='delete')

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


class DbAccessKey(db.Model):
    name = db.Column(db.String, primary_key=True)
    key1 = db.Column(db.String)
    key2 = db.Column(db.String)
    remark = db.Column(db.String)

    def __init__(self, name: str, remark: str):
        self.name = name
        self.remark = remark
        self.shuffle()

    def shuffle(self):
        import base64

        self.key1 = base64.b64encode(os.urandom(64)).decode('utf-8')
        self.key2 = base64.b64encode(os.urandom(64)).decode('utf-8')


class DbWebhookEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    source = db.Column(db.String)
    content = db.Column(db.String)
    signature = db.Column(db.String)

    def __init__(self, source: str, content: str, signature: str = None):
        self.source = source
        self.content = content
        self.signature = signature


# ======================================================================================================================

load_config(app, DbProjectSetting)

login_manager = LoginManager()  # pylint: disable=invalid-name
login_manager.init_app(app)
login_manager.user_loader(lambda user_id: DbUser.query.filter_by(id=user_id).first())


@login_manager.unauthorized_handler
def unauthorized_handler():
    logger = get_logger('auth')
    logger.info('Unauthorized request to {}. Redirect to login page.'.format(request.path))

    return redirect(url_for('login', request_uri=request.path))


@app.before_request
def redirect_https():
    if 'X-Arr-Ssl' not in request.headers and not app.config['is_local_server']:
        redirect_url = request.url.replace('http', 'https')
        return redirect(redirect_url)


@app.route('/', methods=['GET'])
def index():
    byline = 'Morocco - An automation service runs on Azure Batch.\n'
    return render_template('index.html', byline=byline, title='Azure CLI')


@app.route('/login', methods=['GET'])
def login():
    """Redirect user agent to Azure AD sign-in page"""
    import morocco.auth
    return morocco.auth.openid_login()


@app.route('/signin-callback', methods=['POST'])
def signin_callback():
    """Redirect from AAD sign in page"""

    def get_or_add_user(user_id: str):
        logger = get_logger('db')

        user = DbUser.query.filter_by(id=user_id).first()
        if not user:
            user = DbUser(user_id)
            db.session.add(user)
            db.session.commit()

            logger.info('create the user {} in the database.'.format(user_id))
        else:
            logger.info('find the user {} in the database.'.format(user_id))

        return user

    import morocco.auth
    return morocco.auth.openid_callback(get_or_add_user)


@app.route('/logout', methods=['POST'])
def logout():
    """Logout from both this application as well as Azure OpenID sign in."""
    import morocco.auth
    return morocco.auth.openid_logout()


@app.route('/builds', methods=['GET'])
def get_builds():
    query = DbBuild.query
    if request.args.get('include_suppressed') != 'true':
        query = query.filter_by(suppressed=False)

    db_builds = query.order_by(DbBuild.commit_date.desc()).all()
    return render_template('builds.html', builds=db_builds, title='Snapshots')


@app.route('/builds', methods=['POST'])
@login_required
def sync_builds():
    from morocco.core import get_source_control_commits, sync_build
    from flask_login import current_user
    if not current_user.is_authenticated or not current_user.is_admin():
        return 'Forbidden', 403

    build_commits = get_source_control_commits()

    for commit in build_commits:
        sync_build(commit=commit, create_job=True)

    return redirect(url_for('get_builds'))


@app.route('/build/<string:sha>', methods=['GET'])
def build(sha: str):
    build_record = DbBuild.query.filter_by(id=sha).first()
    return render_template('build.html', build=build_record, title='Snapshot')


@app.route('/build/<string:sha>', methods=['POST'])
@login_required
def post_build(sha: str):
    action = request.form.get('action')
    if action == 'refresh' or action == 'rebuild':
        from morocco.core import sync_build
        sync_build(sha=sha, create_job=(action == 'rebuild'))
    elif action == 'suppress':
        build_record = DbBuild.query.filter_by(id=sha).one_or_none()
        if not build_record:
            return 'Build not found', 404
        build_record.suppressed = True
        db.session.commit()
    else:
        return 'Unknown action {}'.format(action or 'None'), 400

    if 'redirect' in request.form:
        return redirect(request.form['redirect'])
    else:
        return redirect(url_for('build', sha=sha))


@app.route('/tests', methods=['GET'])
def tests():
    return render_template('tests.html', test_runs=DbTestRun.query.order_by(DbTestRun.creation_time.desc()).all(),
                           title='Test Runs')


@app.route('/test/<string:job_id>', methods=['GET'])
def test(job_id: str):
    return render_template('test.html', test_run=DbTestRun.query.filter_by(id=job_id).first(),
                           title='Test Run')


@app.route('/test', methods=['POST'])
@login_required
def post_test():
    from morocco.batch import create_test_job

    job_id = create_test_job(request.form['build_id'], request.form['live'] == 'true')
    test_run = DbTestRun.query.filter_by(id=job_id).first()
    if not test_run:
        test_run = DbTestRun(get_job(job_id))
        db.session.add(test_run)
        db.session.commit()

    return redirect(url_for('tests'))


@app.route('/test/<string:job_id>', methods=['POST'])
@login_required
def refresh_test(job_id: str):
    import requests
    storage = get_blob_storage_client()

    test_run = DbTestRun.query.filter_by(id=job_id).first()
    if not test_run:
        return "Test run job not found", 404

    test_run_job = get_job(job_id)
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

    return redirect(url_for('test', job_id=job_id))


@app.route('/delete_test_run', methods=['POST'])
@login_required
def delete_test_run():
    test_run_id = request.form.get('test_run_id')
    if not test_run_id:
        return "Missing test run ID", 400

    test_run = DbTestRun.query.filter_by(id=test_run_id).one_or_none()
    if test_run:
        db.session.delete(test_run)
        db.session.commit()
        return redirect(url_for('tests'))
    else:
        return "Test run {} not found".format(test_run_id), 404


@app.route('/admin', methods=['GET'])
@login_required
def get_admin():
    from flask_login import current_user
    if not current_user.is_admin():
        return 'Check your privilege, Bro.', 403

    keys = DbAccessKey.query.all()
    users = DbUser.query.all()

    return render_template('admin.html', title='Admin', keys=keys, users=users)


@app.route('/admin/access_key', methods=['POST'])
@login_required
def post_access_key():
    from datetime import datetime
    from flask_login import current_user
    if not current_user.is_admin():
        return 'Check your privilege, Bro.', 403

    action = request.form.get('action')
    if action == 'new':
        remark = request.form.get('remark') or 'created on {}'.format(
            datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC'))
        db.session.add(DbAccessKey(request.form['name'], remark))
        db.session.commit()
    elif action == 'delete':
        key = DbAccessKey.query.filter_by(name=request.form['name']).one_or_none()
        db.session.delete(key)
        db.session.commit()

    return redirect(url_for('get_admin'))


@app.route('/api/build', methods=['POST'])
def post_api_build():
    from morocco.auth.util import validate_github_webhook
    from morocco.core.operations import on_github_push, on_batch_callback

    if request.headers.get('X-GitHub-Event') == 'push':
        # to validate it in the future
        event = DbWebhookEvent(source='github', content=request.data.decode('utf-8'),
                               signature=request.headers.get('X-Hub-Signature'))
        db.session.add(event)
        db.session.commit()

        client_id = request.args.get('client_id')
        if not client_id:
            return 'Forbidden', 401

        key = DbAccessKey.query.filter_by(name=client_id).one_or_none()
        if not key:
            # unknown client
            return 'Forbidden', 401

        if not validate_github_webhook(request, key.key1):
            return 'Invalid request', 403

        msg = on_github_push(request.json)

        return msg, 200
    elif request.headers.get('X-Batch-Event') == 'build.finished':
        event = DbWebhookEvent(source='batch', content=request.data.decode('utf-8'))
        db.session.add(event)
        db.session.commit()

        # the callback's credential is validated in on_batch_callback
        msg, status = on_batch_callback(request, DbBuild)
        return msg, status

    return 'Forbidden', 401
