# pylint: disable=invalid-name

import json
import logging

from flask import Flask, render_template, request, redirect, url_for
from flask_login import LoginManager, login_required

from morocco.core import init_database, load_config
from morocco.util import get_logger

app = Flask(__name__)
db, models, funcs = init_database(app)
DbUser, DbBuild, DbTestRun, DbTestCase, DbProjectSetting, DbAccessKey, DbWebhookEvent = models

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
    return render_template('index.html', byline=byline, title='Azure CLI')


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

    get_or_add_test_run(create_test_job(request.form['build_id'], request.form['live'] == 'true'))

    return redirect(url_for('tests'))


@app.route('/test/<string:job_id>', methods=['POST'])
@login_required
def refresh_test(job_id: str):
    update_test_run(job_id)

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
