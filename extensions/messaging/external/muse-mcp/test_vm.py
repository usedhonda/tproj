import asyncio
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parent))
import vm_client
import vm_poll


@unittest.skipUnless(sys.version_info >= (3, 11), 'VM connector requires Python 3.11+')
class VMTests(unittest.TestCase):
    def test_empty_terminal_and_single_active_detection_survive_restart(self):
        row = dict(message_id='probe', thread_id='probe', sequence=8, state='accepted', expires_at=900)
        first = vm_poll.decide({}, {'pending':[row], 'next_cursor':8}, 100)
        self.assertEqual(first['decision'], 'wake')
        state = json.loads(json.dumps(first['state']))
        second = vm_poll.decide(state, {'pending':[row], 'next_cursor':8}, 115)
        self.assertEqual(second['decision'], 'silent')
        stalled = vm_poll.decide(state, {'pending':[row], 'next_cursor':8}, 281)
        self.assertEqual(stalled['reason'], 'tproj-consumer-stalled')
        self.assertEqual(vm_poll.decide(stalled['state'], {'pending':[row]}, 300)['decision'], 'silent')
        done = vm_poll.decide(state, {'pending':[dict(row,state='presented')], 'next_cursor':8}, 150)
        self.assertNotIn('active', done['state']); self.assertEqual(done['state']['cursor'],8)
        self.assertEqual(vm_poll.decide(done['state'], {'pending':[], 'next_cursor':8}, 200)['decision'],'silent')

    def test_transport_failure_never_replays_uncertain_reply(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);ssh=root/'ssh';ssh.write_text('fixture');ssh.chmod(0o600)
            config=root/'client.json';config.write_text(json.dumps(dict(ssh_config=str(ssh),ssh_host='tproj-msg-muse')));config.chmod(0o600)
            args=root/'args.json';args.write_text(json.dumps(dict(message_id='original',body='fixture',submission_id='stable-reply')))
            async def fail(*a,**kw):raise TimeoutError()
            with patch.object(vm_client,'invoke',side_effect=fail) as invoke, contextlib.redirect_stdout(io.StringIO()) as output:
                rc=vm_client.main(['--config',str(config),'call-tool','--name','tproj_reply','--arguments-file',str(args)])
            self.assertEqual(rc,1);self.assertEqual(invoke.call_count,1)
            error=json.loads(output.getvalue())['error']
            self.assertEqual(error['outcome'],'unknown');self.assertEqual(error['submission_id'],'stable-reply')
            self.assertFalse(error['replayed'])

    def test_connection_outage_alert_once_preserves_active_state(self):
        state={'cursor':5,'active':{'message_id':'held','sequence':6,'notified_at':1}}
        with patch.object(vm_poll,'load_config',side_effect=OSError()):
            first=vm_poll.detect(Path('unused'),state)
            again=vm_poll.detect(Path('unused'),first['state'])
        self.assertEqual(first['decision'],'wake');self.assertEqual(again['decision'],'silent')
        self.assertEqual(again['state']['active'],state['active'])

class KeyPolicyTests(unittest.TestCase):
    def test_key_install_checks_current_write_policy_without_changing_enrollment(self):
        spec=importlib.util.spec_from_file_location('enroll_key',Path(__file__).with_name('enroll.py'))
        enroll=importlib.util.module_from_spec(spec);spec.loader.exec_module(enroll)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);host=root/'host.json'
            parent=dict(service_id='muse',address='muse',participant_id='muse-service',service_token='fixture',binding_generation='generation',allowed_addresses=['project.cdx'],read_only=False,bridge_socket='bridge')
            child={k:parent[k] for k in ('service_id','address','participant_id','bridge_socket','read_only')}
            for path,value in [(root/'parent.json',parent),(root/'client.json',child),(host,{'services':{'muse':enroll.service(parent)}})]:
                path.write_text(json.dumps(value));path.chmod(0o600)
            original=host.read_bytes()
            with patch.object(enroll,'host_ready'),patch.object(enroll,'register_participant',return_value=True):
                self.assertTrue(enroll.key_enrollment(host,root));self.assertEqual(host.read_bytes(),original)
                child['read_only']=True;(root/'client.json').write_text(json.dumps(child))
                with self.assertRaises(enroll.EnrollmentError):enroll.key_enrollment(host,root)


if __name__=='__main__':unittest.main()
