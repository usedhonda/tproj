#!/usr/bin/env python3
"""Credential-free, fixed SSH/stdio MCP client for an enrolled Muse mailbox."""
from __future__ import annotations
import argparse
import asyncio
import json
import os
from pathlib import Path
import stat
import sys

TOOLS = frozenset(('tproj_list', 'tproj_status', 'tproj_send', 'tproj_inbox',
                  'tproj_message', 'tproj_reply', 'tproj_ack', 'tproj_diagnose'))
WRITES = frozenset(('tproj_send', 'tproj_reply', 'tproj_ack'))


def load_config(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('owner-only client configuration required')
    config = json.loads(path.read_text())
    if set(config) != {'ssh_config', 'ssh_host'} or config['ssh_host'] != 'tproj-msg-muse':
        raise ValueError('fixed Muse SSH profile required')
    ssh_config = Path(config['ssh_config']).expanduser()
    info = ssh_config.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('owner-only SSH configuration required')
    return ssh_config


async def invoke(ssh_config, name=None, arguments=None, cursor=None):
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters
    # SDK's default child environment drops proxy context. Never fall back to
    # another hook's saved short-lived proxy authorization. Inherit only this
    # invocation's native runtime proxy, ephemerally, as ordinary subprocesses do.
    proxy = os.environ.get('HTTPS_PROXY')
    if not proxy:
        raise ValueError('current runtime proxy context required')
    params = StdioServerParameters(command='ssh', args=[
        '-F', str(ssh_config), '-T', '-o', 'BatchMode=yes',
        '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=yes',
        '-o', 'ConnectTimeout=5', 'tproj-msg-muse'], env={'HTTPS_PROXY': proxy})
    # Legacy mode performs initialize once; never retry a tool call.
    async with asyncio.timeout(20):
        async with Client(params, mode='legacy', read_timeout_seconds=8) as client:
            if name is None:
                result = await client.list_tools(cursor=cursor)
                if any(tool.name not in TOOLS for tool in result.tools):
                    raise ValueError('unexpected server tool')
            else:
                if name not in TOOLS:
                    raise ValueError('tool not allowed')
                result = await client.call_tool(name, arguments)
            return result.model_dump(mode='json', by_alias=True, exclude_none=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    sub = parser.add_subparsers(dest='command', required=True)
    listing = sub.add_parser('list-tools'); listing.add_argument('--cursor')
    calling = sub.add_parser('call-tool')
    calling.add_argument('--name', choices=sorted(TOOLS), required=True)
    calling.add_argument('--arguments-file', type=Path, required=True)
    args = parser.parse_args(argv)
    name = getattr(args, 'name', None)
    arguments = {}
    phase = 'configuration'
    try:
        config = load_config(args.config)
        if name:
            arguments = json.loads(args.arguments_file.read_text())
            if not isinstance(arguments, dict):
                raise ValueError('arguments object required')
        phase = 'transport'
        result = asyncio.run(invoke(config, name, arguments, getattr(args, 'cursor', None)))
        print(json.dumps(result, ensure_ascii=False))
        return 1 if result.get('isError') else 0
    except (Exception, BaseExceptionGroup) as exc:
        # SSH/MCP exceptions may include remote text. Do not echo it or traceback.
        result = {'isError': True, 'error': {'code': 'unavailable' if phase == 'transport' else 'invalid_config',
                  'phase': phase, 'outcome': 'unknown' if phase == 'transport' and name in WRITES else 'not_confirmed',
                  'exception_type': type(exc).__name__, 'replayed': False}}
        if name in ('tproj_send', 'tproj_reply') and isinstance(arguments.get('submission_id'), str):
            result['error']['submission_id'] = arguments['submission_id']
        print(json.dumps(result)); return 1


if __name__ == '__main__':
    raise SystemExit(main())
