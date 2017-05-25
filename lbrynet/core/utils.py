import base64
import datetime
import logging
import random
import socket
import string
import json
import inspect
import pkg_resources

from lbryschema.claim import ClaimDict
from lbrynet.undecorated import undecorated
from lbrynet.core.cryptoutils import get_lbry_hash_obj

# digest_size is in bytes, and blob hashes are hex encoded
blobhash_length = get_lbry_hash_obj().digest_size * 2

log = logging.getLogger(__name__)


# defining these time functions here allows for easier overriding in testing
def now():
    return datetime.datetime.now()


def utcnow():
    return datetime.datetime.utcnow()


def isonow():
    """Return utc now in isoformat with timezone"""
    return utcnow().isoformat() + 'Z'


def today():
    return datetime.datetime.today()


def timedelta(**kwargs):
    return datetime.timedelta(**kwargs)


def datetime_obj(*args, **kwargs):
    return datetime.datetime(*args, **kwargs)


def call_later(delay, func, *args, **kwargs):
    # Import here to ensure that it gets called after installing a reactor
    # see: http://twistedmatrix.com/documents/current/core/howto/choosing-reactor.html
    from twisted.internet import reactor
    return reactor.callLater(delay, func, *args, **kwargs)


def generate_id(num=None):
    h = get_lbry_hash_obj()
    if num is not None:
        h.update(str(num))
    else:
        h.update(str(random.getrandbits(512)))
    return h.digest()


def is_valid_hashcharacter(char):
    return char in "0123456789abcdef"


def is_valid_blobhash(blobhash):
    """Checks whether the blobhash is the correct length and contains only
    valid characters (0-9, a-f)

    @param blobhash: string, the blobhash to check

    @return: True/False
    """
    return len(blobhash) == blobhash_length and all(is_valid_hashcharacter(l) for l in blobhash)


def version_is_greater_than(a, b):
    """Returns True if version a is more recent than version b"""
    return pkg_resources.parse_version(a) > pkg_resources.parse_version(b)


def deobfuscate(obfustacated):
    return base64.b64decode(obfustacated.decode('rot13'))


def obfuscate(plain):
    return base64.b64encode(plain).encode('rot13')


def check_connection(server="lbry.io", port=80):
    """Attempts to open a socket to server:port and returns True if successful."""
    try:
        log.debug('Checking connection to %s:%s', server, port)
        host = socket.gethostbyname(server)
        s = socket.create_connection((host, port), 2)
        log.debug('Connection successful')
        return True
    except Exception as ex:
        log.info(
            "Failed to connect to %s:%s. Maybe the internet connection is not working",
            server, port, exc_info=True)
        return False


def random_string(length=10, chars=string.ascii_lowercase):
    return ''.join([random.choice(chars) for _ in range(length)])


def short_hash(hash_str):
    return hash_str[:6]


def get_sd_hash(stream_info):
    if not stream_info:
        return None
    if isinstance(stream_info, ClaimDict):
        return stream_info.source_hash
    return stream_info['stream']['source']['source']


def json_dumps_pretty(obj, **kwargs):
    return json.dumps(obj, sort_keys=True, indent=2, separators=(',', ': '), **kwargs)


def check_params(fn, args_list=None, args_dict=None):
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
        args += (arg,)

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