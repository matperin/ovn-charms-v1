# Copyright 2026 Canonical Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import os
import socket
import tempfile
import threading
import unittest

import charms.epa_client as epa_client


class FakeEPA(object):
    """Answer one request on a Unix socket the way the EPA daemon does."""

    def __init__(self, reply):
        self.reply = reply
        self.request = None
        self._tmpdir = tempfile.TemporaryDirectory()
        self.socket_path = os.path.join(self._tmpdir.name, 'epa.sock')
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(self.socket_path)
        self._server.listen(1)
        self._thread = threading.Thread(target=self._serve)
        self._thread.start()

    def _serve(self):
        conn, _ = self._server.accept()
        with conn:
            self.request = json.loads(conn.recv(1024))
            conn.sendall(json.dumps(self.reply).encode())

    def close(self):
        self._thread.join(timeout=5)
        self._server.close()
        self._tmpdir.cleanup()


class TestEPAClient(unittest.TestCase):

    def fake_epa(self, reply):
        epa = FakeEPA(reply)
        self.addCleanup(epa.close)
        return epa

    def test_is_available(self):
        epa = self.fake_epa({})
        self.assertTrue(epa_client.is_available(epa.socket_path))
        self.assertFalse(epa_client.is_available(epa.socket_path + '.gone'))
        # Unblock the server thread.
        epa_client.request({}, socket_path=epa.socket_path)

    def test_allocate_numa_cores(self):
        epa = self.fake_epa({
            'version': '1.0',
            'service_name': 'ovs-vswitchd',
            'pool': 'general',
            'preemption_policy': 'non-preemptive',
            'numa_node': 1,
            'num_of_cores': 8,
            'cores_allocated': '136-139,392-395',
            'total_available_cpus': 64,
            'remaining_available_cpus': 56,
        })
        self.assertEqual(
            epa_client.allocate_numa_cores(
                'ovs-vswitchd', 1, 8, socket_path=epa.socket_path),
            '136-139,392-395')
        self.assertEqual(epa.request, {
            'version': '1.0',
            'action': 'allocate_numa_cores',
            'service_name': 'ovs-vswitchd',
            'numa_node': 1,
            'num_of_cores': 8,
            'pool': 'general',
            'preemption_policy': 'non-preemptive',
        })

    def test_allocate_numa_cores_error(self):
        epa = self.fake_epa({
            'version': '1.0',
            'error': 'NUMA node 1 only has 3 eligible CPUs, but 8 were '
                     'requested',
        })
        with self.assertRaisesRegex(epa_client.EPAError, 'only has 3'):
            epa_client.allocate_numa_cores(
                'ovs-vswitchd', 1, 8, socket_path=epa.socket_path)

    def test_allocate_numa_cores_without_pools(self):
        # A daemon that predates CPU pools ignores the fields it does not
        # know, and would hand out isolated CPUs that may be another
        # service's.
        epa = self.fake_epa({
            'version': '1.0',
            'service_name': 'ovs-vswitchd',
            'numa_node': 1,
            'num_of_cores': 8,
            'cores_allocated': '136-143',
            'total_available_cpus': 64,
            'remaining_available_cpus': 56,
        })
        with self.assertRaisesRegex(epa_client.EPAError, 'CPU pools'):
            epa_client.allocate_numa_cores(
                'ovs-vswitchd', 1, 8, socket_path=epa.socket_path)

    def test_release_numa_cores(self):
        epa = self.fake_epa({
            'version': '1.0',
            'service_name': 'ovs-vswitchd',
            'numa_node': 0,
            'num_of_cores': -1,
            'cores_allocated': '',
            'total_available_cpus': 64,
            'remaining_available_cpus': 64,
        })
        self.assertEqual(
            epa_client.allocate_numa_cores(
                'ovs-vswitchd', 0, -1, socket_path=epa.socket_path),
            '')
        self.assertEqual(epa.request['num_of_cores'], -1)
