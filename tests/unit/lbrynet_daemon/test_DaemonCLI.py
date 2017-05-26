from lbrynet.core import utils
from twisted.trial import unittest


class test_obj(object):
    def f1(self, one=True, two=None, three="three", four=1):
        return

    def f2(self, one=1, two=2, three="three", *four):
        return

    def f3(self, one, two=None, three="three", *four):
        return

    def f4(self, one, two='two', *three, **four):
        return

    def f5(self):
        return

    def f6(self, *one):
        return


def f1(one=True, two=None, three="three", four=1):
    return


def f2(one=1, two=2, three="three", *four):
    return


def f3(one, two=None, three="three", *four):
    return


def f4(one, two='two', *three, **four):
    return


def f5():
    return


def f6(*one):
    return


test_methods = [
    (f1, "f1 1", ((1, None, "three", 1), {})),
    (f1, "f1", ((True, None, "three", 1), {})),
    (f1, "f1 three=three two=None one=True four=1", ((1, None, "three", 1), {})),
    (f1, "f1 1 three=three two=None four=1", ((1, None, "three", 1), {})),
    (f2, "f2 one", (("one", 2, "three"), {})),
    (f3, "f3 1", ((1, None, "three"), {})),
    (f3, "f3 1 4 two=2 three=3", ((1, 2, 3, 4), {})),
    (f3, "f3 1 three=three two=None four=1", ((1, None, "three", 1), {})),
    (f4, "f4 1", ((1, "two"), {})),
    (f4, "f4 1 3 4 two=2", ((1, 2, 3, 4), {})),
    (f4, "f4 1 3 two=2 five=5", ((1, 2, 3), {'five': 5})),
    (f5, "f5 ", ((), {})),
    (f6, "f6 1 2 3 4 5 6 7 8 9", ((1, 2, 3, 4, 5, 6, 7, 8, 9), {})),
]


test_instance = test_obj()

test_instance_methods = [
    (test_instance.f1, "f1 1",                             ((1, None, "three", 1), {})),
    (test_instance.f1, "f1",                               ((True, None, "three", 1), {})),
    (test_instance.f1, "f1 three=three two=None one=True four=1", ((1, None, "three", 1), {})),
    (test_instance.f1, "f1 1 three=three two=None four=1", ((1, None, "three", 1), {})),
    (test_instance.f2, "f2 one",                           (("one", 2, "three"), {})),
    (test_instance.f3, "f3 1",                             ((1, None, "three"), {})),
    (test_instance.f3, "f3 1 4 two=2 three=3",             ((1, 2, 3, 4), {})),
    (test_instance.f3, "f3 1 three=three two=None four=1", ((1, None, "three", 1), {})),
    (test_instance.f4, "f4 1",                             ((1, "two"), {})),
    (test_instance.f4, "f4 1 3 4 two=2",                   ((1, 2, 3, 4), {})),
    (test_instance.f4, "f4 1 3 two=2 five=5",              ((1, 2, 3), {'five': 5})),
    (test_instance.f5, "f5 ",                              ((), {})),
    (test_instance.f6, "f6 1 2 3 4 5 6 7 8 9",             ((1, 2, 3, 4, 5, 6, 7, 8, 9), {})),
]


class DaemonCLITests(unittest.TestCase):
    def _run_parse_test_case(self, fn, cmd_str, results, i):
        arguments = cmd_str.split(" ")
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
        if arg_list == ['']:
            arg_list = []
        arg_tup, arg_dict = utils.check_params(fn, arg_list, kw_dict, True)
        self.assertTupleEqual(results[0], arg_tup)
        self.assertDictEqual(results[1], arg_dict)

    def test_parse_args(self):
        cnt = 0
        for fn, cmd_str, results in test_methods:
            self._run_parse_test_case(fn, cmd_str, results, cnt)
            cnt += 1
        for fn, cmd_str, results in test_instance_methods:
            self._run_parse_test_case(fn, cmd_str, results, cnt)
            cnt += 1

    def test_guess_type(self):
        self.assertEqual('0.3.8', utils.guess_type('0.3.8'))
        self.assertEqual(0.3, utils.guess_type('0.3'))
        self.assertEqual(3, utils.guess_type('3'))
        self.assertEqual('VdNmakxFORPSyfCprAD/eDDPk5TY9QYtSA==', utils.guess_type('VdNmakxFORPSyfCprAD/eDDPk5TY9QYtSA=='))
        self.assertEqual(0.3, utils.guess_type('0.3'))
        self.assertEqual(True, utils.guess_type('TRUE'))
        self.assertEqual(True, utils.guess_type('true'))
        self.assertEqual(True, utils.guess_type('True'))
        self.assertEqual(False, utils.guess_type('FALSE'))
        self.assertEqual(False, utils.guess_type('false'))
        self.assertEqual(False, utils.guess_type('False'))