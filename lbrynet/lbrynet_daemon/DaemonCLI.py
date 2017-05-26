import argparse
import json
import os
import sys
import colorama

from lbrynet import conf
from lbrynet.core import utils
from lbrynet.lbrynet_daemon.auth.client import JSONRPCException, LBRYAPIClient
from lbrynet.lbrynet_daemon.Daemon import LOADING_WALLET_CODE, Daemon
from jsonrpc.common import RPCError
from urllib2 import URLError, HTTPError
from httplib import UNAUTHORIZED


def main():
    colorama.init()
    parser = argparse.ArgumentParser(add_help=False)
    _, arguments = parser.parse_known_args()

    conf.initialize_settings()
    api = LBRYAPIClient.get_client()

    try:
        status = api.status()
    except URLError as err:
        if isinstance(err, HTTPError) and err.code == UNAUTHORIZED:
            print_error("Daemon requires authentication, but none was provided.",
                        suggest_help=False)
        else:
            print_error("Could not connect to daemon. Are you sure it's running?",
                        suggest_help=False)
        return 1

    if status['startup_status']['code'] != "started":
        print "Daemon is in the process of starting. Please try again in a bit."
        message = status['startup_status']['message']
        if message:
            if (
                status['startup_status']['code'] == LOADING_WALLET_CODE
                and status['blockchain_status']['blocks_behind'] > 0
            ):
                message += '. Blocks left: ' + str(status['blockchain_status']['blocks_behind'])
            print "  Status: " + message
        return 1

    if len(arguments) < 1:
        print_help(api)
        return 1

    method = arguments[0]

    if method in api.commands():
        fn = Daemon.callable_methods.get(method)
    else:
        return

    try:
        kw_pos = None
        for i, arg in enumerate(arguments[1:]):
            if "=" in arg and len(arg.split('=')) == 2:
                kw_pos = i + 1
                break
        if kw_pos is not None:
            arg_list = arguments[1:kw_pos]
            kw_dict = {x.split('=')[0]: x.split('=')[1] for x in arguments[kw_pos:]}
        else:
            arg_list, kw_dict = arguments[1:], {}

        args, kwargs = utils.check_params(fn, arg_list, kw_dict)

    except InvalidParameters as e:
        print_error(e.message)
        return 1

    # TODO: check if port is bound. Error if its not

    if method in ['--help', '-h', 'help']:
        if len(args) == 0 and len(kwargs) == 0:
            print_help(api)
        elif 'command' in kwargs:
            print_help_for_command(api, kwargs['command'])
        elif len(args) == 1:
            print_help_for_command(api, args[0])
        else:
            print_error('To get help on a specific command, use `{} help COMMAND_NAME`'.format(
                os.path.basename(sys.argv[0])))
    elif method not in api.commands():
        print_error("'" + method + "' is not a valid command.")
    else:
        try:
            result = api.call(method, *args, **kwargs)
            if isinstance(result, basestring):
                # printing the undumped string is prettier
                print result
            else:
                print utils.json_dumps_pretty(result)
        except (RPCError, KeyError, JSONRPCException, HTTPError) as err:
            error_data = None
            if isinstance(err, HTTPError):
                error_body = err.read()
                try:
                    error_data = json.loads(error_body)
                except ValueError:
                    print (
                        "There was an error, and the response was not valid JSON.\n" +
                        "Raw JSONRPC response:\n" + error_body
                    )
                    return 1

                print_error(error_data['error']['message'] + "\n", suggest_help=False)
            else:
                print_error("Something went wrong\n", suggest_help=False)

            print_help_for_command(api, method)
            if 'data' in error_data['error'] and 'traceback' in error_data['error']['data']:
                print "Here's the traceback for the error you encountered:"
                print "\n".join(error_data['error']['data']['traceback'])
            return 1


class InvalidParameters(Exception):
    pass


def print_help_suggestion():
    print "See `{} help` for more information.".format(os.path.basename(sys.argv[0]))


def print_error(message, suggest_help=True):
    error_style = colorama.Style.BRIGHT + colorama.Fore.RED
    print error_style + "ERROR: " + message + colorama.Style.RESET_ALL
    if suggest_help:
        print_help_suggestion()


def print_help(api):
    print "\n".join([
        "NAME",
        "   lbrynet-cli - LBRY command line client.",
        "",
        "USAGE",
        "   lbrynet-cli <command> [<args>]",
        "",
        "EXAMPLES",
        "   lbrynet-cli commands                   # list available commands",
        "   lbrynet-cli status                     # get daemon status",
        "   lbrynet-cli resolve_name name=what     # resolve a name",
        "   lbrynet-cli help command=resolve_name  # get help for a command",
        "",
        "COMMANDS",
        wrap_list_to_term_width(api.commands(), prefix='   ')
    ])


def print_help_for_command(api, command):
    help_response = api.call('help', {'command': command})
    print "Help for %s method:" % command
    message = help_response['help'] if 'help' in help_response else help_response
    message = "\n".join(['    ' + line for line in message.split("\n")])
    print message


def wrap_list_to_term_width(l, width=None, separator=', ', prefix=''):
    if width is None:
        try:
            _, width = os.popen('stty size', 'r').read().split()
            width = int(width)
        except:
            pass
        if not width:
            width = 80

    lines = []
    curr_line = ''
    for item in l:
        new_line = curr_line + item + separator
        if len(new_line) + len(prefix) > width:
            lines.append(curr_line)
            curr_line = item + separator
        else:
            curr_line = new_line
    lines.append(curr_line)

    ret = prefix + ("\n" + prefix).join(lines)
    if ret.endswith(separator):
        ret = ret[:-len(separator)]
    return ret


if __name__ == '__main__':
    sys.exit(main())
