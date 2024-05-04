'''
    Provides functionality for checking login details,
    session validity, and the like.

    2019-24 Benjamin Kellenberger
'''

from typing import Tuple, List
import os
import functools
import hashlib
import re
from datetime import timedelta
from threading import Thread
import secrets
import bcrypt
from bottle import request, response, abort
from psycopg2 import sql

from util.helpers import current_time
from util.common import check_demo_mode
from util import helpers
from .exceptions import *



class UserMiddleware():
    '''
        Handles user authentication and request approval/rejection for all modules.
    '''

    TOKEN_NUM_BYTES = 64
    SALT_NUM_ROUNDS = 12

    CSRF_TOKEN_NAME = '_csrf_token'
    CSRF_TOKEN_AGE = 600
    CSRF_SECRET_FALLBACK = '!ftU$_4FnJ6eA2uN'   # fallback for CSRF secret if not defined in config


    def __init__(self, config, dbConnector):
        self.config = config
        self.db_connector = dbConnector

        self.users_logged_in = {}    # username -> {timestamp, sessionToken}

        self.csrf_secret = self.config.get_property('UserHandler',
                                                    'csrf_secret',
                                                    dtype=str,
                                                    fallback=self.CSRF_SECRET_FALLBACK)

        self.account_name_test = re.compile('^[A-Za-z0-9_-]*')
        self.email_test = re.compile(
                            r'([A-Za-z0-9]+[.-_])*[A-Za-z0-9]+@[A-Za-z0-9-]+(\.[A-Z|a-z]{2,})+')


    def _current_time(self):
        return current_time()


    def _create_token(self):
        return secrets.token_urlsafe(self.TOKEN_NUM_BYTES)


    def _compare_tokens(self, token_a, token_b):
        if token_a is None or token_b is None:
            return False
        return secrets.compare_digest(token_a, token_b)


    def _check_password(self, passwd_provided, passwd_target_hashed) -> bool:
        return bcrypt.checkpw(passwd_provided, passwd_target_hashed)


    def _get_user_data(self, username: str) -> dict:
        result = self.db_connector.execute('''
                SELECT last_login, session_token, secret_token
                FROM aide_admin.user WHERE name = %s;''',
                                           (username,),
                                           numReturn=1)
        if len(result) == 0:
            return None
        return result[0]


    def _extend_session_database(self, username: str, session_token: str) -> None:
        '''
            Updates the last login timestamp of the user to the current time and commits the changes
            to the database. Runs in a thread to be non-blocking.
        '''
        def _extend_session():
            now = self._current_time()

            self.db_connector.execute('''UPDATE aide_admin.user SET last_login = %s,
                    session_token = %s
                    WHERE name = %s
                ''',
                (now, session_token, username,),
                numReturn=None)

            # also update local cache
            self.users_logged_in[username]['timestamp'] = now

        extension_thread = Thread(target=_extend_session)
        extension_thread.start()


    def _init_or_extend_session(self,
                                username: str,
                                session_token: str=None) -> Tuple[str,float,float]:
        '''
            Establishes a "session" for the user (i.e., sets 'time_login' to now). Also creates a
            new sessionToken if None provided.
        '''
        now = self._current_time()

        if session_token is None:
            session_token = self._create_token()

            # new session created; add to database
            self.db_connector.execute('''UPDATE aide_admin.user
                SET last_login = %s, session_token = %s
                WHERE name = %s;
            ''',
            (now, session_token, username,),
            numReturn=None)

            # store locally
            self.users_logged_in[username] = {
                'timestamp': now,
                'sessionToken': session_token
            }

        # update local cache as well
        if not username in self.users_logged_in:
            self.users_logged_in[username] = {
                'timestamp': now,
                'sessionToken': session_token
            }
        else:
            self.users_logged_in[username]['timestamp'] = now
            self.users_logged_in[username]['sessionToken'] = session_token

            # also tell DB about updated tokens
            self._extend_session_database(username, session_token)

        time_login = self.config.get_property('UserHandler',
                                              'time_login',
                                              dtype=int,
                                              fallback=31536000)  # fallback: add one year
        expires = now + timedelta(0, time_login)

        return session_token, now, expires


    def _invalidate_session(self, username: str) -> None:
        if username in self.users_logged_in:
            del self.users_logged_in[username]
        self.db_connector.execute(
            'UPDATE aide_admin.user SET session_token = NULL WHERE name = %s',
            (username,),
            numReturn=None)
        #TODO: feedback that everything is ok?


    def _check_account_name_validity(self, username: str, email: str) -> tuple:
        username_valid = re.fullmatch(self.account_name_test, username) is not None
        email_valid = re.fullmatch(self.email_test, email) is not None
        return username_valid, email_valid


    def _check_account_available(self, username: str, email: str) -> tuple:
        username_available, email_available = self._check_account_name_validity(username, email)
        if not username_available and not email_available:
            return username_available, email_available

        result = self.db_connector.execute('''
            SELECT COUNT(name) AS c FROM aide_admin.user
            WHERE name = %s UNION ALL
            SELECT COUNT(name) AS c FROM aide_admin.user WHERE email = %s''',
                (username,email,),
                numReturn=2)
        username_available = username_available and (result[0]['c'] == 0)
        email_available = email_available and (result[1]['c'] == 0)
        return username_available, email_available


    def _check_logged_in(self, username: str, session_token: str) -> bool:
        now = self._current_time()
        time_login = self.config.get_property('UserHandler',
                                              'time_login',
                                              dtype=int,
                                              fallback=-1)
        if username not in self.users_logged_in:
            # check database
            result = self._get_user_data(username)
            if result is None:
                # account does not exist
                return False

            # check for session token
            if not self._compare_tokens(result['session_token'], session_token):
                # invalid session token provided
                return False

            # check for timestamp
            time_diff = (now - result['last_login']).total_seconds()
            if time_login <= 0 or time_diff <= time_login:
                # user still logged in
                if not username in self.users_logged_in:
                    self.users_logged_in[username] = {
                        'timestamp': now,
                        'sessionToken': session_token
                    }
                else:
                    self.users_logged_in[username]['timestamp'] = now

                # extend user session (commit to DB) if needed
                if time_login > 0 and time_diff >= 0.75 * time_login:
                    self._extend_session_database(username, session_token)

                return True

            # session time-out
            return False

        # check locally
        if not self._compare_tokens(self.users_logged_in[username]['sessionToken'],
                session_token):
            # invalid session token provided; check database if token has updated
            # (can happen if user logs in again from another machine)
            result = self._get_user_data(username)
            if not self._compare_tokens(result['session_token'],
                        session_token):
                return False

            # update local cache
            self.users_logged_in[username]['sessionToken'] = result['session_token']
            self.users_logged_in[username]['timestamp'] = now

        time_diff = (now - self.users_logged_in[username]['timestamp']).total_seconds()
        if time_login <= 0 or time_diff <= time_login:
            # user still logged in; extend user session (commit to DB) if needed
            if time_login > 0 and time_diff >= 0.75 * time_login:
                self._extend_session_database(username, session_token)
            return True

        # local cache session time-out; check if database holds more recent timestamp
        result = self._get_user_data(username)
        if time_login <= 0 or (now - result['last_login']).total_seconds() <= time_login:
            # user still logged in; update
            self._init_or_extend_session(username, session_token)

        else:
            # session time-out
            return False

        # generic error
        return False


    def _check_authorized(self,
                          project: str,
                          username: str,
                          admin: bool,
                          return_all: bool=False) -> dict:
        '''
            Verifies whether a user has access rights to a project. If "return_all" is set to True,
            a dict with the following bools is returned:
                - enrolled: if the user is member of the project
                - isAdmin: if the user is a project administrator
                - isPublic: if the project is publicly visible (*)
                - demoMode: if the project runs in demo mode (*)

            (* note that these are here for convenience, but do not count as authorization tokens)

            If "return_all" is False, only a single bool is returned, with criteria as follows:
                - if "admin" is set to True, the user must be a project admini-
                strator - else, the user must be enrolled, admitted, and not blocked for the current
                date and time

            In this case, options like the demo mode and public flag are not relevant for the
            decision.
        '''
        now = current_time()
        authentication = {
            'enrolled': False,
            'isAdmin': False,
            'isPublic': False
        }

        query_str = sql.SQL('''
            SELECT * FROM aide_admin.authentication AS auth
            JOIN (SELECT shortname, demoMode, isPublic FROM aide_admin.project) AS proj
            ON auth.project = proj.shortname
            WHERE project = %s AND username = %s;
        ''')
        try:
            result = self.db_connector.execute(query_str, (project, username,), 1)
            if len(result):
                authentication['isAdmin'] = result[0]['isadmin']
                authentication['isPublic'] = result[0]['ispublic']
                admitted_until = True
                blocked_until = False
                if result[0]['admitted_until'] is not None:
                    admitted_until = result[0]['admitted_until'] >= now
                if result[0]['blocked_until'] is not None:
                    blocked_until = result[0]['blocked_until'] >= now
                authentication['enrolled'] = (admitted_until and not blocked_until)
        except Exception:
            # no results to fetch: user is not authenticated
            pass

        # check if super user
        super_user = self._check_user_privileges(username, superuser=True)
        if super_user:
            authentication['enrolled'] = True
            authentication['isAdmin'] = True

        if return_all:
            return authentication

        if admin:
            return authentication['isAdmin']
        return authentication['enrolled']


    def check_demo_mode(self, project: str) -> bool:
        '''
            Returns True if the project with given shortname is in demo mode, else False.
        '''
        return check_demo_mode(project, self.db_connector)


    def decrypt_session_token(self, username: str, request_obj: request) -> str:
        '''
            Decrypts and returns the current session token for given username and request (or None
            if it is not present or else could not be decrypted).
        '''
        try:
            userdata = self._get_user_data(username)
            return request_obj.get_cookie('session_token', secret=userdata['secret_token'])
        except Exception:
            return None


    def encrypt_session_token(self, username: str, response_obj: response) -> None:
        '''
            Retrieves the data for given user and sets the session token for the response.
        '''
        userdata = self._get_user_data(username)
        response_obj.set_cookie('session_token',
                                userdata['session_token'],
                                httponly=True,
                                path='/',
                                secret=userdata['secret_token'])


    def _check_user_privileges(self,
                               username: str,
                               superuser: bool=False,
                               can_create_projects: bool=False,
                               return_all: bool=False) -> dict:
        user_privileges = {
            'superuser': False,
            'can_create_projects': False
        }
        result = self.db_connector.execute('''SELECT isSuperUser, canCreateProjects
            FROM aide_admin.user WHERE name = %s;''',
            (username,),
            1)

        if len(result) > 0:
            user_privileges['superuser'] = result[0]['issuperuser']
            user_privileges['can_create_projects'] = result[0]['cancreateprojects']

        if return_all:
            return user_privileges

        if superuser and not result[0]['issuperuser']:
            return False
        if can_create_projects and not (
            result[0]['cancreateprojects'] or result[0]['issuperuser']):
            return False
        return True


    def is_authenticated(self,
                         username: str,
                         session_token: str,
                         project: str=None,
                         admin: bool=False,
                         superuser: bool=False,
                         can_create_projects: bool=False,
                         extend_session: bool=False,
                         return_all: bool=False) -> dict:
        '''
            Checks if the user is authenticated to access a service. Returns False if one or more of
            the following conditions holds:

                - user is not logged in
                - 'project' (shortname) is provided, project is configured to be private and user is
                  not in the
                    authenticated users list
                - 'admin' is True, 'project' (shortname) is provided and user is not an admin of the
                  project
                - 'superuser' is True and user is not a super user
                - 'can_create_projects' is True and user is not authenticated to create (or remove)
                  projects

            If 'extend_session' is True, the user's session will automatically be prolonged by the
            max login time specified in the configuration file.
            
            If 'return_all' is True, all individual flags (instead of just a single bool) is
            returned.
        '''

        demo_mode = check_demo_mode(project, self.db_connector)

        if return_all:
            return_vals = {}
            return_vals['logged_in'] = self._check_logged_in(username, session_token)
            if not return_vals['logged_in']:
                username = None
            if project is not None:
                return_vals['project'] = self._check_authorized(project,
                                                                username,
                                                                admin,
                                                                return_all=True)
                return_vals['project']['demoMode'] = demo_mode
            return_vals['privileges'] = self._check_user_privileges(username,
                                                                    superuser,
                                                                    can_create_projects,
                                                                    return_all=True)
            if return_vals['logged_in'] and extend_session:
                self._init_or_extend_session(username, session_token)
            return return_vals

        if demo_mode is not None and demo_mode:
            # return True if project is in demo mode
            return True
        if not self._check_logged_in(username, session_token):
            return False
        if project is not None and not self._check_authorized(project,
                                                              username,
                                                              admin):
            return False
        if not self._check_user_privileges(username,
                                           superuser,
                                           can_create_projects):
            return False
        if extend_session:
            self._init_or_extend_session(username, session_token)
        return True


    def get_authentication(self, username: str, project: str=None) -> dict:
        '''
            Returns general authentication properties of the user, regardless of whether
            they are logged in or not.
            If a project shortname is specified, this will also return the user access
            properties for the given project.
        '''

        auth = {}
        if project is None:
            result = self.db_connector.execute(
                '''SELECT * FROM aide_admin.user AS u
                    WHERE name = %s;
                ''',
                (username,),
                1)
            auth['canCreateProjects'] = result[0]['cancreateprojects']
            auth['isSuperUser'] = result[0]['issuperuser']
        else:
            result = self.db_connector.execute(
                '''SELECT * FROM aide_admin.user AS u
                    JOIN aide_admin.authentication AS a
                    ON u.name = a.username
                    WHERE name = %s
                    AND project = %s;
                ''',
                (username,project,),
                1)
            auth['canCreateProjects'] = result[0]['cancreateprojects']
            auth['isSuperUser'] = result[0]['issuperuser']
            auth['isAdmin'] = result[0]['isadmin']
            auth['admittedUntil'] = result[0]['admitted_until']
            auth['blockedUntil'] = result[0]['blocked_until']

        return auth


    def get_login_data(self, username: str, session_token: str) -> Tuple[str, float, float]:
        '''
            Performs a lookup on the login timestamp dict. If the username cannot be found (also not
            in the database), they are not logged in (False returned). If the difference between the
            current time and the recorded login timestamp exceeds a pre-defined threshold, the user
            is removed from the dict and False is returned. Otherwise returns True if and only if
            'sessionToken' matches the entry in the database.
        '''
        if self._check_logged_in(username, session_token):
            # still logged in; extend session
            session_token, now, expires = self._init_or_extend_session(username, session_token)
            return session_token, now, expires

        # not logged in or error
        raise Exception('Not logged in.')


    def get_user_permissions(self, project: str, username: str) -> dict:
        '''
            Returns the user-to-project relation (e.g., if user is admin).
        '''
        permissions = {
            'demoMode': False,
            'isAdmin': False,
            'admittedUntil': None,
            'blockedUntil': None
        }

        try:
            # demo mode
            permissions['demoMode'] = check_demo_mode(project, self.db_connector)

            # rest
            query_str = sql.SQL('''SELECT * FROM {id_auth}
                WHERE project = %s AND username = %s''').format(
                id_auth=sql.Identifier('aide_admin', 'authentication'))
            result = self.db_connector.execute(query_str, (project,username,), 1)
            if len(result) > 0:
                permissions['isAdmin'] = result[0]['isadmin']
                permissions['admittedUntil'] = result[0]['admitted_until']
                permissions['blockedUntil'] = result[0]['blocked_until']

        except Exception:
            pass

        return permissions


    def login(self,
              username: str,
              password: str,
              session_token: str) -> Tuple[str,float,float]:
        '''
            Main log in routine. Performs checks as follows:

                1. Whether username exists in database
                2. Whether password is correct
                3. Whether session token is correct

            Returns the session token, current timestamp, and login expiration timestamp if checks
            passed (else raises an exception).
        '''
        # check if logged in
        if self._check_logged_in(username, session_token):
            # still logged in; extend session
            session_token, now, expires = self._init_or_extend_session(username, session_token)
            return session_token, now, expires

        # get user info
        user_data = self.db_connector.execute(
            'SELECT hash FROM aide_admin.user WHERE name = %s;',
            (username,),
            numReturn=1
        )
        if len(user_data) == 0:
            # account does not exist
            raise InvalidRequestException()
        user_data = user_data[0]

        # verify provided password
        if self._check_password(password.encode('utf8'), bytes(user_data['hash'])):
            # correct
            session_token, timestamp, expires = self._init_or_extend_session(username, None)
            return session_token, timestamp, expires

        # incorrect
        self._invalidate_session(username)
        raise InvalidPasswordException()


    def logout(self, username: str, session_token: str) -> None:
        '''
            Main log out routine. Checks whether user is logged in, invalidates session if True.
        '''
        # check if logged in first
        if self._check_logged_in(username, session_token):
            self._invalidate_session(username)


    def account_available(self, username: str, email: str) -> bool:
        '''
            Returns True if a given user name and E-mail address are available (False otherwise).
        '''
        return self._check_account_available(username, email)


    def create_account(self,
                       username: str,
                       password: str,
                       email: str) -> Tuple[str,float,float]:
        '''
            Main routine to create a new user account. Checks if username and E-mail address are
            available (throws an exception if not); if they are, registers user details in database.
            Returns the session token, current timestamp, and login expiration timestamp.
        '''
        username_available, email_available = self._check_account_available(username, email)
        if not username_available or not email_available:
            raise AccountExistsException(username)

        passwd_hash = helpers.create_hash(password.encode('utf8'), self.SALT_NUM_ROUNDS)

        query_str = '''
            INSERT INTO aide_admin.user (name, email, hash)
            VALUES (%s, %s, %s);
        '''
        self.db_connector.execute(query_str,
        (username, email, passwd_hash,),
        numReturn=None)
        session_token, timestamp, expires = self._init_or_extend_session(username)
        return session_token, timestamp, expires


    def get_user_names(self, project=None) -> List[str]:
        '''
            Gets all user names in AIDE (if "project" is None) or else in a given project.
        '''
        if not isinstance(project, str):
            query_str = 'SELECT name FROM aide_admin.user'
            query_vals = None
        else:
            query_str = 'SELECT username AS name FROM aide_admin.authentication WHERE project = %s'
            query_vals = (project,)
        result = self.db_connector.execute(query_str, query_vals, 'all')
        return [r['name'] for r in result]


    def set_password(self, username: str, password: str) -> dict:
        '''
            Sets a new password for given username. Does NOT perform any checks (login, integrity,
            etc.).
        '''
        hash_val = helpers.create_hash(password.encode('utf8'), self.SALT_NUM_ROUNDS)
        query_str = '''
            UPDATE aide_admin.user
            SET hash = %s
            WHERE name = %s;
            SELECT hash
            FROM aide_admin.user
            WHERE name = %s;
        '''
        result = self.db_connector.execute(query_str,
                                           (hash_val, username, username),
                                           1)
        if len(result) > 0:
            return {
                'success': True
            }
        return {
            'success': False,
            'message': f'User with name "{username}" does not exist.'
        }


    # CSRF prevention functionality, adapted from
    # https://github.com/Othernet-Project/bottle-utils-csrf/blob/master/bottle_utils/csrf.py

    def generate_csrf_token(self) -> None:
        '''
            Generate and set new CSRF token in cookie. The generated token is set to
            ``request.csrf_token`` attribute for easier access by other functions.

            .. warning::

            This function uses ``os.urandom()`` call to obtain 8 random bytes when
            generating the token. It is possible to deplete the randomness pool and
            make the random token predictable.
        '''
        sha256 = hashlib.sha256()
        sha256.update(os.urandom(8))
        token = sha256.hexdigest().encode('utf8')
        response.set_cookie(self.CSRF_TOKEN_NAME,
                            token,
                            path='/',
                            secret=self.csrf_secret,
                            max_age=self.CSRF_TOKEN_AGE)
        request.csrf_token = token.decode('utf8')


    def csrf_token(self, func: callable) -> None:
        '''
            Create and set CSRF token in preparation for subsequent POST request. This
            decorator is used to set the token. It also sets the ``'Cache-Control'``
            header in order to prevent caching of the page on which the token appears.
            When an existing token cookie is found, it is reused. The existing token is
            reset so that the expiration time is extended each time it is reused.
            The POST handler must use the :py:func:`~bottle_utils.csrf.csrf_protect`
            decotrator for the token to be used in any way.
            The token is available in the ``bottle.request`` object as ``csrf_token``
            attribute::
                @app.get('/')
                @bottle.view('myform')
                @csrf_token
                def put_token_in_form():
                    return dict(token=request.csrf_token)
            In a view, you can render this token as a hidden field inside the form. The
            hidden field must have a name ``_csrf_token``::
                <form method="POST">
                    <input type="hidden" name="_csrf_token" value="{{ csrf_token }}">
                    ....
                </form>
        '''
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            token = request.get_cookie(self.CSRF_TOKEN_NAME, secret=self.csrf_secret)
            if token:
                # We will reuse existing tokens
                response.set_cookie(self.CSRF_TOKEN_NAME,
                                    token,
                                    path='/',
                                    secret=self.csrf_secret,
                                    max_age=self.CSRF_TOKEN_AGE)
                request.csrf_token = token.decode('utf8')
            else:
                self.generate_csrf_token()
            # Pages with CSRF tokens should not be cached
            response.headers[str('Cache-Control')] = ('no-cache, max-age=0, '
                                                      'must-revalidate, no-store')
            return func(*args, **kwargs)
        return wrapper


    def csrf_check(self, token: str, regenerate: bool=True) -> None:
        '''
            Perform CSRF protection checks. Performs checks to determine if submitted token matches
            the token in the cookie. If "regenerate" is False the current CSRF token will be reused.
        '''
        if isinstance(token, bytes):
            token = token.decode('utf8')
        token_cookie = request.get_cookie(self.CSRF_TOKEN_NAME, secret=self.csrf_secret)
        if isinstance(token_cookie, bytes):
            token_cookie = token_cookie.decode('utf8')
        if token != token_cookie:
            response.delete_cookie(self.CSRF_TOKEN_NAME,
                                   path='/',
                                   secret=self.csrf_secret,
                                   max_age=self.CSRF_TOKEN_AGE)
            abort(403, 'Request is invalid or has expired.')
        if regenerate:
            self.generate_csrf_token()
