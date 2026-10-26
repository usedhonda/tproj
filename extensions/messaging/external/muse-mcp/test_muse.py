import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('muse_adapter', Path(__file__).with_name('muse.py'))
muse = importlib.util.module_from_spec(spec); spec.loader.exec_module(muse)


class MuseTests(unittest.TestCase):
    def config(self, root):
        return dict(service_id='muse', address='muse', participant_id='muse.service',
                    service_token='fixture-secret', binding_generation='fixture-generation',
                    allowed_addresses=['project.cc'], read_only=True,
                    host_socket=str(root/'host.sock'), bridge_socket=str(root/'bridge.sock'))

    def observed(self):
        scope = ['project.cc']
        return dict(service_id='muse', address='muse', participant_id='muse.service',
            binding_generation='fixture-generation', incarnation='incarnation',
            binding_id='muse.service', allowed_addresses=scope, policy_state='valid',
            policy_revision=hashlib.sha256(json.dumps(scope, separators=(',', ':')).encode()).hexdigest())

    def test_catalog_has_only_mailbox_tools_and_no_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = muse.MuseRuntime(self.config(Path(tmp)))
            server = runtime.server()
            init = server.handle(dict(jsonrpc='2.0', id=1, method='initialize', params={}))
            self.assertNotIn('events', init['result']['capabilities'])
            self.assertFalse(server.event_pump_enabled)
            self.assertIsNone(runtime.state_path)
            with self.assertRaises(muse.common.RuntimeConfigError): runtime.events()
            listed = server.handle(dict(jsonrpc='2.0', id=2, method='tools/list'))
            self.assertEqual({x['name'] for x in listed['result']['tools']}, muse.TOOLS)
            self.assertEqual(server.handle(dict(id=3, method='events/list'))['error']['code'], -32601)
            self.assertEqual(server.handle(dict(id=4, method='tools/call',
                params={'name': 'tproj_repo_read', 'arguments': {}}))['error']['code'], -32601)

    def test_tokenless_child_and_parent_only_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self.config(Path(tmp))
            for key in ('service_token', 'binding_generation', 'host_socket'):
                config.pop(key)
            calls = []
            attested = self.observed()
            def bridge(path, request):
                calls.append(request)
                if request['op'] == 'whoami': return dict(attested)
                return {'participants': [{'address': 'project.cc', 'online': True}]}
            with patch.object(muse.common, '_bridge_rpc', side_effect=bridge):
                server = muse.proxy_server(config)
                out = server.tools.dispatch('tproj_list', {})
                self.assertEqual(out['participants'][0]['address'], 'project.cc')
                forwarded = [r['request'] for r in calls if r['op'] == 'call']
                self.assertTrue(forwarded)
                self.assertFalse(any({'service_id', 'service_token', 'address', 'binding_generation'} & r.keys() for r in forwarded))
                with self.assertRaises(muse.MailboxToolError):
                    server.tools.dispatch('tproj_send', dict(target='project.cc', body='do not send', submission_id='fixture'))
                self.assertFalse(any(r.get('request', {}).get('op') == 'service_send' for r in calls))
                attested['binding_generation'] = 'rotated'
                with self.assertRaises(muse.MailboxToolError): server.tools.dispatch('tproj_list', {})
                config['service_token'] = 'not-allowed'
                with self.assertRaises(muse.common.RuntimeConfigError): muse.proxy_server(config)

    def test_parent_denies_writes_and_foreign_identity_is_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self.config(Path(tmp)); config['bridge_socket'] = None
            runtime = muse.MuseRuntime(config)
            calls = []
            with patch.object(muse.common, 'socket_rpc', side_effect=lambda socket, request: calls.append(request) or {}):
                for op in ('service_send', 'service_reply', 'service_ack', 'service_begin_present', 'service_repo_read'):
                    with self.assertRaises(muse.MailboxToolError): runtime._request({'op': op})
                self.assertEqual(calls, [])
                runtime._request(dict(op='service_list', service_id='kai', service_token='foreign'))
            self.assertEqual(calls[0]['service_id'], 'muse')
            self.assertEqual(calls[0]['service_token'], config['service_token'])
            wrong = dict(config, service_id='kai')
            with self.assertRaises(muse.common.RuntimeConfigError): muse.MuseRuntime(wrong)


class EnrollmentTests(unittest.TestCase):
    def test_existing_writable_workspace_recheck_preserves_policy_and_credentials(self):
        spec=importlib.util.spec_from_file_location('workspace_enrollment',Path(__file__).with_name('enroll.py'))
        enroll=importlib.util.module_from_spec(spec);spec.loader.exec_module(enroll)
        with tempfile.TemporaryDirectory() as tmp, patch.object(enroll,'host_ready'), patch.object(enroll,'register_participant',return_value=True):
            home=Path(tmp);root=home/'state';host=home/'host.json'
            host.write_text(json.dumps({'socket':str(home/'host.sock')}));host.chmod(0o600)
            enroll.prepare(home,host,root,['project.cc']);enroll.apply(host,root)
            parent=json.loads((root/'parent.json').read_text());parent['read_only']=False
            enroll.atomic(root/'parent.json',enroll.encoded(parent))
            cfg=json.loads(host.read_text());cfg['services']['muse'].update(read_only=False,messaging_scope='workspace')
            enroll.atomic(host,enroll.encoded(cfg));before=host.read_bytes()
            result=enroll.prepare(home,host,root,[])
            self.assertFalse(result['read_only'])
            self.assertFalse(enroll.apply(host,root,check=True)['changed'])
            self.assertTrue(enroll.key_enrollment(host,root))
            self.assertEqual(host.read_bytes(),before)
            self.assertEqual(json.loads((root/'parent.json').read_text())['service_token'],parent['service_token'])

    def test_prepare_apply_check_and_key_preserve_other_services(self):
        import base64
        spec=importlib.util.spec_from_file_location('muse_enrollment',Path(__file__).with_name('enroll.py'))
        enroll=importlib.util.module_from_spec(spec);spec.loader.exec_module(enroll)
        ready=patch.object(enroll,'host_ready');ready.start();self.addCleanup(ready.stop)
        registration=patch.object(enroll,'register_participant',return_value=True);registration.start();self.addCleanup(registration.stop)
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);root=home/'state';host=home/'host.json'
            original=dict(socket=str(home/'host.sock'),service={'unchanged':'legacy'},
                          services={'kai':{'address':'kai','participant_id':'kai-service','token':'retain'}})
            host.write_text(json.dumps(original));host.chmod(0o600)
            self.assertFalse(enroll.prepare(home,host,root,[])['host_changed'])
            before=host.read_bytes();parent=(root/'parent.json').read_bytes()
            client=json.loads((root/'client.json').read_text())
            self.assertNotIn('service_token',client);self.assertNotIn('binding_generation',client)
            self.assertFalse(enroll.apply(host,root,check=True)['enrolled'])
            self.assertEqual(host.read_bytes(),before)
            self.assertTrue(enroll.apply(host,root)['changed'])
            after=host.read_bytes()
            self.assertFalse(enroll.apply(host,root)['changed'])
            self.assertEqual(host.read_bytes(),after)
            self.assertEqual(json.loads(after)['services']['kai'],original['services']['kai'])
            self.assertEqual(json.loads(after)['service'],original['service'])
            enroll.prepare(home,host,root,[])
            self.assertEqual((root/'parent.json').read_bytes(),parent)
            with self.assertRaises(enroll.EnrollmentError):enroll.prepare(home,host,root,['other.cc'])
            public=home/'public.pub'
            raw=bytes.fromhex('0000000b')+b'ssh-ed25519'+bytes.fromhex('00000020')+b'x'*32
            public.write_text('ssh-ed25519 '+base64.b64encode(raw).decode()+' fixture')
            ssh=home/'.ssh';ssh.mkdir(mode=0o700)
            keys=ssh/'authorized_keys';keys.write_text(public.read_text()+'\n');keys.chmod(0o600)
            key_before=keys.read_bytes()
            with self.assertRaises(enroll.EnrollmentError):enroll.install_key(home,root,public)
            self.assertEqual(keys.read_bytes(),key_before)
            keys.write_text('');keys.chmod(0o600)
            self.assertTrue(enroll.install_key(home,root,public)['changed'])
            self.assertFalse(enroll.install_key(home,root,public)['changed'])
            self.assertIn('restrict,command=',keys.read_text())
            self.assertNotIn('fixture-secret',keys.read_text())


    def test_directory_registration_uses_owner_api_and_is_idempotent(self):
        import sys
        sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'unified'))
        from hub import Hub
        spec=importlib.util.spec_from_file_location('muse_enrollment_api',Path(__file__).with_name('enroll.py'))
        enroll=importlib.util.module_from_spec(spec);spec.loader.exec_module(enroll)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);hp=root/'hub.json'
            hp.write_text(json.dumps(dict(host_id='owner',socket='hub',admin_token='admin')));hp.chmod(0o600)
            hub=Hub(root/'hub.db',dict(host_id='owner',admin_token='admin',hosts={'owner':'host-token'}))
            self.addCleanup(hub.close)
            hub.directory_import(dict(admin_token='admin',services=[dict(participant_id='kai',address='kai',host_id='owner',kind='kai')]))
            before=dict(hub._row("SELECT * FROM participants WHERE participant_id='kai'"))
            calls=[]
            def rpc(path,req):
                calls.append((path,req['op']))
                return hub.directory_list() if path=='host' else hub.dispatch(req)
            config=dict(socket='host',host_id='owner')
            with patch.object(enroll,'rpc',side_effect=rpc):
                self.assertFalse(enroll.register_participant(config,hp,check=True))
                self.assertTrue(enroll.register_participant(config,hp))
                count=len([x for x in calls if x[1]=='directory_import'])
                self.assertTrue(enroll.register_participant(config,hp))
                self.assertEqual(len([x for x in calls if x[1]=='directory_import']),count)
                with self.assertRaises(enroll.EnrollmentError):enroll.register_participant(dict(config,host_id='foreign'),hp)
            self.assertEqual(dict(hub._row("SELECT * FROM participants WHERE participant_id='kai'")),before)
            self.assertEqual(hub.db.execute('SELECT COUNT(*) FROM messages').fetchone()[0],0)


if __name__ == '__main__': unittest.main()
