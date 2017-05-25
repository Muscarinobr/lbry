from twisted.trial import unittest
from lbrynet.lbrynet_daemon import DaemonCLI


class DaemonCLITests(unittest.TestCase):
    def test_guess_type(self):
        self.assertEqual('0.3.8', DaemonCLI.guess_type('0.3.8'))
        self.assertEqual(0.3, DaemonCLI.guess_type('0.3'))
        self.assertEqual(3, DaemonCLI.guess_type('3'))
        self.assertEqual('VdNmakxFORPSyfCprAD/eDDPk5TY9QYtSA==', DaemonCLI.guess_type('VdNmakxFORPSyfCprAD/eDDPk5TY9QYtSA=='))
        self.assertEqual(0.3, DaemonCLI.guess_type('0.3'))
        self.assertEqual(True, DaemonCLI.guess_type('TRUE'))
        self.assertEqual(True, DaemonCLI.guess_type('true'))
        self.assertEqual(True, DaemonCLI.guess_type('True'))
        self.assertEqual(False, DaemonCLI.guess_type('FALSE'))
        self.assertEqual(False, DaemonCLI.guess_type('false'))
        self.assertEqual(False, DaemonCLI.guess_type('False'))

    def test_get_params(self):
        test_params = [
            'b64address=VdNmakxFORPSyfCprAD/eDDPk5TY9QYtSA==',
            'name=test',
            'amount=5.3',
            'n=5',
            'address=bY13xeAjLrsjP4KGETwStK2a9UgKgXVTXu',
            't=true',
            'f=False',
        ]
        test_r = {
            'b64address': 'VdNmakxFORPSyfCprAD/eDDPk5TY9QYtSA==',
            'name': 'test',
            'amount': 5.3,
            'n': 5,
            'address': 'bY13xeAjLrsjP4KGETwStK2a9UgKgXVTXu',
            't': True,
            'f': False,
        }
        args_tup, kw_dict = DaemonCLI.parse_params(test_params)
        self.assertDictEqual(test_r, kw_dict)
        self.assertTupleEqual(args_tup, ())

