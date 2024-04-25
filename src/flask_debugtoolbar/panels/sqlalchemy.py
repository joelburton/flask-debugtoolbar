try:
    from flask_sqlalchemy import SQLAlchemy
except ImportError:
    sqlalchemy_available = False
    get_recorded_queries = SQLAlchemy = None
    debug_enables_record_queries = False
else:
    try:
        from flask_sqlalchemy.record_queries import get_recorded_queries
        debug_enables_record_queries = False
    except ImportError:
        # For flask_sqlalchemy < 3.0.0
        from flask_sqlalchemy import get_debug_queries as get_recorded_queries

        # flask_sqlalchemy < 3.0.0 automatically enabled
        # SQLALCHEMY_RECORD_QUERIES in debug or test mode
        debug_enables_record_queries = True

        location_property = 'context'
    else:
        location_property = 'location'
    sqlalchemy_available = True

from flask import request, current_app, abort, g
from flask_debugtoolbar import module
from flask_debugtoolbar.panels import DebugPanel
from flask_debugtoolbar.utils import format_fname, format_sql
import itsdangerous

_ = lambda x: x


def query_signer():
    return itsdangerous.URLSafeSerializer(current_app.config['SECRET_KEY'],
                                          salt='fdt-sql-query')


def is_select(statement):
    prefix = b'select' if isinstance(statement, bytes) else 'select'
    return statement.lower().strip().startswith(prefix)


def dump_query(statement, params):
    if not params or not is_select(statement):
        return None

    try:
        return query_signer().dumps([statement, params])
    except TypeError:
        return None


def load_query(data):
    try:
        statement, params = query_signer().loads(request.args['query'])
    except (itsdangerous.BadSignature, TypeError):
        abort(406)

    # Make sure it is a select statement
    if not is_select(statement):
        abort(406)

    return statement, params


def extension_used():
    return 'sqlalchemy' in current_app.extensions


def recording_enabled():
    return (
        (debug_enables_record_queries and current_app.debug) or
        current_app.config.get('SQLALCHEMY_RECORD_QUERIES')
    )


def is_available():
    return sqlalchemy_available and extension_used() and recording_enabled()


def get_queries():
    if get_recorded_queries:
        return get_recorded_queries()
    else:
        return []


class SQLAlchemyDebugPanel(DebugPanel):
    """
    Panel that displays the time a response took in milliseconds.
    """
    name = 'SQLAlchemy'

    @property
    def has_content(self):
        return bool(get_queries()) or not is_available()

    def process_request(self, request):
        pass

    def process_response(self, request, response):
        pass

    def nav_title(self):
        return _('SQLAlchemy')

    def nav_subtitle(self):
        count = len(get_queries())

        if not count and not is_available():
            return 'Unavailable'

        return '%d %s' % (count, 'query' if count == 1 else 'queries')

    def title(self):
        return _('SQLAlchemy queries')

    def url(self):
        return ''

    def content(self):
        queries = get_queries()

        if not queries and not is_available():
            return self.render('panels/sqlalchemy_error.html', {
                'sqlalchemy_available': sqlalchemy_available,
                'extension_used': extension_used(),
                'recording_enabled': recording_enabled(),
            })

        data = []
        for query in queries:
            data.append({
                'duration': query.duration,
                'sql': format_sql(query.statement, query.parameters),
                'signed_query': dump_query(query.statement, query.parameters),
                'location_long': getattr(query, location_property),
                'location': format_fname(getattr(query, location_property))
            })
        return self.render('panels/sqlalchemy.html', {'queries': data})


# Panel views


@module.route('/sqlalchemy/sql_select', methods=['GET', 'POST'])
@module.route('/sqlalchemy/sql_explain', methods=['GET', 'POST'],
              defaults=dict(explain=True))
def sql_select(explain=False):
    statement, params = load_query(request.args['query'])
    engine = SQLAlchemy().get_engine(current_app)

    if explain:
        if engine.driver == 'pysqlite':
            statement = 'EXPLAIN QUERY PLAN\n%s' % statement
        else:
            statement = 'EXPLAIN\n%s' % statement

    result = engine.execute(statement, params)
    return g.debug_toolbar.render('panels/sqlalchemy_select.html', {
        'result': result.fetchall(),
        'headers': result.keys(),
        'sql': format_sql(statement, params),
        'duration': float(request.args['duration']),
    })
