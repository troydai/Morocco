import os
from flask import Flask, render_template, request, redirect, url_for

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
        build_job_view = namedtuple('BuildJob', ['id', 'state', 'start_time', 'end_time', 'end'])
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
    from .models import (get_batch_client, get_blob_storage_client, get_batch_pools_from_file, get_source_control_info)

    build_job_id = create_build_job(get_batch_client(), get_blob_storage_client(), get_source_control_info(),
                                    get_batch_pools_from_file())
    return build_job_id


@app.route('/api/test', methods=['POST'])
def create_test_job():
    pass


@app.route('/headers')
def headers():
    return str(list(h for h in request.headers))
