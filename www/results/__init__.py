import logging.handlers
import MySQLdb
from flask import Flask, g
from . import index

app = Flask(__name__, instance_relative_config=True)
app.config.from_pyfile('imp-results.cfg')

if not app.debug and 'MAIL_SERVER' in app.config:
    mail_handler = logging.handlers.SMTPHandler(
        mailhost=(app.config['MAIL_SERVER'], app.config['MAIL_PORT']),
        fromaddr='no-reply@' + app.config['MAIL_SERVER'],
        toaddrs=app.config['ADMINS'], subject='IMP nightly build page error')
    mail_handler.setLevel(logging.ERROR)
    app.logger.addHandler(mail_handler)


def _connect_db():
    conn = MySQLdb.connect(host=app.config['HOST'], user=app.config['USER'],
                           passwd=app.config['PASSWORD'],
                           db=app.config['DATABASE'])
    return conn


def get_db():
    """Open a new database connection if necessary"""
    if not hasattr(g, 'db_conn'):
        g.db_conn = _connect_db()
    return g.db_conn


@app.teardown_appcontext
def close_db(error):
    if hasattr(g, 'db_conn'):
        g.db_conn.close()


# The old CGI script didn't use routing and worked entirely with
# request parameters. For compatibility, do the same thing here.
@app.route('/')
def summary():
    p = index.TestPage(get_db(), app.config)
    return p.display()


@app.route('/platform/<int:plat>')
def platform(plat):
    p = index.TestPage(get_db(), app.config, platform=plat,
                       page='platform')
    return p.display()


@app.route('/comp/<int:comp>')
def component(comp):
    p = index.TestPage(get_db(), app.config, component=comp)
    return p.display()


@app.route('/all-fail')
def all_failed_tests():
    p = index.TestPage(get_db(), app.config, page='all')
    return p.display()


@app.route('/new-fail')
def new_failed_tests():
    p = index.TestPage(get_db(), app.config, page='new')
    return p.display()


@app.route('/long')
def long_tests():
    p = index.TestPage(get_db(), app.config, page='long')
    return p.display()


@app.route('/platform/<int:plat>/comp/<int:comp>')
def platform_component_tests(plat, comp):
    p = index.TestPage(get_db(), app.config, page='compplattest',
                       platform=plat, component=comp)
    return p.display()


@app.route('/platform/<int:plat>/test/<int:test>')
def one_test(plat, test):
    p = index.TestPage(get_db(), app.config, page='results',
                       platform=plat, test=test)
    return p.display()


@app.route('/doc')
def doc():
    p = index.TestPage(get_db(), app.config, page='doc')
    return p.display()
