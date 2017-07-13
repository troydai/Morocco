import os
from flask import Flask, render_template, request, redirect, url_for

app = Flask(__name__)


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
    from .models import get_batch_client
    from .util import get_time_str
    from collections import namedtuple

    batch_client = get_batch_client()

    BuildJob = namedtuple('BuildJob', ['id', 'state', 'start_time', 'end_time', 'end'])
    builds = [BuildJob(b.id, b.state.value, get_time_str(b.execution_info.start_time),
                       get_time_str(b.execution_info.end_time),
                       b.execution_info.terminate_reason) for b in batch_client.job.list() if b.id.startswith('build')]

    return render_template('builds.html', builds=builds)


@app.route('/api/build', methods=['POST'])
def create_build():
    from .actions import create_build_job
    from .models import (get_batch_client, get_blob_storage_client, get_batch_pools_from_file, get_source_control_info)

    build_job_id = create_build_job(get_batch_client(), get_blob_storage_client(), get_source_control_info(),
                                    get_batch_pools_from_file())
    return build_job_id


@app.route('/headers')
def headers():
    return str(list(h for h in request.headers))
