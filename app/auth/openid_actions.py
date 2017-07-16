from ..models import User


def openid_signout(post_logout_redirect_uri: str = None):
    from urllib.parse import urlencode
    from flask import url_for, redirect
    from flask_login import logout_user
    from ..main import app

    logout_user()

    redirect_uri = post_logout_redirect_uri or url_for('index', _external=True)
    sign_out_uri = app.config['auth_signout_uri']

    return redirect('{}?{}'.format(sign_out_uri, urlencode({'post_logout_redirect_uri': redirect_uri})))


def openid_callback():
    from flask import redirect, request, render_template, url_for
    from flask_login import login_user
    from .jwt import AzureJWS

    if 'error' in request.form:
        return render_template('error.html', error='Fail to sign in. Error: {}. Description: {}.'.format(
            request.form['error'], request.form['error_description']))

    if 'id_token' not in request.form:
        return render_template('error.html', error='Fail to sign in. Neither id_token nor error was sent.'
                                                   'The authorization server did not act correctly.')

    id_token, redirect_uri = request.form['id_token'], request.form.get('state', None) or url_for('index')

    try:
        jws = AzureJWS(id_token)
    except Exception:  # pylint: too-broad-except
        return render_template('error.html', error='Fail to validate id_token.')

    user = User(user_id=jws.payload['upn'])
    login_user(user, remember=True, fresh=True)

    return redirect(redirect_uri)


def openid_login():
    from flask import request, url_for, render_template
    from urllib.parse import urlencode
    from uuid import uuid4
    from ..main import app

    redirect_uri = request.args.get('redirect_uri') or url_for('index')

    azure_signin_uri = '{}?{}'.format(app.config['auth_authorization_endpoint'],
                                      urlencode({
                                          'tenant': app.config['auth_tenant'],
                                          'client_id': app.config['auth_client_id'],
                                          'response_type': 'id_token',
                                          'scope': 'openid',
                                          'nonce': str(uuid4()),
                                          'redirect_uri': url_for('signin_callback', _external=True),
                                          'response_mode': 'form_post',
                                          'state': redirect_uri
                                      }))

    return render_template('login.html', azure_signin_uri=azure_signin_uri)