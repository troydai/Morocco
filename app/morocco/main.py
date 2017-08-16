# pylint: disable=invalid-name

import os
from datetime import datetime, timedelta

from flask import render_template, request, redirect, url_for

from morocco.batch import get_job, list_tasks
from morocco.core import get_blob_storage_client

from azure.batch.models import JobState
from azure.storage.blob.models import BlobPermissions

from .application import db, app, load_config_from_db
from .models import DbUser, DbBuild, DbTestRun, DbTestCase, DbWebhookEvent, DbAccessKey
from .view_models import Snapshot
from .authentication import login_required

load_config_from_db()


@app.route('/builds', methods=['GET'])
def builds():
    query = DbBuild.query
    if request.args.get('include_suppressed') != 'true':
        query = query.filter_by(suppressed=False)

    view_models = (Snapshot(b) for b in query.order_by(DbBuild.commit_date.desc()).all())
    return render_template('builds.html', models=view_models, title='Snapshots')


@app.route('/build/<string:sha>', methods=['GET'])
def build(sha: str):
    view_model = Snapshot(DbBuild.query.filter_by(id=sha).first())
    return render_template('build.html', model=view_model, title='Snapshot')


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

    return redirect(url_for('builds'))


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
            event.remark = 'missing client id'
            db.session.commit()
            return 'Forbidden', 401

        key = DbAccessKey.query.filter_by(name=client_id).one_or_none()
        if not key:
            # unknown client
            event.remark = 'access key not found in db'
            db.session.commit()
            return 'Forbidden', 401

        if not validate_github_webhook(request, key.key1):
            event.remark = 'github signature invalidate'
            db.session.commit()
            return 'Invalid request', 403

        msg = on_github_push(request.json)

        event.remark = 'success: {}'.format(msg)
        db.session.commit()

        return msg, 200
    elif request.headers.get('X-Batch-Event') == 'build.finished':
        event = DbWebhookEvent(source='batch', content=request.data.decode('utf-8'))
        db.session.add(event)
        db.session.commit()

        # the callback's credential is validated in on_batch_callback
        msg, status = on_batch_callback(request, DbBuild)

        event.remark = 'Result: {} -> {}'.format(msg, status)
        db.session.commit()

        return msg, status

    return 'Forbidden', 401
