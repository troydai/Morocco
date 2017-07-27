# pylint: disable=invalid-name

import json
import logging

from flask import Flask, render_template, request, redirect, url_for
from flask_login import LoginManager, login_required

from morocco.batch import get_metadata
from morocco.core import init_database, load_config, get_batch_client
from morocco.util import get_logger

app = Flask(__name__)
db, models, funcs = init_database(app)
DbUser, DbBuild, DbTestRun, DbTestCase, DbProjectSetting = models

load_config(app, DbProjectSetting)

(find_user, get_or_add_user, get_or_add_test_run, update_test_run, update_test_run_protected) = funcs

if not app.debug:
    app.config['PREFERRED_URL_SCHEME'] = 'https'

if app.debug:
    logging.basicConfig(level=logging.DEBUG)

if not app.secret_key:
    app.secret_key = 'session secret key for local testing'

login_manager = LoginManager()  # pylint: disable=invalid-name
login_manager.init_app(app)
login_manager.user_loader(find_user)


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
    return render_template('index.html', byline=byline)


@app.route('/login', methods=['GET'])
def login():
    """Redirect user agent to Azure AD sign-in page"""
    import morocco.auth
    return morocco.auth.openid_login()


@app.route('/signin-callback', methods=['POST'])
def signin_callback():
    """Redirect from AAD sign in page"""
    import morocco.auth
    return morocco.auth.openid_callback(get_or_add_user)


@app.route('/logout', methods=['POST'])
def logout():
    """Logout from both this application as well as Azure OpenID sign in."""
    import morocco.auth
    return morocco.auth.openid_logout()


@app.route('/builds', methods=['GET'])
def builds():
    return render_template('builds.html', builds=DbBuild.query.order_by(DbBuild.creation_time.desc()).all())


@app.route('/build/<string:sha>', methods=['GET'])
def build(sha: str):
    return render_template('build.html', build=DbBuild.query.filter_by(id=sha).first())


@app.route('/build', methods=['POST'])
@login_required
def post_build():
    import requests
    from morocco.batch import create_build_job
    from morocco.core import get_source_control_info

    git_url = get_source_control_info().url
    git_url = git_url.replace('https://github.com', 'https://api.github.com/repos')[:-4] + '/commits'
    response = requests.get(git_url)
    commit_sha = response.json()[0]['sha']

    build_record = DbBuild.query.filter_by(id=commit_sha).one_or_none()
    if not build_record:
        db.session.add(DbBuild(create_build_job(commit_sha)))
        db.session.commit()

    return redirect(url_for('build', sha=commit_sha))


@app.route('/build/<string:sha>', methods=['POST'])
@login_required
def refresh_build(sha: str):
    build_record = DbBuild.query.filter_by(id=sha).first()
    if not build_record:
        return 'Not found', 404

    batch_client = get_batch_client()
    job = batch_client.job.get(sha)
    if not job:
        return 'Cloud job is not found', 400

    build_task = batch_client.task.get(job_id=sha, task_id='build')
    if not build_task:
        return 'Cloud task for the build is not found', 400

    build_record.state = build_task.state.value
    db.session.commit()

    return redirect(url_for('build', sha=sha))


@app.route('/tests', methods=['GET'])
def tests():
    return render_template('tests.html', test_runs=DbTestRun.query.order_by(DbTestRun.creation_time.desc()).all())


@app.route('/test/<string:job_id>', methods=['GET'])
def test(job_id: str):
    return render_template('test.html', test_run=DbTestRun.query.filter_by(id=job_id).first())


@app.route('/test', methods=['POST'])
@login_required
def post_test():
    from morocco.batch import create_test_job

    get_or_add_test_run(create_test_job(request.form['build_id'], request.form['live'] == 'true'))

    return redirect(url_for('tests'))


@app.route('/test/<string:job_id>', methods=['POST'])
@login_required
def refresh_test(job_id: str):
    update_test_run(job_id)

    return redirect(url_for('test', job_id=job_id))


@app.route('/admin', methods=['GET'])
@login_required
def get_admin():
    return render_template('admin.html')


@app.route('/api/build/<string:sha>', methods=['PUT'])
def put_build(sha: str):
    secret = request.form.get('secret')
    if not secret:
        return 'Missing secret', 403

    build_record = DbBuild.query.filter_by(id=sha).first()
    if not build_record:
        return 'Not found', 404

    batch_client = get_batch_client()
    job = batch_client.job.get(sha)
    if not job:
        return 'Cloud job is not found', 400

    expect_secret = get_metadata(job.metadata, 'secret')
    if expect_secret != secret:
        return 'Invalid secret', 403

    build_task = batch_client.task.get(job_id=sha, task_id='build')
    if not build_task:
        return 'Cloud task for the build is not found', 400

    build_record.state = build_task.state.value
    db.session.commit()

    return json.dumps(build_record.get_view())


@app.route('/api/test/<string:job_id>', methods=['PUT'])
def put_test(job_id: str):
    from morocco.exceptions import SecretError

    try:
        test_run = update_test_run_protected(job_id, request.form.get('secret'))

        if not test_run:
            return 'Not found', 404

        return json.dumps(test_run.get_view())

    except SecretError:
        return 'Invalid secret', 403
