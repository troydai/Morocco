import os
from flask import Flask, render_template, request, redirect, url_for
from .util import get_logger

app = Flask(__name__)  # pylint: disable=invalid-name


@app.before_request
def redirect_https():
    if 'X-Arr-Ssl' not in request.headers and os.environ.get('FLASK_DEBUG') != '1':
        return redirect(url_for('index', _external=True, _scheme='https'))


@app.route('/')
def index():
    byline = 'Morocco - An automation service runs on Azure Batch.\n'
    return render_template('index.html', byline=byline)


@app.route('/builds', methods=['GET'])
def list_builds():
    from collections import namedtuple
    from typing import NamedTuple
    from .models import get_batch_client
    from .util import get_time_str
    from azure.batch.models import JobListOptions, CloudJob

    def _transform(job: CloudJob) -> NamedTuple:
        build_job_view = namedtuple('build_job_view', ['id', 'state', 'start_time', 'end_time', 'end'])
        return build_job_view(job.id,
                              job.state.value,
                              get_time_str(job.execution_info.start_time),
                              get_time_str(job.execution_info.end_time),
                              job.execution_info.terminate_reason)

    batch_client = get_batch_client()
    build_jobs = batch_client.job.list(JobListOptions('startswith(id,\'build\')'))
    builds = [_transform(job) for job in build_jobs]

    return render_template('builds.html', builds=builds)


@app.route('/api/build', methods=['POST'])
def create_build():
    from .actions import create_build_job
    from .models import (get_batch_client, get_blob_storage_client, get_source_control_info)

    build_job_id = create_build_job(get_batch_client(), get_blob_storage_client(), get_source_control_info())
    return build_job_id


@app.route('/api/test', methods=['POST'])
def create_test_job():
    from .actions import create_test_job as start_test
    logger = get_logger()
    test_job_id = start_test(build_id=request.form['build_job'], run_live='live' in request.form)
    logger.info('Create new test job %s', test_job_id)
    return redirect(url_for('show_job', job_id=test_job_id))


@app.route('/job', methods=['GET'])
def show_job():
    from collections import namedtuple
    from .models import get_batch_client
    from .util import get_time_str
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


@app.route('/headers')
def headers():
    return str(list(h for h in request.headers))
