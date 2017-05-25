import logging
import urlparse
import inspect
import json

from decimal import Decimal
from zope.interface import implements
from twisted.web import server, resource
from twisted.internet import defer
from twisted.python.failure import Failure
from twisted.internet.error import ConnectionDone, ConnectionLost
from txjsonrpc import jsonrpclib
from traceback import format_exc

from lbrynet import conf
from lbrynet.core.Error import InvalidAuthenticationToken
from lbrynet.core import utils
from lbrynet.undecorated import undecorated
from lbrynet.lbrynet_daemon.auth.util import APIKey, get_auth_message
from lbrynet.lbrynet_daemon.auth.client import LBRY_SECRET

log = logging.getLogger(__name__)

EMPTY_PARAMS = [{}]


class JSONRPCError(object):
    # http://www.jsonrpc.org/specification#error_object
    CODE_PARSE_ERROR = -32700  # Invalid JSON. Error while parsing the JSON text.
    CODE_INVALID_REQUEST = -32600  # The JSON sent is not a valid Request object.
    CODE_METHOD_NOT_FOUND = -32601  # The method does not exist / is not available.
    CODE_INVALID_PARAMS = -32602  # Invalid method parameter(s).
    CODE_INTERNAL_ERROR = -32603  # Internal JSON-RPC error (I think this is like a 500?)
    CODE_APPLICATION_ERROR = -32500  # Generic error with our app??
    CODE_AUTHENTICATION_ERROR = -32501  # Authentication failed

    MESSAGES = {
        CODE_PARSE_ERROR: "Parse Error. Data is not valid JSON.",
        CODE_INVALID_REQUEST: "JSON data is not a valid Request",
        CODE_METHOD_NOT_FOUND: "Method Not Found",
        CODE_INVALID_PARAMS: "Invalid Params",
        CODE_INTERNAL_ERROR: "Internal Error",
        CODE_AUTHENTICATION_ERROR: "Authentication Failed",
    }

    HTTP_CODES = {
        CODE_INVALID_REQUEST: 400,
        CODE_PARSE_ERROR: 400,
        CODE_INVALID_PARAMS: 400,
        CODE_METHOD_NOT_FOUND: 404,
        CODE_INTERNAL_ERROR: 500,
        CODE_APPLICATION_ERROR: 500,
        CODE_AUTHENTICATION_ERROR: 401,
    }

    def __init__(self, message, code=CODE_APPLICATION_ERROR, traceback=None, data=None):
        assert isinstance(code, (int, long)), "'code' must be an int"
        assert (data is None or isinstance(data, dict)), "'data' must be None or a dict"
        self.code = code
        if message is None:
            message = self.MESSAGES[code] if code in self.MESSAGES else "Error"
        self.message = message
        self.data = {} if data is None else data
        if traceback is not None:
            self.data['traceback'] = traceback.split("\n")

    def to_dict(self):
        ret = {
            'code': self.code,
            'message': self.message,
        }
        if len(self.data):
            ret['data'] = self.data
        return ret

    @classmethod
    def create_from_exception(cls, exception, code=CODE_APPLICATION_ERROR, traceback=None):
        return cls(exception.message, code=code, traceback=traceback)


def default_decimal(obj):
    if isinstance(obj, Decimal):
        return float(obj)


class UnknownAPIMethodError(Exception):
    pass


class NotAllowedDuringStartupError(Exception):
    pass


def trap(err, *to_trap):
    err.trap(*to_trap)


def jsonrpc_dumps_pretty(obj, **kwargs):
    try:
        id_ = kwargs.pop("id")
    except KeyError:
        id_ = None

    if isinstance(obj, JSONRPCError):
        data = {"jsonrpc": "2.0", "error": obj.to_dict(), "id": id_}
    else:
        data = {"jsonrpc": "2.0", "result": obj, "id": id_}

    return json.dumps(data, cls=jsonrpclib.JSONRPCEncoder, sort_keys=True, indent=2,
                      separators=(',', ': '), **kwargs) + "\n"


class AuthorizedBase(object):
    def __init__(self):
        self.authorized_functions = []
        self.callable_methods = {}
        self._call_lock = {}
        self._queued_methods = []

        for methodname in dir(self):
            if methodname.startswith("jsonrpc_"):
                method = getattr(self, methodname)
                self.callable_methods.update({methodname.split("jsonrpc_")[1]: method})
                if hasattr(method, '_auth_required'):
                    self.authorized_functions.append(methodname.split("jsonrpc_")[1])
                if hasattr(method, '_queued'):
                    self._queued_methods.append(methodname.split("jsonrpc_")[1])

    @staticmethod
    def auth_required(f):
        f._auth_required = True
        return f

    @staticmethod
    def queued(f):
        f._queued = True
        return f


class AuthJSONRPCServer(AuthorizedBase):
    """Authorized JSONRPC server used as the base class for the LBRY API

    API methods are named with a leading "jsonrpc_"

    Decorators:

        @AuthJSONRPCServer.auth_required: this requires that the client
            include a valid hmac authentication token in their request

    Attributes:
        allowed_during_startup (list): list of api methods that are
            callable before the server has finished startup

        sessions (dict): dictionary of active session_id:
            lbrynet.lbrynet_daemon.auth.util.APIKey values

        authorized_functions (list): list of api methods that require authentication

        callable_methods (dict): dictionary of api_callable_name: method values

    """
    implements(resource.IResource)

    isLeaf = True

    def __init__(self, use_authentication=None):
        AuthorizedBase.__init__(self)
        self._use_authentication = (
            use_authentication if use_authentication is not None else conf.settings['use_auth_http']
        )
        self.announced_startup = False
        self.allowed_during_startup = []
        self.sessions = {}

    def setup(self):
        return NotImplementedError()

    def _set_headers(self, request, data, update_secret=False):
        if conf.settings['allowed_origin']:
            request.setHeader("Access-Control-Allow-Origin", conf.settings['allowed_origin'])
        request.setHeader("Content-Type", "application/json")
        request.setHeader("Accept", "application/json-rpc")
        request.setHeader("Content-Length", str(len(data)))
        if update_secret:
            session_id = request.getSession().uid
            request.setHeader(LBRY_SECRET, self.sessions.get(session_id).secret)

    @staticmethod
    def _render_message(request, message):
        request.write(message)
        request.finish()

    def _render_error(self, failure, request, id_):
        if isinstance(failure, JSONRPCError):
            error = failure
        elif isinstance(failure, Failure):
            # maybe failure is JSONRPCError wrapped in a twisted Failure
            error = failure.check(JSONRPCError)
            if error is None:
                # maybe its a twisted Failure with another type of error
                error = JSONRPCError(failure.getErrorMessage(), traceback=failure.getTraceback())
        else:
            # last resort, just cast it as a string
            error = JSONRPCError(str(failure))

        response_content = jsonrpc_dumps_pretty(error, id=id_)

        self._set_headers(request, response_content)
        try:
            request.setResponseCode(JSONRPCError.HTTP_CODES[error.code])
        except KeyError:
            request.setResponseCode(JSONRPCError.HTTP_CODES[JSONRPCError.CODE_INTERNAL_ERROR])
        self._render_message(request, response_content)

    @staticmethod
    def _handle_dropped_request(result, d, function_name):
        if not d.called:
            log.warning("Cancelling dropped api request %s", function_name)
            d.cancel()

    def render(self, request):
        try:
            return self._render(request)
        except BaseException as e:
            log.error(e)
            error = JSONRPCError.create_from_exception(e, traceback=format_exc())
            self._render_error(error, request, None)
            return server.NOT_DONE_YET

    def _render(self, request):
        time_in = utils.now()
        # assert self._check_headers(request), InvalidHeaderError
        session = request.getSession()
        session_id = session.uid
        finished_deferred = request.notifyFinish()

        if self._use_authentication:
            # if this is a new session, send a new secret and set the expiration
            # otherwise, session.touch()
            if self._initialize_session(session_id):
                def expire_session():
                    self._unregister_user_session(session_id)

                session.startCheckingExpiration()
                session.notifyOnExpire(expire_session)
                message = "OK"
                request.setResponseCode(200)
                self._set_headers(request, message, True)
                self._render_message(request, message)
                return server.NOT_DONE_YET
            else:
                session.touch()

        request.content.seek(0, 0)
        content = request.content.read()
        try:
            parsed = jsonrpclib.loads(content)
        except ValueError:
            log.warning("Unable to decode request json")
            self._render_error(JSONRPCError(None, JSONRPCError.CODE_PARSE_ERROR), request, None)
            return server.NOT_DONE_YET

        id_ = None
        try:
            function_name = parsed.get('method')
            is_queued = function_name in self._queued_methods
            args = parsed.get('params', {})
            id_ = parsed.get('id', None)
            token = parsed.pop('hmac', None)
        except AttributeError as err:
            log.warning(err)
            self._render_error(
                JSONRPCError(None, code=JSONRPCError.CODE_INVALID_REQUEST), request, id_
            )
            return server.NOT_DONE_YET

        reply_with_next_secret = False
        if self._use_authentication:
            if function_name in self.authorized_functions:
                try:
                    self._verify_token(session_id, parsed, token)
                except InvalidAuthenticationToken as err:
                    log.warning("API validation failed")
                    self._render_error(
                        JSONRPCError.create_from_exception(
                            err.message, code=JSONRPCError.CODE_AUTHENTICATION_ERROR,
                            traceback=format_exc()
                        ),
                        request, id_
                    )
                    return server.NOT_DONE_YET
                self._update_session_secret(session_id)
                reply_with_next_secret = True

        try:
            function = self._get_jsonrpc_method(function_name)
        except UnknownAPIMethodError as err:
            log.warning('Failed to get function %s: %s', function_name, err)
            self._render_error(
                JSONRPCError(None, JSONRPCError.CODE_METHOD_NOT_FOUND),
                request, id_
            )
            return server.NOT_DONE_YET
        except NotAllowedDuringStartupError as err:
            log.warning('Function not allowed during startup %s: %s', function_name, err)
            self._render_error(
                JSONRPCError("This method is unavailable until the daemon is fully started",
                             code=JSONRPCError.CODE_INVALID_REQUEST),
                request, id_
            )
            return server.NOT_DONE_YET

        if isinstance(args, list):
            if args == [{}]:
                args_list = []
                args_dict = {}
            else:
                if args and isinstance(args[0], dict):
                    args_dict = args[0]
                    args_list = args[1:]
                else:
                    args_list = args
                    args_dict = {}
        elif isinstance(args, dict):
            if "__args" in args:
                args_list = args.pop("__args")
            else:
                args_list = []
            args_dict = args
        else:
            raise Exception("Unknown argument format")

        try:
            _args, _kwargs = self._check_params(function, args_list, args_dict)
        except Exception as params_error:
            log.warning(params_error.message)
            self._render_error(
                JSONRPCError(params_error.message, code=JSONRPCError.CODE_INVALID_PARAMS),
                request, id_
            )
            return server.NOT_DONE_YET
        if is_queued:
            d_lock = self._call_lock.get(function_name, False)
            if not d_lock:
                d = defer.maybeDeferred(function, *_args, **_kwargs)
                self._call_lock[function_name] = finished_deferred

                def _del_lock(*args):
                    if function_name in self._call_lock:
                        del self._call_lock[function_name]
                    if args:
                        return args

                finished_deferred.addCallback(_del_lock)

            else:
                log.info("queued %s", function_name)
                d = d_lock
                d.addBoth(lambda _: log.info("running %s from queue", function_name))
                d.addCallback(lambda _: defer.maybeDeferred(function, *_args, **_kwargs))
        else:
            d = defer.maybeDeferred(function, *_args, **_kwargs)

        # finished_deferred will callback when the request is finished
        # and errback if something went wrong. If the errback is
        # called, cancel the deferred stack. This is to prevent
        # request.finish() from being called on a closed request.
        finished_deferred.addErrback(self._handle_dropped_request, d, function_name)

        d.addCallback(self._callback_render, request, id_, reply_with_next_secret)
        # TODO: don't trap RuntimeError, which is presently caught to
        # handle deferredLists that won't peacefully cancel, namely
        # get_lbry_files
        d.addErrback(trap, ConnectionDone, ConnectionLost, defer.CancelledError, RuntimeError)
        d.addErrback(log.fail(self._render_error, request, id_),
                     'Failed to process %s', function_name)
        d.addBoth(lambda _: log.debug("%s took %f",
                                      function_name,
                                      (utils.now() - time_in).total_seconds()))
        return server.NOT_DONE_YET

    @staticmethod
    def _check_params(fn, args_list=None, args_dict=None):
        args_list = args_list or []
        args_dict = args_dict or {}
        argspec = inspect.getargspec(undecorated(fn))
        start_pos = 0 if not inspect.ismethod(fn) else 1
        arg_names = [] if argspec.args is None else argspec.args[start_pos:]
        defaults = []
        default_cnt = 0 if argspec.defaults is None else len(argspec.defaults)
        required = len(arg_names) - default_cnt

        for key, arg in zip(arg_names[-default_cnt:], argspec.defaults or []):
            defaults.append((key, arg))

        args = ()
        kwargs = {}

        for i, arg in enumerate(args_list):
            if i < len(arg_names):
                arg_name = arg_names[i]
                if arg_name in args_dict:
                    name = fn.__name__
                    raise Exception("Argument \"%s\" given to %s an arg and a kwarg" % (arg_name,
                                                                                        name))
            elif argspec.varargs is None:
                raise Exception("Too many arguments given")
            args += (arg, )

        for i, req_key in enumerate(arg_names):
            if len(args) + len(kwargs) == i:
                if req_key in args_dict:
                    kwargs.update({req_key: args_dict.pop(req_key)})
                elif req_key in [x[0] for x in defaults]:
                    v = [x[1] for x in defaults if x[0] == req_key][0]
                    kwargs.update({req_key: v})

        missing_required = [n for n in arg_names[len(args):] if n not in [i[0] for i in defaults]]

        if missing_required:
            raise Exception("%s missing required arguments: %s" % (fn.__name__, missing_required))

        if args_dict is not None:
            if argspec.varargs is not None and argspec.varargs in args_dict:
                args += tuple(args_dict.pop(argspec.varargs))
            if argspec.keywords is not None and argspec.keywords in args_dict:
                kwargs.update(args_dict.pop(argspec.keywords))
        if args_dict:
            raise Exception("Extraneous params given to %s: %s" % (fn.__name__, args_dict))

        return args, kwargs

    def _register_user_session(self, session_id):
        """
        Add or update a HMAC secret for a session

        @param session_id:
        @return: secret
        """
        log.info("Register api session")
        token = APIKey.new(seed=session_id)
        self.sessions.update({session_id: token})

    def _unregister_user_session(self, session_id):
        log.info("Unregister API session")
        del self.sessions[session_id]

    def _check_headers(self, request):
        return (
            self._check_header_source(request, 'Origin') and
            self._check_header_source(request, 'Referer'))

    def _check_header_source(self, request, header):
        """Check if the source of the request is allowed based on the header value."""
        source = request.getHeader(header)
        if not self._check_source_of_request(source):
            log.warning("Attempted api call from invalid %s: %s", header, source)
            return False
        return True

    def _check_source_of_request(self, source):
        if source is None:
            return True
        if conf.settings['api_host'] == '0.0.0.0':
            return True
        server, port = self.get_server_port(source)
        return self._check_server_port(server, port)

    def _check_server_port(self, server, port):
        api = (conf.settings['api_host'], conf.settings['api_port'])
        return (server, port) == api or self._is_from_allowed_origin(server, port)

    def _is_from_allowed_origin(self, server, port):
        allowed_origin = conf.settings['allowed_origin']
        if not allowed_origin:
            return False
        if allowed_origin == '*':
            return True
        allowed_server, allowed_port = self.get_server_port(allowed_origin)
        return (allowed_server, allowed_port) == (server, port)

    def get_server_port(self, origin):
        parsed = urlparse.urlparse(origin)
        server_port = parsed.netloc.split(':')
        assert len(server_port) <= 2
        if len(server_port) == 2:
            return server_port[0], int(server_port[1])
        else:
            return server_port[0], 80

    def _verify_method_is_callable(self, function_path):
        if function_path not in self.callable_methods:
            raise UnknownAPIMethodError(function_path)
        if not self.announced_startup:
            if function_path not in self.allowed_during_startup:
                raise NotAllowedDuringStartupError(function_path)

    def _get_jsonrpc_method(self, function_path):
        self._verify_method_is_callable(function_path)
        return self.callable_methods.get(function_path)

    def _initialize_session(self, session_id):
        if not self.sessions.get(session_id, False):
            self._register_user_session(session_id)
            return True
        return False

    def _verify_token(self, session_id, message, token):
        if token is None:
            raise InvalidAuthenticationToken('Authentication token not found')
        to_auth = get_auth_message(message)
        api_key = self.sessions.get(session_id)
        if not api_key.compare_hmac(to_auth, token):
            raise InvalidAuthenticationToken('Invalid authentication token')

    def _update_session_secret(self, session_id):
        self.sessions.update({session_id: APIKey.new(name=session_id)})

    def _callback_render(self, result, request, id_, auth_required=False):
        try:
            encoded_message = jsonrpc_dumps_pretty(result, id=id_, default=default_decimal)
            request.setResponseCode(200)
            self._set_headers(request, encoded_message, auth_required)
            self._render_message(request, encoded_message)
        except Exception as err:
            log.exception("Failed to render API response: %s", result)
            self._render_error(err, request, id_)

    @staticmethod
    def _render_response(result):
        return defer.succeed(result)
