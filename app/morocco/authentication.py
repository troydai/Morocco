import flask_login
from .application import app
from .models import DbUser

login_manager = flask_login.LoginManager()  # pylint: disable=invalid-name
login_manager.init_app(app)
login_manager.user_loader(lambda user_id: DbUser.query.filter_by(id=user_id).first())
login_required = flask_login.login_required


@login_manager.unauthorized_handler
def unauthorized_handler():
    from flask import redirect, request, url_for

    return redirect(url_for('login', request_uri=request.path))


@app.before_request
def redirect_https():
    from flask import redirect, request

    if 'X-Arr-Ssl' not in request.headers and not app.config['is_local_server']:
        redirect_url = request.url.replace('http', 'https')
        return redirect(redirect_url)


@app.route('/', methods=['GET'])
def index():
    from flask import render_template

    byline = 'Morocco - An automation service runs on Azure Batch.\n'
    return render_template('index.html', byline=byline, title='Azure CLI')


@app.route('/login', methods=['GET'])
def login():
    """Redirect user agent to Azure AD sign-in page"""
    import morocco.auth
    return morocco.auth.openid_login()


@app.route('/signin-callback', methods=['POST'])
def signin_callback():
    """Redirect from AAD sign in page"""

    def get_or_add_user(user_id: str):
        from .application import db
        from .models import DbUser

        user = DbUser.query.filter_by(id=user_id).first()
        if not user:
            user = DbUser(user_id)
            db.session.add(user)
            db.session.commit()

        return user

    import morocco.auth
    return morocco.auth.openid_callback(get_or_add_user)


@app.route('/logout', methods=['POST'])
def logout():
    """Logout from both this application as well as Azure OpenID sign in."""
    import morocco.auth
    return morocco.auth.openid_logout()

