"""Synthetic identities only. All sockets, subprocesses and network blocked."""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'unified'))
sys.path.append(str(Path(__file__).resolve().parents[1]/'external/kai-mcp'))
import unittest, tempfile, json, socket, subprocess, importlib.util, copy, os, sqlite3, time
from dataclasses import replace, asdict
import telegram_ingress as ingress
import telegram_runtime as runtime
from host import Host
from hub import Hub
from protocol import HubError

def forbidden(*a,**kw):raise AssertionError('REAL IO FORBIDDEN')
socket.socket=forbidden;subprocess.run=forbidden;runtime.urllib.request.urlopen=forbidden

class AgentsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='telegram-agents-');self.addCleanup(self.tmp.cleanup)
        self.private=ingress.TelegramOwnerBinding('private-fixture','owner-fixture',101,202,202,'kai',1,2000000000)
        self.group=replace(self.private,binding_id='group-fixture',chat_id=-100123,chat_type='supergroup')
        self.settings={'owner_binding':asdict(self.private),'group_binding':asdict(self.group)}
        self.now=1000

    def raw(self,group=True,**changes):
        chat={'id':self.group.chat_id,'type':'supergroup','title':'Agents'} if group else {'id':202,'type':'private'}
        message={'message_id':7,'from':{'id':202,'is_bot':False},'chat':chat,'text':'fixture text'}
        message.update(changes)
        return json.dumps({'update_id':9,'message':message}).encode()

    def admit(self,raw,settings=None):
        binding=ingress.select_binding(settings or self.settings,raw)
        return ingress.TelegramIngressAuthority(binding).admit_authenticated_poll(raw,verified_bot_id=101,now=self.now)

    def test_approved_group_owner_only_and_private_v1_unchanged(self):
        group=self.admit(self.raw());self.assertEqual(group.envelope()['external_origin']['version'],2)
        old_binding=asdict(self.private);old_binding.pop('chat_type')
        old=ingress.TelegramIngressAuthority(ingress.TelegramOwnerBinding(**old_binding)).admit_authenticated_poll(self.raw(False),verified_bot_id=101,now=self.now)
        self.assertEqual(self.admit(self.raw(False)).envelope(),old.envelope())

    def test_unrelated_group_and_wrong_chat_type_denied(self):
        for chat in [{'id':-100999,'type':'supergroup','title':'Agents'},{'id':-100123,'type':'group','title':'Agents'}]:
            with self.subTest(chat=chat),self.assertRaises(ingress.TelegramIngressError):self.admit(self.raw(chat=chat))

    def test_regular_group_type_uses_exact_group_origin_and_reply_route(self):
        binding=replace(self.group,chat_type='group')
        settings=dict(self.settings,group_binding=asdict(binding))
        raw=self.raw(chat={'id':binding.chat_id,'type':'group','title':'Agents'})
        intent=self.admit(raw,settings)
        self.assertEqual(intent.envelope()['external_origin']['chat_type'],'group')
        ingress.validate_origin(intent.envelope()['external_origin'],intent.envelope(),binding,now=self.now)
        relay,journal,submits,sends=self.relay(binding)
        relay.receive(raw,now=self.now,authenticated_poll_bot_id=101)
        relay.deliver_reply({'message_id':'regular-group-reply','in_reply_to':intent.message_id,
            'thread_id':intent.message_id,'sender_endpoint':'kai-fixture','body':'fixture response'},now=self.now)
        self.assertEqual(sends[0]['chat_id'],binding.chat_id)

    def test_spoofed_or_peer_sender_and_forwarded_message_denied(self):
        cases=[{'from':{'id':303,'is_bot':False}},{'from':{'id':202,'is_bot':True}},
               {'from':{'id':True,'is_bot':False}},{'sender_chat':{'id':-100123}},
               {'via_bot':{'id':101}},{'forward_origin':{'type':'user'}}]
        for fields in cases:
            with self.subTest(fields=fields),self.assertRaises(ingress.TelegramIngressError):self.admit(self.raw(**fields))

    def test_group_cannot_change_owner_bot_target_or_reuse_private_id(self):
        for key,value in [('user_id',303),('bot_id',404),('target','other'),('binding_id','private-fixture')]:
            settings=copy.deepcopy(self.settings);settings['group_binding'][key]=value
            with self.subTest(key=key),self.assertRaises(ingress.TelegramIngressError):ingress.approved_bindings(settings)

    def test_origin_group_type_and_chat_are_verified(self):
        intent=self.admit(self.raw());envelope=intent.envelope()
        ingress.validate_origin(envelope['external_origin'],envelope,self.group,now=self.now)
        for key,value in [('chat_id',-100999),('chat_type','group'),('user_id',303),('version',1)]:
            changed=copy.deepcopy(envelope);changed['external_origin'][key]=value
            with self.subTest(key=key),self.assertRaises(ingress.TelegramIngressError):ingress.validate_origin(changed['external_origin'],changed,self.group,now=self.now)

    def relay(self,binding):
        journal=ingress.TelegramIngressJournal(str(Path(self.tmp.name)/(binding.binding_id+'.db')));self.addCleanup(journal.close)
        submits=[];sends=[]
        def submit(envelope):submits.append(envelope);return {'message_id':envelope['message_id'],'state':'accepted'}
        def send(payload):sends.append(payload);return {'chat_id':payload['chat_id'],'message_id':50}
        relay=ingress.TelegramMailboxRelay(ingress.TelegramIngressAuthority(binding),journal,lambda:binding,submit,send,kai_endpoint='kai-fixture')
        return relay,journal,submits,sends

    def test_group_and_private_replies_exact_chat_message_and_dedupe(self):
        for binding,is_group in [(self.group,True),(self.private,False)]:
            relay,journal,submits,sends=self.relay(binding)
            first=relay.receive(self.raw(is_group),now=self.now,authenticated_poll_bot_id=101)
            second=relay.receive(self.raw(is_group),now=self.now,authenticated_poll_bot_id=101)
            self.assertTrue(second['duplicate']);self.assertEqual(len(submits),1)
            reply={'message_id':'reply-fixture','in_reply_to':first['message_id'],'thread_id':first['message_id'],'sender_endpoint':'kai-fixture','body':'fixture response'}
            relay.deliver_reply(reply,now=self.now);result=relay.deliver_reply(reply,now=self.now)
            self.assertTrue(result['duplicate']);self.assertEqual(sends,[{'chat_id':binding.chat_id,'text':'fixture response','reply_to_message_id':7}])
            forged=dict(reply,message_id='spoof-reply',sender_endpoint='peer-agent')
            with self.assertRaises(ingress.TelegramIngressError):relay.deliver_reply(forged,now=self.now)
            self.assertEqual(len(sends),1)

    def test_discovery_is_metadata_only_owner_exact_marker_and_no_grant(self):
        settings={'owner_binding':asdict(self.private),'group_discovery':{'marker':'fixture-marker-unique','expires_at':1100}}
        raw=self.raw(text='fixture-marker-unique')
        found=ingress.observe_group_candidate(settings,raw,verified_bot_id=101,now=self.now)
        self.assertEqual(found['chat_id'],-100123);self.assertNotIn('body',found);self.assertNotIn('text',found)
        with self.assertRaises(ingress.TelegramIngressError):self.admit(raw,settings)
        for bad in [self.raw(text='different'),self.raw(text='fixture-marker-unique',**{'from':{'id':303,'is_bot':False}})]:
            self.assertIsNone(ingress.observe_group_candidate(settings,bad,verified_bot_id=101,now=self.now))
        self.assertIsNone(ingress.observe_group_candidate(settings,raw,verified_bot_id=101,now=1101))

    def test_host_revalidates_group_and_hub_pins_attester(self):
        host=Host.__new__(Host);captured=[]
        host.config={'services':{'telegram':{'telegram_ingress':dict(self.settings,mode='long_poll'),'binding_generation':'FAKE','allowed_addresses':['kai']}}}
        host.service=lambda *a,**kw:{'endpoint_id':'telegram-fixture'}
        host.submit=lambda ep,request,**kw:captured.append(kw['trusted_origin']) or {'message_id':request['submission_id'],'state':'accepted'}
        request={'op':'service_telegram_ingress','service_id':'telegram','raw_update':self.raw().decode(),'verified_bot_id':101}
        host.dispatch(request,1,os.getuid());self.assertEqual(captured[0]['chat_id'],-100123)
        with self.assertRaises(HubError):host.dispatch(dict(request,raw_update=self.raw(**{'from':{'id':303,'is_bot':False}}).decode()),1,os.getuid())
        self.assertEqual(len(captured),1)
        hub=Hub.__new__(Hub);hub._now=lambda:self.now
        hub.config={'telegram_ingress_bindings':{self.group.binding_id:{'host_id':'host-fixture','participant_id':'telegram-fixture','owner_binding':asdict(self.group)}}}
        envelope=self.admit(self.raw()).envelope();sender={'host_id':'host-fixture','participant_id':'telegram-fixture'}
        self.assertTrue(hub._telegram_origin_active(envelope['external_origin'],envelope,sender))
        self.assertFalse(hub._telegram_origin_active(envelope['external_origin'],envelope,dict(sender,participant_id='other')))

    def real_submit_fixture(self,legacy=False):
        hub=Hub(Path(self.tmp.name)/'real-hub.db',{'host_id':'local','hosts':{'local':'FAKE'},
            'telegram_ingress_bindings':{b.binding_id:{'host_id':'local','participant_id':'telegram-principal','owner_binding':asdict(b)} for b in [self.private,self.group]}})
        self.addCleanup(hub.close)
        for ident,address,platform in [('telegram-principal','telegram','telegram'),('kai-principal','kai','kai')]:
            hub.db.execute('INSERT INTO participants VALUES(?,?,?,?,?)',(ident,None,address,'local',platform))
            hub.db.execute('INSERT INTO endpoints VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(ident+'-ep',ident,'local',address,'',0,'0','fixture-'+address,platform,'fixture-'+address,time.time(),0))
        host=Host.__new__(Host)
        host.db=sqlite3.connect(Path(self.tmp.name)/'real-host.db');host.db.row_factory=sqlite3.Row;self.addCleanup(host.db.close)
        host.db.execute('CREATE TABLE submissions(message_id TEXT PRIMARY KEY,endpoint_id TEXT NOT NULL,envelope TEXT NOT NULL)')
        host.config={'services':{'telegram':{'telegram_ingress':dict(self.settings,mode='long_poll'),
            'binding_generation':'FAKE','allowed_addresses':['kai']}}}
        if legacy:host.config['service']={'allowed_addresses':['wrong-legacy-target']}
        host.service=lambda *a,**kw:{'endpoint_id':'telegram-principal-ep','service_id':'telegram'}
        calls=[]
        def call(op,**kwargs):
            calls.append((op,kwargs))
            return hub.dispatch(dict(kwargs,op=op,host_id='local',host_token='FAKE'))
        host.hub=call
        return host,hub,calls

    def test_real_host_submit_to_hub_preserves_dedicated_telegram_policy(self):
        host,hub,calls=self.real_submit_fixture()
        for is_group in [False,True]:
            raw=self.raw(is_group)
            result=host.dispatch({'op':'service_telegram_ingress','service_id':'telegram',
                'raw_update':raw.decode(),'verified_bot_id':101},1,os.getuid())
            row=hub.db.execute('SELECT target_address,external_origin_json FROM messages WHERE message_id=?',(result['message_id'],)).fetchone()
            self.assertEqual(row['target_address'],'kai')
            self.assertEqual(json.loads(row['external_origin_json'])['chat_id'],self.group.chat_id if is_group else self.private.chat_id)
            self.assertEqual(calls[-1][1]['authorized_targets'],['kai'])
        self.assertEqual(host.db.execute('SELECT count(*) FROM submissions').fetchone()[0],2)
        self.assertEqual(hub.db.execute('SELECT count(*) FROM messages').fetchone()[0],2)

    def test_real_submit_does_not_select_legacy_or_raw_message_identity(self):
        host,hub,calls=self.real_submit_fixture(legacy=True)
        raw=self.raw(service_id='openclaw',address='forged',service_token='forged')
        result=host.dispatch({'op':'service_telegram_ingress','service_id':'telegram',
            'raw_update':raw.decode(),'verified_bot_id':101},1,os.getuid())
        self.assertEqual(calls[-1][1]['authorized_targets'],['kai'])
        self.assertEqual(hub.db.execute('SELECT sender_endpoint FROM messages WHERE message_id=?',(result['message_id'],)).fetchone()[0],'telegram-principal-ep')
        self.assertNotIn('service_id',calls[-1][1]['message'])

    def make_runtime(self,settings,updates,*,kai_endpoint='kai-fixture'):
        config=dict(settings,journal=str(Path(self.tmp.name)/'runtime.db'),host_socket=str(Path(self.tmp.name)/'never.sock'),kai_endpoint=kai_endpoint,service_id='telegram',service_token='FAKE',address='telegram',binding_generation='FAKE')
        p=Path(self.tmp.name)/'config.json';p.write_text(json.dumps(config));p.chmod(0o600)
        api_calls=[];host_calls=[];payloads=[]
        class API:
            def call(api,method,payload):
                api_calls.append(method)
                payloads.append((method,payload))
                if method=='getUpdates':return updates
                if method=='sendMessage':return {'message_id':80,'chat':{'id':payload['chat_id']}}
                raise AssertionError(method)
        def host_call(path,req):
            host_calls.append(req['op'])
            if req['op']=='service_telegram_ingress':
                intent=self.admit(req['raw_update'].encode(),settings)
                return {'message_id':intent.message_id,'state':'accepted'}
            raise AssertionError(req['op'])
        rt=runtime.TelegramRuntime(str(p),api=API(),host_call=host_call,clock=lambda:self.now);self.addCleanup(rt.journal.close);rt.verified_bot_id=101
        rt.fixture_payloads=payloads
        return rt,api_calls,host_calls

    def test_existing_poller_observes_candidate_without_submitting_group(self):
        settings={'owner_binding':asdict(self.private),'group_discovery':{'marker':'fixture-marker-unique','expires_at':1100}}
        rt,api,host=self.make_runtime(settings,[json.loads(self.raw(text='fixture-marker-unique'))])
        rt.receive_once();self.assertEqual(api,['getUpdates']);self.assertEqual(host,[])
        self.assertEqual(rt.journal.db.execute('SELECT chat_id FROM telegram_group_candidates').fetchall(),[(-100123,)])
        self.assertEqual(rt.journal.db.execute('SELECT count(*) FROM telegram_intents').fetchone()[0],0)

    def test_runtime_routes_group_and_private(self):
        group=json.loads(self.raw());private=json.loads(self.raw(False));private['update_id']=10
        rt,api,host=self.make_runtime(self.settings,[group,private]);rt.receive_once()
        self.assertEqual(host,['service_telegram_ingress','service_telegram_ingress'])
        self.assertEqual(rt.journal.db.execute('SELECT count(*) FROM telegram_intents').fetchone()[0],2)

    def test_revoked_group_does_not_stop_private(self):
        group=json.loads(self.raw());private=json.loads(self.raw(False));private['update_id']=10
        rt,api,host=self.make_runtime(self.settings,[group,private])
        p=Path(rt.config_path);config=json.loads(p.read_text());config['group_binding']['revoked']=True;p.write_text(json.dumps(config))
        rt.receive_once();self.assertEqual(host,['service_telegram_ingress'])

    def test_runtime_reply_uses_original_group_not_private_chat(self):
        rt,api,host=self.make_runtime(self.settings,[json.loads(self.raw())]);rt.receive_once()
        original=self.admit(self.raw()).message_id
        reply={'message_id':'runtime-reply','in_reply_to':original,'thread_id':original,'sender_endpoint':'kai-fixture','body':'fixture reply'}
        def response(op,**kw):
            if op=='service_inbox':return {'messages':[{'message_id':'runtime-reply','sequence':1}]}
            if op=='service_message':return reply
            if op=='service_ack':return {}
            raise AssertionError(op)
        rt.host=response;rt.replies_once()
        sends=[payload for method,payload in rt.fixture_payloads if method=='sendMessage']
        self.assertEqual(len(sends),1);self.assertEqual(sends[0]['chat_id'],-100123)
        self.assertEqual(sends[0]['reply_parameters']['message_id'],7)

    def reply_fixture(self):
        group=json.loads(self.raw());private=json.loads(self.raw(False));private['update_id']=10
        rt,api,host=self.make_runtime(self.settings,[group,private]);rt.receive_once()
        mids=[self.admit(json.dumps(x).encode()).message_id for x in [group,private]]
        replies=[{'message_id':'group-pending','in_reply_to':mids[0],'thread_id':mids[0],'sender_endpoint':'kai-fixture','body':'durable group reply'},
                 {'message_id':'private-pending','in_reply_to':mids[1],'thread_id':mids[1],'sender_endpoint':'kai-fixture','body':'private reply'}]
        acknowledgements=[];previous=rt.host
        def mailbox(op,**kw):
            if op=='service_inbox':return {'messages':[{'message_id':r['message_id'],'sequence':i+1} for i,r in enumerate(replies)]}
            if op=='service_message':return next(r for r in replies if r['message_id']==kw['message_id'])
            if op=='service_ack':acknowledgements.append(kw['message_id']);return {}
            return previous(op,**kw)
        rt.host=mailbox
        return rt,replies,acknowledgements

    def edit_config(self,rt,edit):
        p=Path(rt.config_path);config=json.loads(p.read_text());edit(config);p.write_text(json.dumps(config))

    def test_revoked_pending_reply_is_durable_unacked_and_private_continues(self):
        rt,replies,acks=self.reply_fixture()
        self.edit_config(rt,lambda c:c['group_binding'].update(revoked=True))
        rt.replies_once()
        held=rt.journal.db.execute('SELECT envelope,reason,prior_reply_state FROM telegram_reply_holds').fetchone()
        self.assertEqual(json.loads(held[0]),replies[0]);self.assertEqual(held[1],'binding_inactive');self.assertIsNone(held[2])
        self.assertEqual(acks,['private-pending']);self.assertEqual(rt.cursor('mailbox'),2)
        sends=[p for m,p in rt.fixture_payloads if m=='sendMessage'];self.assertEqual([p['chat_id'] for p in sends],[202])
        previous=rt.api.call;private=json.loads(self.raw(False));private['update_id']=11
        rt.api.call=lambda m,p:[private] if m=='getUpdates' else previous(m,p)
        rt.receive_once();self.assertEqual(rt.journal.db.execute('SELECT count(*) FROM telegram_intents').fetchone()[0],3)
        self.edit_config(rt,lambda c:c['group_binding'].update(revoked=False))
        rt.replies_once()
        self.assertEqual(len([p for m,p in rt.fixture_payloads if m=='sendMessage']),1)

    def test_unknown_group_send_is_held_without_retry_and_private_reply_continues(self):
        rt,replies,acks=self.reply_fixture();prior=rt.api.call;attempts=[]
        def api(method,payload):
            if method=='sendMessage':
                attempts.append(payload['chat_id'])
                if payload['chat_id']<0:raise OSError('synthetic response lost after possible acceptance')
            return prior(method,payload)
        rt.api.call=api;rt.replies_once();rt.replies_once()
        self.assertEqual(attempts,[-100123,202]);self.assertEqual(rt.journal.reply_state('group-pending'),'unknown')
        row=rt.journal.db.execute('SELECT prior_reply_state,envelope FROM telegram_reply_holds WHERE message_id="group-pending"').fetchone()
        self.assertEqual(row[0],'unknown');self.assertEqual(json.loads(row[1]),replies[0]);self.assertNotIn('group-pending',acks)

    def test_existing_reserved_or_unknown_group_reply_is_not_resent(self):
        rt,replies,acks=self.reply_fixture();group=replies[0]
        payload={'chat_id':-100123,'text':group['body'],'reply_to_message_id':7}
        rt.journal.reserve_reply(group['message_id'],payload)
        rt.replies_once()
        self.assertEqual(rt.journal.reply_state(group['message_id']),'reserved')
        row=rt.journal.db.execute('SELECT prior_reply_state FROM telegram_reply_holds WHERE message_id=?',(group['message_id'],)).fetchone()
        self.assertEqual(row[0],'reserved');self.assertNotIn(group['message_id'],acks)
        self.assertEqual([p['chat_id'] for m,p in rt.fixture_payloads if m=='sendMessage'],[202])

    def test_removed_group_binding_retains_pending_reply_for_reconciliation(self):
        rt,replies,acks=self.reply_fixture()
        self.edit_config(rt,lambda c:c.pop('group_binding'))
        rt.relays.pop(self.group.binding_id)  # same view as a restart after removal
        rt.replies_once()
        row=rt.journal.db.execute('SELECT envelope FROM telegram_reply_holds WHERE message_id="group-pending"').fetchone()
        self.assertEqual(json.loads(row[0]),replies[0]);self.assertEqual(acks,['private-pending'])

    def test_hold_and_cursor_are_atomic_if_durable_storage_fails(self):
        rt,replies,acks=self.reply_fixture();self.edit_config(rt,lambda c:c['group_binding'].update(revoked=True))
        rt.journal.db.execute("CREATE TRIGGER fail_hold BEFORE INSERT ON telegram_reply_holds BEGIN SELECT RAISE(ABORT,'synthetic storage failure'); END")
        with self.assertRaises(__import__('sqlite3').IntegrityError):rt.replies_once()
        self.assertEqual(rt.cursor('mailbox'),0);self.assertEqual(acks,[])
        self.assertEqual(rt.journal.db.execute('SELECT count(*) FROM telegram_reply_holds').fetchone()[0],0)
        rt.journal.db.execute('DROP TRIGGER fail_hold');rt.replies_once()
        self.assertEqual(rt.cursor('mailbox'),2);self.assertEqual(acks,['private-pending'])

    def test_discovery_metadata_ttl_and_row_cap_on_empty_poll(self):
        settings={'owner_binding':asdict(self.private),'group_discovery':{'marker':'fixture-marker-unique','expires_at':1100}}
        rt,api,host=self.make_runtime(settings,[])
        for i in range(40):rt.journal.db.execute('INSERT INTO telegram_group_candidates VALUES(?,?,?,?)',(-200000-i,'{}',999-i,1100))
        rt.journal.db.execute('INSERT INTO telegram_group_candidates VALUES(?,?,?,?)',(-300000,'{}',-100,2000))
        rt.receive_once();self.assertEqual(rt.journal.db.execute('SELECT count(*) FROM telegram_group_candidates').fetchone()[0],runtime.GROUP_DISCOVERY_MAX_ROWS)
        self.assertIsNone(rt.journal.db.execute('SELECT 1 FROM telegram_group_candidates WHERE chat_id=-300000').fetchone())
        self.now=1101;rt.receive_once();self.assertEqual(rt.journal.db.execute('SELECT count(*) FROM telegram_group_candidates').fetchone()[0],0)

    def test_removed_discovery_is_honored_after_startup_and_during_poll(self):
        settings={'owner_binding':asdict(self.private),'group_discovery':{'marker':'fixture-marker-unique','expires_at':1100}}
        rt,api,host=self.make_runtime(settings,[json.loads(self.raw(text='fixture-marker-unique'))])
        rt.maintain_group_candidates(settings,{'chat_id':-100123,'title':'Agents'})
        previous=rt.api.call
        def call(method,payload):
            if method=='getUpdates':self.edit_config(rt,lambda c:c.pop('group_discovery'))
            return previous(method,payload)
        rt.api.call=call;rt.receive_once()
        self.assertEqual(rt.journal.db.execute('SELECT count(*) FROM telegram_group_candidates').fetchone()[0],0);self.assertEqual(host,[])

    def test_owner_revocation_stops_discovery_after_startup(self):
        settings={'owner_binding':asdict(self.private),'group_discovery':{'marker':'fixture-marker-unique','expires_at':1100}}
        rt,api,host=self.make_runtime(settings,[json.loads(self.raw(text='fixture-marker-unique'))])
        rt.maintain_group_candidates(settings,{'chat_id':-100123,'title':'Agents'})
        self.edit_config(rt,lambda c:c['owner_binding'].update(revoked=True));rt.receive_once()
        self.assertEqual(rt.journal.db.execute('SELECT count(*) FROM telegram_group_candidates').fetchone()[0],0);self.assertEqual(host,[])


# Exercise the existing adapter/bridge/Host/Hub path with fixture transports.
fixture_module = sys.modules[__name__]
_kai_spec = importlib.util.spec_from_file_location('integrated_kai_runtime',
    Path(__file__).resolve().parents[1]/'external/kai-mcp/runtime.py')
kai_runtime = importlib.util.module_from_spec(_kai_spec); _kai_spec.loader.exec_module(kai_runtime)
from connection import FixedConnectionAuthorizer
from mailbox_tools import MailboxTools, MailboxToolError
from server import MCPServer
from unittest.mock import patch

class IntegratedFlow(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture_module.AgentsTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        f=self.fixture
        self.host,self.hub,self.hub_calls=f.real_submit_fixture(legacy=True)
        telegram=self.host.config['services']['telegram']
        telegram.update(token='FAKE',address='telegram',participant_id='telegram-principal')
        self.host.config['services']['kai']={'token':'FAKE-KAI','address':'kai',
            'participant_id':'kai-principal','binding_generation':'KAI-GENERATION','allowed_addresses':['telegram']}
        def authenticated_fixture_service(pid,uid,req,**kw):
            ident,cfg=self.host._service_binding(req)
            if (req.get('service_token')!=cfg['token'] or req.get('address')!=cfg['address']
                    or req.get('binding_generation')!=cfg['binding_generation']):
                raise HubError('identity_rejected','fixture service credential mismatch')
            ep=dict(self.hub.db.execute('SELECT * FROM endpoints WHERE participant_id=?',(cfg['participant_id'],)).fetchone())
            ep.update(service_id=ident,address=cfg['address'])
            return ep
        self.host.service=authenticated_fixture_service
        private=json.loads(f.raw(False));group=json.loads(f.raw());group['update_id']=10
        self.updates=[private,group]
        self.telegram,self.api_calls,self.initial_host_calls=f.make_runtime(f.settings,self.updates,kai_endpoint='kai-principal-ep')
        def transport(path,request):return self.host.dispatch(request,123,__import__('os').getuid())
        self.telegram.host_call=transport
        original_api=self.telegram.api.call
        self.telegram.api.call=lambda method,payload:({'id':101,'is_bot':True,'username':'fixture_bot'}
            if method=='getMe' else original_api(method,payload))
        self.patch=patch.object(kai_runtime,'socket_rpc',side_effect=transport);self.patch.start();self.addCleanup(self.patch.stop)
        kai_config={'service_id':'kai','address':'kai',
            'participant_id':'kai-principal','service_token':'FAKE-KAI',
            'binding_generation':'KAI-GENERATION','allowed_addresses':['telegram'],
            'host_socket':str(Path(f.tmp.name)/'never-host.sock'),
            'event_state':str(Path(f.tmp.name)/'unused-events.json')}
        self.parent=kai_runtime.ServiceRuntime(kai_config)
        self.bridge_calls=[]
        def bridge_transport(path,request):
            self.bridge_calls.append(request['op'])
            self.bridge_calls.append(request.get('request',{}).get('op'))
            return kai_runtime._bridge_request(self.parent,request)
        self.bridge_patch=patch.object(kai_runtime,'_bridge_rpc',side_effect=bridge_transport)
        self.bridge_patch.start();self.addCleanup(self.bridge_patch.stop)
        self.kai=kai_runtime.ServiceRuntime(dict(kai_config,bridge_socket=str(Path(f.tmp.name)/'never-bridge.sock')))
        auth=FixedConnectionAuthorizer(self.kai.binding,self.kai._attest)
        self.tools=MailboxTools(service_id='kai',service_address='kai',service_token='FAKE-KAI',
            authorizer=auth.authorize,host_call=self.kai._request)
        self.server=MCPServer(tools=self.tools)
        self.host.db.execute('CREATE TABLE deliveries(message_id TEXT PRIMARY KEY,endpoint_id TEXT,envelope TEXT,state TEXT,prompt_hash TEXT,updated REAL)')
        self.telegram.verify();self.telegram.receive_once()
        self.ids=[f.admit(json.dumps(update).encode()).message_id for update in self.updates]

    def call(self,name,args):
        response=self.server.handle({'jsonrpc':'2.0','id':1,'method':'tools/call',
            'params':{'name':name,'arguments':args}})
        return response['result']

    def test_private_and_group_runtime_host_hub_kai_view_reply(self):
        for index,mid in enumerate(self.ids):
            response=self.call('tproj_message',{'message_id':mid})
            self.assertFalse(response.get('isError',False),response)
            view=response['structuredContent'];expected=self.fixture.admit(json.dumps(self.updates[index]).encode()).envelope()['external_origin']
            self.assertEqual(view['external_origin'],expected)
            self.assertIs(view['origin_binding_active'],True)
            self.assertEqual(view['external_origin']['version'],1 if index==0 else 2)
            self.assertFalse(self.call('tproj_ack',{'message_id':mid}).get('isError',False))
            reply=self.call('tproj_reply',{'message_id':mid,'body':'fixture KAI response',
                'submission_id':'fixture-response-'+str(index)})
            self.assertFalse(reply.get('isError',False),reply)
        __import__('submission_queue').work_once(self.host)
        self.telegram.replies_once()
        sends=[payload for method,payload in self.telegram.fixture_payloads if method=='sendMessage']
        self.assertEqual([p['chat_id'] for p in sends],[202,-100123])
        self.assertEqual([p['reply_parameters']['message_id'] for p in sends],[7,7])
        self.assertEqual(self.hub.db.execute('SELECT count(*) FROM messages').fetchone()[0],4)
        self.assertEqual(self.telegram.journal.db.execute('SELECT count(*) FROM telegram_replies WHERE state="accepted"').fetchone()[0],2)

    def test_existing_bridge_parent_forwards_raw_origin_without_view_or_catalog(self):
        self.parent.server=lambda:(_ for _ in ()).throw(AssertionError('parent must not render tools'))
        response=self.call('tproj_message',{'message_id':self.ids[1]})
        self.assertIs(response['structuredContent']['origin_binding_active'],True)
        self.assertEqual(response['structuredContent']['external_origin']['version'],2)
        self.assertIn('call',self.bridge_calls)

    def test_hub_rejects_origin_reused_by_wrong_authenticated_principal(self):
        envelope=self.fixture.admit(json.dumps(self.updates[1]).encode()).envelope()
        envelope['sender_endpoint']='kai-principal-ep'
        with self.assertRaises(HubError) as e:self.hub.dispatch(dict(op='submit',host_id='local',host_token='FAKE',message=envelope))
        self.assertEqual(e.exception.code,'identity_rejected')
        self.assertEqual(self.hub.db.execute('SELECT count(*) FROM messages').fetchone()[0],2)

    def test_invalid_origin_fails_at_kai_view_and_private_still_works(self):
        mid=self.ids[1];row=self.hub.db.execute('SELECT external_origin_json FROM messages WHERE message_id=?',(mid,)).fetchone()
        origin=json.loads(row[0]);origin['body_sha256']='f'*64
        self.hub.db.execute('UPDATE messages SET external_origin_json=? WHERE message_id=?',(json.dumps(origin),mid))
        response=self.call('tproj_message',{'message_id':mid})
        self.assertTrue(response['isError']);self.assertEqual(response['structuredContent']['error']['code'],'unavailable')
        private=self.call('tproj_message',{'message_id':self.ids[0]})
        self.assertIs(private['structuredContent']['origin_binding_active'],True)

    def test_inactive_host_binding_is_never_promoted_to_owner_authority(self):
        binding=self.fixture.group.binding_id
        self.hub.config['telegram_ingress_bindings'][binding]['owner_binding']['revoked']=True
        result=self.call('tproj_message',{'message_id':self.ids[1]})
        self.assertFalse(result.get('isError',False),result)
        self.assertIs(result['structuredContent']['origin_binding_active'],False)
        self.assertEqual(result['structuredContent']['external_origin']['version'],2)

    def test_malformed_origin_types_and_marker_rejected(self):
        mid=self.ids[1]
        row=self.host.hub('query',endpoint_id='kai-principal-ep',message_id=mid)
        for change in [('origin_binding_active',1),('origin_binding_active',None)]:
            altered=copy.deepcopy(row);altered[change[0]]=change[1]
            with self.subTest(change=change),self.assertRaises(MailboxToolError):MailboxTools._view(altered)
        for key,value in [('version',True),('version',3),('chat_type','private'),('chat_id',True),('user_id',True)]:
            altered=copy.deepcopy(row);altered['external_origin'][key]=value
            with self.subTest(key=key),self.assertRaises(MailboxToolError):MailboxTools._view(altered)
        altered=copy.deepcopy(row);altered['body']='\ud800'
        with self.assertRaises(MailboxToolError):MailboxTools._view(altered)

    def test_catalog_restores_private_schema_and_explicit_group_variant(self):
        active=json.loads((Path(__file__).resolve().parents[3]/'docs/reference/external-assistant-tools.json').read_text())
        documented={t['name']:t for t in active['tools']}
        catalog=self.server.handle({'jsonrpc':'2.0','id':1,'method':'tools/list'})['result']['tools']
        exposed={t['name']:t for t in catalog}
        self.assertEqual(exposed,documented)
        self.assertTrue({'tproj_reconcile','tproj_cancel_submission'} <= set(exposed))
        for name in ['tproj_inbox','tproj_message']:
            props=exposed[name]['outputSchema']['properties']
            if name=='tproj_inbox':props=props['messages']['items']['properties']
            variants=props['external_origin']['oneOf']
            self.assertIn('origin_binding_active',props)
            self.assertEqual(variants[0]['properties']['version']['const'],1)
            self.assertEqual(variants[1]['properties']['chat_id']['maximum'],-1)
            self.assertEqual(variants[1]['properties']['chat_type']['enum'],['group','supergroup'])



    def test_public_submission_controls_cross_actual_bridge_host_and_hub(self):
        sent=self.call('tproj_send',{'target':'telegram','body':'fixture','submission_id':'public-control'})
        self.assertFalse(sent.get('isError',False),sent)
        rec=self.call('tproj_reconcile',{'submission_id':'public-control'})
        self.assertFalse(rec.get('isError',False),rec)
        self.assertFalse(rec['structuredContent']['reconciled'])
        cancelled=self.call('tproj_cancel_submission',{'submission_id':'public-control'})
        self.assertFalse(cancelled.get('isError',False),cancelled)
        self.assertTrue(cancelled['structuredContent']['cancelled'])
        __import__('submission_queue').work_once(self.host)
        self.assertIsNone(self.hub.db.execute("SELECT 1 FROM messages WHERE message_id='public-control'").fetchone())
        self.assertIn('service_reconcile',self.bridge_calls);self.assertIn('service_cancel_submission',self.bridge_calls)

    def test_public_reconciliation_positive_proof_crosses_actual_runtime_and_bridge(self):
        sid='public-positive-proof'
        sent=self.call('tproj_send',{'target':'telegram','body':'fixture','submission_id':sid})
        self.assertFalse(sent.get('isError',False),sent)
        __import__('submission_queue').work_once(self.host)
        self.host.db.execute("UPDATE submission_work SET state='held',hub_receipt=NULL WHERE message_id=?",(sid,));self.host.db.commit()
        result=self.call('tproj_reconcile',{'submission_id':sid})
        self.assertFalse(result.get('isError',False),result)
        self.assertTrue(result['structuredContent']['reconciled'])
        self.assertEqual(result['structuredContent']['hub_acceptance'],'committed')
        result=self.call('tproj_cancel_submission',{'submission_id':sid})
        self.assertFalse(result.get('isError',False),result)
        self.assertFalse(result['structuredContent']['cancelled'])

    def test_public_submission_controls_require_existing_authenticated_principal(self):
        for name in ('tproj_reconcile','tproj_cancel_submission'):
            bad=self.call(name,{'submission_id':'unknown','endpoint_id':'kai-principal-ep'})
            self.assertTrue(bad.get('isError',False))
        real=self.kai._attest;self.kai._attest=lambda:dict(real(),participant_id='OTHER')
        auth=FixedConnectionAuthorizer(self.kai.binding,self.kai._attest)
        denied=MailboxTools(service_id='kai',service_address='kai',service_token='FAKE-KAI',authorizer=auth.authorize,host_call=self.kai._request)
        for name in ('tproj_reconcile','tproj_cancel_submission'):
            with self.assertRaises(MailboxToolError):denied.dispatch(name,{'submission_id':'unknown'})
        req={'op':'service_reconcile','service_id':'kai','service_token':'WRONG','address':'kai','binding_generation':'KAI-GENERATION','submission_id':'unknown'}
        with self.assertRaises(HubError):self.host.dispatch(req,123,__import__('os').getuid())


if __name__=='__main__': unittest.main(verbosity=2)
