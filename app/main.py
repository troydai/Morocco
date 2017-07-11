import os
import json
from urllib.parse import urlparse
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

@app.route('/sec')
def sec():
    url = urlparse(request.host_url)
    return url.scheme

@app.route('/headers')
def headers():
    return str(list(h for h in request.headers))
