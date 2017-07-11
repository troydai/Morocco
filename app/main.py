import os
from flask import Flask, render_template
app = Flask(__name__)


@app.route('/')
def index():
    byline = 'Morocco - An automation service runs on Azure Batch.\n'
    return render_template('index.html', byline=byline)
