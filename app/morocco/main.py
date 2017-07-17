import os
import logging
from flask import Flask, render_template, request, redirect, url_for
from flask_login import LoginManager, login_required
from morocco.auth import init_auth_config
from morocco.util import get_logger

app = Flask(__name__)  # pylint: disable=invalid-name
init_auth_config(app.config)

if not app.secret_key:
    app.secret_key = 'session secret key for local testing'

login_manager = LoginManager()  # pylint: disable=invalid-name
login_manager.init_app(app)

if app.debug:
    logging.basicConfig(level=logging.DEBUG)


@login_manager.user_loader
def load_user(user_id):
    from morocco.models import User
    get_logger('login').info('loading user {}'.format(user_id))
    return User(user_id)


@login_manager.unauthorized_handler
def unauthorized_handler():
    logger = get_logger('auth')
    logger.info('Unauthorized request to {}. Redirect to login page.'.format(request.path))

    return redirect(url_for('login', request_uri=request.path))


@app.before_request
def redirect_https():
    if 'X-Arr-Ssl' not in request.headers and os.environ.get('FLASK_DEBUG') != '1':
        return redirect(url_for('index', _external=True, _scheme='https'))


@app.route('/', methods=['GET'])
def index():
    byline = 'Morocco - An automation service runs on Azure Batch.\n'
    return render_template('index.html', byline=byline)


@app.route('/login', methods=['GET'])
def login():
    """Redirect user agent to Azure AD sign-in page"""
    from morocco.auth import openid_login
    return openid_login()


@app.route('/signin-callback', methods=['POST'])
def signin_callback():
    """Redirect from AAD sign in page"""
    from morocco.auth import openid_callback
    return openid_callback()


@app.route('/logout', methods=['POST'])
def logout():
    """Logout from both this application as well as Azure OpenID sign in."""
    from morocco.auth import openid_signout
    return openid_signout()


@app.route('/builds', methods=['GET'])
@login_required
def get_builds():
    from collections import namedtuple
    from typing import NamedTuple
    from morocco.models import get_batch_client
    from morocco.util import get_time_str
    from azure.batch.models import JobListOptions, CloudJob

    def _transform(job: CloudJob) -> NamedTuple:
        build_job_view = namedtuple('build_job_view', ['id', 'state', 'start_time', 'end_time', 'end'])
        return build_job_view(job.id,
                              job.state.value,
                              get_time_str(job.execution_info.start_time),
                              get_time_str(job.execution_info.end_time) if job.execution_info.end_time else 'N/A',
                              job.execution_info.terminate_reason)

    batch_client = get_batch_client()
    build_jobs = batch_client.job.list(JobListOptions('startswith(id,\'build\')'))
    builds = [_transform(job) for job in build_jobs]

    return render_template('builds.html', builds=builds)


@app.route('/api/build', methods=['POST'])
def post_build():
    from morocco.operations import create_build_job

    build_job_id = create_build_job(request.form['branch'])

    for each in request.headers.get('Accept').split(','):
        if each in ('text/html', 'application/xhtml+xml'):
            return redirect(url_for('get_builds'))

    import json
    return json.dumps({'job_id': build_job_id})


@app.route('/api/test', methods=['POST'])
@login_required
def create_test_job():
    from morocco.actions import create_test_job as start_test
    logger = get_logger()
    test_job_id = start_test(build_id=request.form['build_job'], run_live='live' in request.form)
    logger.info('Create new test job %s', test_job_id)
    return redirect(url_for('show_job', job_id=test_job_id))


@app.route('/job', methods=['GET'])
@login_required
def show_job():
    from collections import namedtuple
    from morocco.models import get_batch_client
    from morocco.util import get_time_str
    from azure.batch.models import BatchErrorException, TaskState

    job_view = namedtuple('job_view', ['id', 'description', 'state', 'creation_time', 'last_modified', 'total_tasks',
                                       'running_tasks', 'completed_tasks'])
    job_id = request.args.get('job_id')

    try:
        job = get_batch_client().job.get(job_id)
        tasks = list(get_batch_client().task.list(job_id))

        return render_template('job.html', job=job_view(
            job.id,
            job.display_name,
            job.state,
            get_time_str(job.creation_time),
            get_time_str(job.last_modified),
            len(tasks),
            len([t for t in tasks if t.state == TaskState.running]),
            len([t for t in tasks if t.state == TaskState.completed])
        ))
    except BatchErrorException:
        return render_template('error.html', error='Job {} is not found.'.format(job_id))
