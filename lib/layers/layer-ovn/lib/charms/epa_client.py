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
"""Client for the EPA orchestrator, which hands out the CPUs of a host.

The ``epa-orchestrator`` snap keeps track of which CPUs it has handed to
which service, so services sharing a host do not end up pinned to the same
CPUs.  It is installed by the ``epa-orchestrator`` subordinate charm and
answers requests on a Unix socket.
"""
import json
import os
import socket

EPA_SOCKET = '/var/snap/epa-orchestrator/current/data/epa.sock'
EPA_API_VERSION = '1.0'

# Ordinary CPUs balanced by the scheduler, as opposed to the default
# ``isolated`` pool taken from the ``isolcpus`` kernel parameter.
EPA_POOL_GENERAL = 'general'

# Only hand out CPUs no other service holds, and keep handing out the same
# ones on every request, rather than taking them back from other services.
EPA_POLICY_NON_PREEMPTIVE = 'non-preemptive'


class EPAError(Exception):
    """The EPA orchestrator could not satisfy a request."""


def is_available(socket_path=EPA_SOCKET):
    """Whether the EPA orchestrator is installed on this host.

    :param socket_path: Path to the EPA orchestrator socket.
    :type socket_path: str
    :rtype: bool
    """
    return os.path.exists(socket_path)


def request(payload, socket_path=EPA_SOCKET):
    """Send a request to the EPA orchestrator.

    :param payload: Request
    :type payload: Dict[str,any]
    :param socket_path: Path to the EPA orchestrator socket.
    :type socket_path: str
    :returns: Reply
    :rtype: Dict[str,any]
    :raises: EPAError
    """
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.connect(socket_path)
            sock.sendall(json.dumps(payload).encode())
            # The daemon closes the connection once it has replied.
            reply = b''
            while True:
                data = sock.recv(4096)
                if not data:
                    break
                reply += data
    except OSError as e:
        raise EPAError('Unable to talk to the EPA orchestrator on {}: {}'
                       .format(socket_path, e))
    reply = json.loads(reply)
    if reply.get('error'):
        raise EPAError('EPA orchestrator request {} failed: {}'
                       .format(payload, reply['error']))
    return reply


def allocate_numa_cores(service_name, numa_node, num_of_cores,
                        socket_path=EPA_SOCKET):
    """Hold general pool CPUs of a NUMA node for a service.

    :param service_name: Name the CPUs are held under.
    :type service_name: str
    :param numa_node: NUMA node to take the CPUs from.
    :type numa_node: int
    :param num_of_cores: Number of CPUs, or -1 to release the CPUs held on
                         the NUMA node.
    :type num_of_cores: int
    :param socket_path: Path to the EPA orchestrator socket.
    :type socket_path: str
    :returns: CPU list of the CPUs held, for example ``8-11,72-75``.
    :rtype: str
    :raises: EPAError
    """
    reply = request({
        'version': EPA_API_VERSION,
        'action': 'allocate_numa_cores',
        'service_name': service_name,
        'numa_node': numa_node,
        'num_of_cores': num_of_cores,
        'pool': EPA_POOL_GENERAL,
        'preemption_policy': EPA_POLICY_NON_PREEMPTIVE,
    }, socket_path=socket_path)
    if num_of_cores > 0 and (
            reply.get('pool') != EPA_POOL_GENERAL or
            reply.get('preemption_policy') != EPA_POLICY_NON_PREEMPTIVE):
        # A daemon that predates them ignores the fields it does not know.
        raise EPAError('The EPA orchestrator does not support CPU pools '
                       'and non-preemptive allocations, refresh the '
                       'epa-orchestrator snap.')
    return reply['cores_allocated']
