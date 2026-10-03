import importlib.util
import sys
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'messaging/unified'))
SPEC = importlib.util.spec_from_file_location('task_role_under_test', ROOT / 'messaging/unified/task_role.py')
task_role = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(task_role)


class TaskRoleContextTest(unittest.TestCase):
    def test_payload_native_context_is_forwarded(self):
        with patch.object(task_role.cli, 'native_conversation_context', return_value={}), \
             patch.object(task_role.cli, '_caller_request', return_value={'op':'task_context'}) as request:
            result = task_role._caller_request({'session_id':'payload-session'})
        self.assertEqual(result['conversation'], {'session_id':'payload-session'})
        request.assert_called_once_with('task_context')

    def test_conflicting_environment_context_is_rejected(self):
        with patch.object(task_role.cli, 'native_conversation_context', return_value={'session_id':'env-session'}), \
             patch.object(task_role.cli, '_caller_request', side_effect=AssertionError('must reject before request')):
            with self.assertRaisesRegex(ValueError, 'context conflict'):
                task_role._caller_request({'session_id':'payload-session'})

    def test_payload_context_reaches_task_context_for_bound_marker(self):
        with tempfile.TemporaryDirectory() as raw, patch.dict(task_role.os.environ, {
                'TPROJ_TASK_BINDING_DIR': raw, 'CODEX_THREAD_ID': '', 'CODEX_SESSION_ID': ''}), \
             patch.object(task_role.cli, 'native_conversation_context', return_value={}), \
             patch.object(task_role.cli, 'config', return_value={'socket':'fixture'}), \
             patch.object(task_role.cli, '_caller_request', return_value={'op':'task_context'}) as request, \
             patch.object(task_role.cli, 'rpc', return_value={'assigned':True, 'can_mutate':True}) as rpc:
            task_role.binding_marker('payload-session').parent.mkdir(parents=True, exist_ok=True)
            task_role.binding_marker('payload-session').touch()
            result = task_role.context({'session_id':'payload-session'})
        self.assertTrue(result['can_mutate'])
        request.assert_called_once_with('task_context')
        self.assertEqual(rpc.call_args.args[1]['conversation'], {'session_id':'payload-session'})

    def test_conflicting_payload_roots_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'context conflict'):
            task_role.native_context({'session_id':'one', 'raw_event':{'session_id':'two'}})

    def test_context_conflict_is_restrictive_and_skips_rpc(self):
        with patch.dict(task_role.os.environ, {'CODEX_THREAD_ID':'', 'CODEX_SESSION_ID':''}), \
             patch.object(task_role.cli, 'native_conversation_context', return_value={}), \
             patch.object(task_role.cli, 'rpc', side_effect=AssertionError('must not call rpc')):
            result = task_role.context({'thread_id':'one', 'raw_event':{'conversation_id':'two'}})
        self.assertEqual(result, {'assigned':True, 'can_mutate':False, 'task_status':'authority_unavailable',
                                  'authority_error':'native_context_conflict', 'authority_phase':'context'})

    def test_authority_failures_are_fixed_categories(self):
        marker_root = tempfile.TemporaryDirectory()
        self.addCleanup(marker_root.cleanup)
        with patch.dict(task_role.os.environ, {'TPROJ_TASK_BINDING_DIR': marker_root.name,
                                                'CODEX_THREAD_ID':'bound', 'CODEX_SESSION_ID':''}), \
             patch.object(task_role.cli, 'native_conversation_context', return_value={}), \
             patch.object(task_role.cli, 'config', side_effect=task_role.cli.ClientError('offline')):
            task_role.binding_marker('bound').parent.mkdir(parents=True, exist_ok=True)
            task_role.binding_marker('bound').touch()
            result = task_role.context({'session_id':'bound'})
        self.assertEqual(result['authority_error'], 'config_unavailable')
        self.assertEqual(result['authority_phase'], 'config')
        self.assertNotIn('offline', str(result))


if __name__ == '__main__':
    unittest.main()
