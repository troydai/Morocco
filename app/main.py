from flask import Flask
app = Flask(__name__)


@app.route('/')
def root():
    return 'Morocco - An automation service runs on Azure Batch.'
