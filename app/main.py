import os
from flask import Flask
app = Flask(__name__)


@app.route('/')
def root():
    results = 'Morocco - An automation service runs on Azure Batch.\n'
    for key in os.environ:
        results += '{} = {}\n'.format(key, os.environ[key])
    
    return results
