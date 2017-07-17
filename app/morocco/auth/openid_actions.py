from flask import Config
from morocco.models import User


def openid_signout(config: Config, post_logout_redirect_uri: str = None):
    from urllib.parse import urlencode
    from flask import url_for, redirect
    from flask_login import logout_user

    logout_user()

    redirect_uri = post_logout_redirect_uri or url_for('index', _external=True)
    sign_out_uri = config['auth_signout_uri']

    return redirect('{}?{}'.format(sign_out_uri, urlencode({'post_logout_redirect_uri': redirect_uri})))


def openid_callback(config: Config):
    from flask import redirect, request, render_template, url_for
    from flask_login import login_user

    if 'error' in request.form:
        return render_template('error.html', error='Fail to sign in. Error: {}. Description: {}.'.format(
            request.form['error'], request.form['error_description']))

    if 'id_token' not in request.form:
        return render_template('error.html', error='Fail to sign in. Neither id_token nor error was sent.'
                                                   'The authorization server did not act correctly.')

    id_token, redirect_uri = request.form['id_token'], request.form.get('state', None) or url_for('index')

    try:
        public_key_mgr = config['auth_public_key_manager']
        payload = public_key_mgr.get_id_token_payload(id_token)
    except Exception:  # pylint: disable=broad-except
        return render_template('error.html', error='Fail to validate id_token.')

    user = User(user_id=payload['upn'])
    login_user(user, remember=True, fresh=True)

    return redirect(redirect_uri)


def openid_login(config: Config):
    from flask import request, url_for, render_template
    from urllib.parse import urlencode
    from uuid import uuid4

    redirect_uri = request.args.get('redirect_uri') or url_for('index')

    kwargs = {'_external': True}
    if not config['is_local_server']:
        kwargs['_scheme'] = 'https'

    azure_signin_uri = '{}?{}'.format(config['auth_authorization_endpoint'],
                                      urlencode({
                                          'tenant': config['auth_tenant'],
                                          'client_id': config['auth_client_id'],
                                          'response_type': 'id_token',
                                          'scope': 'openid',
                                          'nonce': str(uuid4()),
                                          'redirect_uri': url_for('signin_callback', **kwargs),
                                          'response_mode': 'form_post',
                                          'state': redirect_uri
                                      }))

    return render_template('login.html', azure_signin_uri=azure_signin_uri)
