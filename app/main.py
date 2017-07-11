import os
import json
from urllib.parse import urlparse
from flask import Flask, render_template, request
app = Flask(__name__)


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
