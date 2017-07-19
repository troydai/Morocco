import os
import logging
import json

from flask import Flask, render_template, request, redirect, url_for
from flask_login import LoginManager, login_required

import morocco.batch
import morocco.auth
from morocco.util import get_logger


def init_db():
    from morocco.db import get_db
    get_db().create_all()


app = Flask(__name__)  # pylint: disable=invalid-name

morocco.auth.init_auth_config(app.config)
app.config['is_local_server'] = os.environ.get('MOROCCO_LOCAL_SERVER', False)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////tmp/test.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

if not app.secret_key:
    app.secret_key = 'session secret key for local testing'

login_manager = LoginManager()  # pylint: disable=invalid-name
login_manager.init_app(app)

if app.debug:
    logging.basicConfig(level=logging.DEBUG)

if not app.debug:
    app.config['PREFERRED_URL_SCHEME'] = 'https'

init_db()


@login_manager.user_loader
def load_user(user_id):
    from morocco.models import User
    from morocco.db import get_or_add_user

    get_logger('login').info('loading user {}'.format(user_id))
    get_or_add_user(user_id)
    return User(user_id)


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
    return morocco.auth.openid_login(app.config)


@app.route('/signin-callback', methods=['POST'])
def signin_callback():
    """Redirect from AAD sign in page"""
    return morocco.auth.openid_callback(app.config)


@app.route('/logout', methods=['POST'])
def logout():
    """Logout from both this application as well as Azure OpenID sign in."""
    return morocco.auth.openid_signout(app.config)


@app.route('/builds', methods=['GET'])
def builds():
    from morocco.db import DbBuild
    return render_template('builds.html', builds=DbBuild.query.order_by(DbBuild.creation_time.desc()).all())


@app.route('/build/<string:job_id>', methods=['GET'])
def build(job_id: str):
    from morocco.db import DbBuild
    return render_template('build.html', build=DbBuild.query.filter_by(id=job_id).first())


@app.route('/build', methods=['POST'])
@login_required
def post_build():
    from morocco.db import get_or_add_build
    from morocco.batch import create_build_job

    get_or_add_build(create_build_job(request.form['branch']))

    return redirect(url_for('builds'))


@app.route('/build/<string:job_id>', methods=['POST'])
@login_required
def refresh_build(job_id: str):
    from morocco.db import update_build
    update_build(job_id)

    return redirect(url_for('build', job_id=job_id))


@app.route('/tests', methods=['GET'])
def tests():
    from morocco.db import DbTestRun
    return render_template('tests.html', test_runs=DbTestRun.query.order_by(DbTestRun.creation_time.desc()).all())


@app.route('/test/<string:job_id>', methods=['GET'])
def test(job_id: str):
    from morocco.db import DbTestRun
    return render_template('test.html', test_run=DbTestRun.query.filter_by(id=job_id).first())


@app.route('/test', methods=['POST'])
@login_required
def post_test():
    from morocco.batch import create_test_job
    from morocco.db import get_or_add_test_run

    get_or_add_test_run(create_test_job(request.form['build_id'], request.form['live'] == 'true'))

    return redirect(url_for('tests'))


@app.route('/test/<string:job_id>', methods=['POST'])
@login_required
def refresh_test(job_id: str):
    from morocco.db import update_test_run

    update_test_run(job_id)

    return redirect(url_for('test', job_id=job_id))


@app.route('/admin', methods=['GET'])
@login_required
def get_admin():
    return render_template('admin.html')


@app.route('/api/build/<string:job_id>', methods=['PUT'])
def put_build(job_id: str):
    from morocco.db import update_build_protected
    from morocco.exceptions import SecretError

    try:
        db_build = update_build_protected(job_id, request.form.get('secret'))

        if not db_build:
            return 'Not found', 404

        return json.dumps(db_build.get_view())

    except SecretError:
        return 'Invalid secret', 403


@app.route('/api/test/<string:job_id>', methods=['PUT'])
def put_test(job_id: str):
    from morocco.db import update_test_run_protected
    from morocco.exceptions import SecretError

    try:
        test_run = update_test_run_protected(job_id, request.form.get('secret'))

        if not test_run:
            return 'Not found', 404

        return json.dumps(test_run.get_view())

    except SecretError:
        return 'Invalid secret', 403


@app.route('/sync_all', methods=['POST'])
@login_required
def sync_all():
    """Sync all batch builds data into the database"""
    from morocco.db.actions import sync_all as sync_all_op
    sync_all_op()
    return redirect(url_for('index'))
