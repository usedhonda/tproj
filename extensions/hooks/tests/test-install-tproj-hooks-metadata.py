#!/usr/bin/env python3
"""Focused trust metadata checks for the Codex hook installer."""

import runpy
import copy
import unittest
from pathlib import Path


INSTALLER = Path(__file__).resolve().parents[1] / "install-tproj-hooks"
installer = runpy.run_path(str(INSTALLER))
hook_metadata = installer["hook_metadata"]


class HookMetadataTest(unittest.TestCase):
    def test_native_matcher_migration_preserves_custom_hooks(self):
        for platform in ('claude', 'codex'):
            original = installer['merge']({}, platform)
            old = copy.deepcopy(original)
            for entries in old['hooks'].values():
                for entry in entries:
                    if 'matcher' in entry:
                        entry['matcher'] = entry['matcher'].replace('Bash|exec|exec_command|', 'Bash|')
            custom = copy.deepcopy(old['hooks']['PreToolUse'][0])
            custom['hooks'].append({'type': 'command', 'command': 'custom-user-hook'})
            old['hooks']['PreToolUse'].append(custom)
            merged = installer['merge'](old, platform)
            self.assertIn(custom, merged['hooks']['PreToolUse'])
            merged['hooks']['PreToolUse'].remove(custom)
            self.assertEqual(merged, original)
            self.assertEqual(installer['merge'](copy.deepcopy(merged), platform), original)

    def test_failure_hook_is_platform_specific(self):
        cc=installer['merge']({},'claude')['hooks']
        cdx=installer['merge']({},'codex')['hooks']
        self.assertTrue(any('tproj-formal-task-guard --event failure' in installer['command_of'](entry) for entry in cc['PostToolUseFailure']))
        self.assertNotIn('PostToolUseFailure',cdx)
        for event in ('PreToolUse','PostToolUse'):
            formal=next(entry for entry in cdx[event] if 'tproj-formal-task-guard' in installer['command_of'](entry))
            self.assertIn('exec',formal['matcher'].split('|'))
        self.assertTrue(any('tproj-formal-task-guard' in installer['command_of'](entry) for entry in cdx['PostToolUse']))

    def test_optional_hook_is_accepted_with_required_hooks(self):
        source = Path("/tmp/tproj-hooks.json")
        names = (
            "tproj-inbox-record",
            "tproj-inbox-check",
            "tproj-completion-guard",
            "tproj-mutation-guard",
            "tproj-formal-task-guard",
            "tproj-codex-cache-observer",
        )
        hooks = [
            {
                "key": name,
                "sourcePath": str(source),
                "command": f"/tmp/bin/{name}",
                "currentHash": "sha256:abc",
            }
            for name in names
        ]
        formal=next(h for h in hooks if h['key']=='tproj-formal-task-guard')
        formal['command'] += ' --event pretool'
        post=dict(formal,key='formal-post',command=formal['command'].replace('pretool','posttool'))
        with self.assertRaises(RuntimeError):hook_metadata({'result':{'data':[{'hooks':hooks}]}},source)
        hooks.append(post)
        found = hook_metadata({"result": {"data": [{"hooks": hooks}]}}, source)
        self.assertEqual({entry["key"] for entry in found}, set(names)|{"formal-post"})


if __name__ == "__main__":
    unittest.main()
