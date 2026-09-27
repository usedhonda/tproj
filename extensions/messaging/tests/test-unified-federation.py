import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'unified'))
from federation import FederatedHub
from protocol import HubError

class FederationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.hubs={};self.down=set();self.calls=[]
        for host in ('a','b','c'):
            cfg={'host_id':host,'hosts':{h:h+'-token' for h in ('a','b','c')},'admin_token':'admin'}
            hub=FederatedHub(Path(self.tmp.name)/(host+'.db'),cfg)
            hub.topology=lambda host=host:{'mode':'multi','management_host_id':'a','hosts':[{'id':h,'ssh_alias':h} for h in ('a','b','c') if h!=host]}
            hub.directory_import({'admin_token':'admin','projects':[{'project_id':host,'alias':host,'host_id':host,'path':'/same/path'}]})
            for role in ('cc','cdx'):
                hub.register(dict(host_id=host,host_token=host+'-token',endpoint_id=host+role,participant_id=host+':'+role,session=host,pane='%1',pid=100,pid_start=10,runtime_id=host+role,platform=role))
            self.hubs[host]=hub;self.addCleanup(hub.close)
        for host,hub in self.hubs.items():
            def remote(owner,op,host=host,**args):
                self.calls.append((host,owner,op))
                if owner in self.down:raise HubError('host_unavailable','offline')
                return self.hubs[owner].dispatch(dict(args,op='peer_'+op,host_id=host,host_token=host+'-token',protocol=1))
            hub.remote=remote
    def send(self,host,mid,target=None,reply=None,body='hello'):
        message=dict(message_id=mid,sender_endpoint=host+'cc',body=body,kind='chat')
        if target:message['target']=target
        if reply:message['in_reply_to']=reply
        return self.hubs[host].submit(dict(host_id=host,host_token=host+'-token',message=message))
    def test_local_without_any_remote_and_same_path_isolated(self):
        self.down={'b','c'}
        self.assertEqual(self.send('a','local','cdx')['state'],'queued')
        self.assertEqual(self.calls,[])
        self.assertIsNotNone(self.hubs['a']._row('SELECT * FROM messages WHERE message_id="local"'))
        self.assertIsNone(self.hubs['b']._row('SELECT * FROM messages WHERE message_id="local"'))
    def test_remote_reply_receipt_and_no_foreign_directory(self):
        self.send('a','out','b.cc')
        self.assertEqual(self.hubs['b']._row('SELECT sender_endpoint FROM messages WHERE message_id="out"')[0],'acc')
        self.send('b','back',reply='out',body='received')
        self.assertEqual(self.hubs['a']._row('SELECT recipient_endpoint FROM messages WHERE message_id="back"')[0],'acc')
        self.assertEqual([p['alias'] for p in self.hubs['b'].local_directory()['projects']],['b'])
        self.hubs['b'].receipt(dict(host_id='b',host_token='b-token',endpoint_id='bcc',message_id='out',state='presented'))
        r=self.hubs['a'].dispatch(dict(op='query',host_id='a',host_token='a-token',endpoint_id='acc',message_id='out'))
        self.assertEqual(r['state'],'presented')
        self.assertTrue(self.send('a','out','b.cc')['duplicate'])
    def test_offline_no_accept_and_stale_reply_never_retargets(self):
        self.down={'b'}
        with self.assertRaises(HubError):self.send('a','missing','b.cc')
        self.assertIsNone(self.hubs['a']._row('SELECT * FROM messages WHERE message_id="missing"'))
        self.down.clear();self.send('a','sent','b.cc')
        self.hubs['a'].dispatch(dict(op='endpoint_retire',host_id='a',host_token='a-token',endpoint_id='acc'))
        with self.assertRaises(HubError):self.send('b','reply',reply='sent',body='answer')
    def test_unknown_peer_cannot_inject(self):
        with self.assertRaises(HubError):self.hubs['b'].dispatch(dict(op='peer_directory',host_id='a',host_token='bad',protocol=1))

if __name__=='__main__':unittest.main()
