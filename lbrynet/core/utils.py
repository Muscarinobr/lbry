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


def check_params(fn, args_list=None, args_dict=None, convert_type=False):
    args_list = args_list or []
    args_dict = args_dict or {}
    argspec = inspect.getargspec(undecorated(fn))
    start_pos = 0 if not inspect.ismethod(fn) else 1
    arg_names = [] if argspec.args is None else argspec.args[start_pos:]
    default_cnt = 0 if argspec.defaults is None else len(argspec.defaults)

    default_arg_list = []
    undefined = object()

    first_arg_with_default = len(arg_names) - default_cnt

    for i, key in enumerate(arg_names):
        if argspec.defaults is not None and i >= first_arg_with_default:
            default_arg_list.append((key, argspec.defaults[i - first_arg_with_default]))
        else:
            default_arg_list.append((key, undefined))

    has_vargs = argspec.varargs is not None
    has_vkwargs = argspec.keywords is not None

    ordered_arg_list = []
    tmp_args_list = args_list
    tmp_args_list.reverse()

    for i, (arg_name, default) in enumerate(default_arg_list):
        if arg_name in args_dict:
            ordered_arg_list.append((arg_name, args_dict.pop(arg_name)))
        elif tmp_args_list:
            ordered_arg_list.append((arg_name, tmp_args_list.pop()))
        else:
            ordered_arg_list.append((arg_name, default))

    tmp_args_list.reverse()
    args_list = tmp_args_list

    if args_list and has_vargs:
        for arg in args_list:
            ordered_arg_list.append(("*", arg))
    elif has_vargs and argspec.varargs in args_dict:
        for arg in tuple(args_dict.pop(argspec.varargs)):
            ordered_arg_list.append(("*", arg))
    elif args_list and not has_vargs:
        raise Exception("Too many args: %s" % str(args_list))
    final_args = ()
    for arg_name, arg in ordered_arg_list:
        if arg is undefined:
            raise Exception("Missing arg: %s" % arg_name)
        final_args += (arg if not convert_type else guess_type(arg), )
    if args_dict and not has_vkwargs:
        raise Exception("Too many kwargs: %s" % str(args_dict))
    if convert_type:
        for key in args_dict:
            args_dict[key] = guess_type(args_dict[key])
    return final_args, args_dict


def guess_type(x):
    if not isinstance(x, (unicode, str)):
        return x
    if x in ('true', 'True', 'TRUE'):
        return True
    if x in ('false', 'False', 'FALSE'):
        return False
    if x in ('none', 'None', 'null', 'NULL', 'NONE'):
        return None
    if '.' in x:
        try:
            return float(x)
        except ValueError:
            return x
    else:
        try:
            return int(x)
        except ValueError:
            return x
