#!/usr/bin/env python3
"""Events-free Muse mailbox adapter; credentials stay in the launchd parent."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

SHARED = Path(__file__).resolve().parent.parent / 'kai-mcp'
sys.path.insert(0, str(SHARED))
import runtime as common
from connection import ServiceIdentity, FixedConnectionAuthorizer, ConnectionBindingError
from mailbox_tools import MailboxTools, MailboxToolError
from server import MCPServer, run_stdio

TOOLS = {'tproj_list', 'tproj_status', 'tproj_send', 'tproj_inbox',
         'tproj_message', 'tproj_reply', 'tproj_ack', 'tproj_diagnose'}
READ_OPS = {'service_whoami', 'service_list', 'service_status',
            'service_inbox', 'service_message', 'service_diagnose'}
MAILBOX_OPS = READ_OPS | {'service_send', 'service_reply', 'service_ack', 'service_begin_present'}


def identity(config):
    if (config.get('service_id') != 'muse' or config.get('address') != 'muse'
            or not isinstance(config.get('participant_id'), str) or not config['participant_id']):
        raise common.RuntimeConfigError('fixed Muse enrollment required')
    read_only = config.get('read_only', True)
    if type(read_only) is not bool:
        raise common.RuntimeConfigError('explicit read-only policy must be boolean')
    return read_only


class MuseRuntime(common.ServiceRuntime):
    def __init__(self, config):
        self.read_only = identity(config)
        super().__init__(config, events_enabled=False)

    def _request(self, request):
        op = request.get('op')
        if op not in MAILBOX_OPS or (self.read_only and op not in READ_OPS):
            raise MailboxToolError('scope_denied', 'Muse mailbox is read-only or operation is unavailable')
        return super()._request(request)

    def server(self):
        authorizer = FixedConnectionAuthorizer(self.binding, self._attest)
        tools = MailboxTools(service_id='muse', service_address='muse',
            service_token=self.binding.token, authorizer=authorizer.authorize, host_call=self._request)
        server = MCPServer(tools=tools, tool_names=TOOLS)
        server.event_pump_enabled = False
        return server


def proxy_server(config):
    """Tokenless SSH child. The parent stamps all private Host credentials."""
    read_only = identity(config)
    if 'service_token' in config or 'token' in config or 'binding_generation' in config:
        raise common.RuntimeConfigError('SSH child config must not contain credentials or generation')
    path = Path(common._required(config.get('bridge_socket'), 'bridge_socket')).expanduser()

    def attest():
        observed = common._bridge_rpc(path, {'op': 'whoami'})
        if (not isinstance(observed, dict) or observed.get('service_id') != 'muse'
                or observed.get('address') != 'muse'
                or observed.get('participant_id') != config['participant_id']):
            raise ConnectionBindingError('Muse bridge identity mismatch')
        return observed

    initial = attest()
    public = ServiceIdentity('muse', 'muse', config['participant_id'],
                             tuple(initial.get('allowed_addresses') or ()), initial['binding_generation'])
    authorizer = FixedConnectionAuthorizer(public, attest)

    def call(request):
        op = request.get('op')
        if op not in MAILBOX_OPS or (read_only and op not in READ_OPS):
            raise MailboxToolError('scope_denied', 'Muse mailbox is read-only or operation is unavailable')
        # Omit even empty credential-shaped fields from the child wire.
        forwarded = {key: value for key, value in request.items()
                     if key not in ('service_id', 'service_token', 'address', 'binding_generation')}
        return common._bridge_rpc(path, {'op': 'call', 'request': forwarded})

    tools = MailboxTools(service_id='muse', service_address='muse', service_token='',
                         authorizer=authorizer.authorize, host_call=call)
    server = MCPServer(tools=tools, tool_names=TOOLS)
    server.event_pump_enabled = False
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description='Run the enrolled Muse mailbox without events')
    parser.add_argument('--config', required=True)
    parser.add_argument('--bridge', action='store_true')
    args = parser.parse_args(argv)
    try:
        config = common.load_config(args.config)
        identity(config)
        if args.bridge:
            return common.bridge(config, runtime_factory=MuseRuntime)
        return run_stdio(proxy_server(config))
    except (common.RuntimeConfigError, ConnectionBindingError, MailboxToolError) as exc:
        print('Muse mailbox unavailable: ' + type(exc).__name__, file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
