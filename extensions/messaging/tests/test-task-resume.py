"""Same-native continuation: role-specific CAS, authenticated transport and recovery."""
import copy
import io
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'unified'))
from tasks import TaskAuthority, TaskAuthorityError
from protocol import HubError
import task_transport
import task_host
import task_cli

OLD = dict(endpoint_id='old', incarnation='old-inc', host_id='origin', project_id='project')
NEW = dict(OLD, endpoint_id='new', incarnation='new-inc', platform='cdx', thread_id='native')
OWNER = dict(OLD, endpoint_id='owner', incarnation='owner-inc')


def proof(old=OLD, new=NEW):
    common=dict(host_id='origin', project_id='project', participant_id='party',
                platform='cdx', native_kind='thread_id', native_id='native')
    return dict(current=dict(common, **{k:new[k] for k in ('endpoint_id','incarnation')}, retired=False),
                previous=[dict(common, **{k:old[k] for k in ('endpoint_id','incarnation')}, retired=True)])


def authority(owner=OWNER, executor=OLD, status='in_progress'):
    t=TaskAuthority(':memory:')
    t.db.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        ('task','key','intent','scope','approval',owner['endpoint_id'],owner['incarnation'],owner['host_id'],
         owner['project_id'],executor['endpoint_id'],executor['incarnation'],executor['host_id'],status,0,'{"kept":true}',1.,1.))
    return t


def resume(t, op='resume', actor=NEW, epoch=0, p=None):
    return t.dispatch(dict(op=op, task_id='task', expected_epoch=epoch, _resume_proof=p or proof()), actor)


class AuthorityTests(unittest.TestCase):
    def test_executor_resume_preserves_record_and_duplicate_is_durable(self):
        t=authority(); before=dict(t.db.execute('SELECT * FROM tasks').fetchone())
        preview=resume(t,'resume_status')
        self.assertEqual(preview['resume_roles'],['executor'])
        self.assertEqual(t.db.total_changes,1)
        out=resume(t); row=out['task']
        self.assertEqual((row['epoch'],row['executor_endpoint']),(1,'new'))
        for k in ('task_id','approval_id','scope_hash','intent_hash','payload','status','owner_endpoint'):
            self.assertEqual(row[k], before[k] if k!='payload' else {'kept':True})
        self.assertEqual(t.db.execute('SELECT COUNT(*) FROM task_assignments').fetchone()[0],1)
        again=resume(TaskAuthority(t.db))
        self.assertTrue(again['duplicate']);self.assertEqual(again['task']['epoch'],1)
        self.assertEqual(t.db.execute('SELECT COUNT(*) FROM task_events').fetchone()[0],1)
        with self.assertRaises(TaskAuthorityError):
            t.dispatch(dict(op='progress',task_id='task',expected_epoch=1),OLD)
        t.dispatch(dict(op='done',task_id='task',expected_epoch=1),NEW)

    def test_roles_are_independent_and_other_role_epoch_does_not_break_receipt(self):
        t=authority(owner=OLD,executor=OWNER)
        out=resume(t);self.assertEqual(out['resumed_roles'],['owner'])
        self.assertEqual(out['task']['executor_endpoint'],'owner')
        with self.assertRaises(TaskAuthorityError):
            t.dispatch(dict(op='done',task_id='task',expected_epoch=1),NEW)
        second=dict(NEW,endpoint_id='new-executor',incarnation='new-executor-inc')
        resume(t,actor=second,epoch=1,p=proof(OWNER,second))
        self.assertEqual(resume(t)['task']['epoch'],2)
        t.db.execute("UPDATE tasks SET owner_endpoint='elsewhere', owner_incarnation='different'")
        with self.assertRaises(TaskAuthorityError):resume(t)
        both=authority(owner=OLD);self.assertEqual(resume(both)['resumed_roles'],['owner','executor'])

    def test_missing_or_mismatched_native_and_retirement_reject(self):
        for where,key,value in [('current','native_id',''),('current','project_id','wrong'),
                ('current','platform','service'),('current','retired',True),
                ('previous','host_id','other'),('previous','project_id','other'),
                ('previous','participant_id','other'),('previous','platform','cc'),
                ('previous','native_kind','session_id'),('previous','native_id','other'),
                ('previous','retired',False),('previous','incarnation','other')]:
            with self.subTest(where=where,key=key):
                p=proof();(p['current'] if where=='current' else p['previous'][0])[key]=value
                with self.assertRaises(TaskAuthorityError):resume(authority(),p=p)
        with self.assertRaises(TaskAuthorityError):
            authority().dispatch(dict(op='resume',task_id='task',expected_epoch=0),NEW)

    def test_quiescence_status_and_epoch_fences(self):
        for mode in ('frozen','cancelled','reported','open','handoff','stale'):
            with self.subTest(mode=mode):
                t=authority(status=mode if mode in ('frozen','cancelled','reported') else 'in_progress')
                if mode=='open':t.db.execute("INSERT INTO task_operations VALUES('token','task','old','old-inc',0,'tool','open',1)")
                if mode=='handoff':t.db.execute("INSERT INTO task_handoffs VALUES('task',0,'next','next-inc','origin','prepared',1)")
                check=resume(t,'resume_status')
                self.assertEqual(check['resume_allowed'],mode=='stale')
                with self.assertRaises(TaskAuthorityError):resume(t,epoch=7 if mode=='stale' else 0)
                self.assertEqual(t.db.execute('SELECT epoch FROM tasks').fetchone()[0],0)

    def test_preview_never_initializes_schema_or_writes(self):
        fresh=sqlite3.connect(':memory:',isolation_level=None)
        with self.assertRaises(TaskAuthorityError) as error:TaskAuthority(fresh,initialize=False)
        self.assertEqual(error.exception.code,'not_found')
        self.assertEqual(fresh.execute('SELECT COUNT(*) FROM sqlite_master').fetchone()[0],0)
        fresh.close()
        t=authority();t.db.execute('DROP TABLE task_resumptions');before=t.db.total_changes
        resume(TaskAuthority(t.db,initialize=False),'resume_status')
        self.assertEqual(before,t.db.total_changes)
        self.assertFalse(t.db.execute("SELECT 1 FROM sqlite_master WHERE name='task_resumptions'").fetchone())


class TransportTests(unittest.TestCase):
    def hub(self,t):
        class Hub:
            local_id='origin'
            db=t.db
            def _auth(self,req):return 'origin'
            def topology(self):return {'mode':'single'}
            def _row(self,sql,args):
                r=self.db.execute(sql,args).fetchone();return dict(r) if r else None
            def local_resolve(self,**kwargs):return evidence()
        def evidence():
            return dict(endpoint=dict(NEW,participant_id='party',retired=0),
                        participant=dict(participant_id='party',host_id='origin',project_id='project'))
        h=Hub();h.evidence=evidence
        h.db.executescript('CREATE TABLE endpoints(endpoint_id,incarnation,host_id,participant_id,platform,retired); CREATE TABLE endpoint_native(endpoint_id,native_kind,native_id);')
        h.db.executemany('INSERT INTO endpoints VALUES(?,?,?,?,?,?)',
            [('old','old-inc','origin','party','cdx',1),('new','new-inc','origin','party','cdx',0)])
        h.db.executemany('INSERT INTO endpoint_native VALUES(?,?,?)',[('old','thread_id','native'),('new','thread_id','native')])
        return h

    def test_owner_derives_proof_and_rejects_body_injection(self):
        h=self.hub(authority())
        self.assertEqual(task_transport.dispatch(h,dict(op='task_resume_status',endpoint_id='new',task_id='task'))['resume_roles'],['executor'])
        for field in ('_resume_proof','resume_continuity'):
            with self.assertRaises(HubError):task_transport.dispatch(h,dict(op='task_resume',endpoint_id='new',task_id='task',expected_epoch=0,**{field:proof()}))
        h.db.execute("UPDATE endpoint_native SET native_id='unrelated' WHERE endpoint_id='new'")
        with self.assertRaises(HubError):task_transport.dispatch(h,dict(op='task_resume',endpoint_id='new',task_id='task',expected_epoch=0))

    def test_enrolled_peer_attestation_no_origin_callback(self):
        h=self.hub(authority());e=h.evidence();e['resume_continuity']=proof()
        h.local_id='master';h.topology=lambda:dict(mode='multi',task_master_host_id='master');h.peers=lambda:{'origin':{}}
        h.remote=lambda *a,**kw: self.fail('must not call waiting origin')
        req=dict(task_protocol=1,actor_evidence=e,request=dict(op='task_resume',task_id='task',expected_epoch=0))
        self.assertEqual(task_transport.dispatch(h,req,peer=True)['result']['task']['epoch'],1)
        for field,value in [('host_id','foreign'),('participant_id','foreign'),('incarnation','foreign')]:
            bad=copy.deepcopy(req);bad['actor_evidence']['endpoint'][field]=value
            with self.assertRaises(HubError):task_transport.dispatch(h,bad,peer=True)


class HostTests(unittest.TestCase):
    def test_lost_result_then_same_epoch_repairs_binding_and_check_is_readonly(self):
        t=authority()
        class Host:
            db=sqlite3.connect(':memory:',isolation_level=None);db.row_factory=sqlite3.Row
            lose=True
            def hub(self,op,**body):
                if op=='task_capabilities':return dict(capabilities=['task_resume','task_resume_status'])
                result=t.dispatch(dict(body,op=op,_resume_proof=proof()),NEW)
                if op=='task_resume' and self.lose:
                    self.lose=False;raise TimeoutError('lost committed response')
                return result
        host=Host();req=dict(op='task_resume',task_id='task',expected_epoch=0)
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,TPROJ_TASK_BINDING_DIR=d):
            task_host.dispatch(host,NEW,dict(op='task_resume_status',task_id='task'))
            self.assertEqual(list(Path(d).iterdir()),[])
            self.assertFalse(host.db.execute("SELECT name FROM sqlite_master WHERE name='formal_task_binding'").fetchone())
            with self.assertRaises(TimeoutError):task_host.dispatch(host,NEW,req)
            self.assertEqual(list(Path(d).iterdir()),[])
            out=task_host.dispatch(host,NEW,req)
            self.assertTrue(out['binding_committed']);self.assertTrue(out['duplicate'])
            self.assertEqual(tuple(host.db.execute('SELECT task_id,epoch,native_id FROM formal_task_binding').fetchone()),('task',1,'native'))
            host.db.execute("UPDATE formal_task_binding SET task_id='different'")
            with self.assertRaises(HubError):task_host.dispatch(host,NEW,req)
            with self.assertRaises(HubError):task_host.dispatch(host,NEW,dict(req,previous=OLD))

    def test_enrolled_launcher_routes_resume_to_only_unified_cli(self):
        wrapper=Path(__file__).resolve().parents[1]/'tproj-task'
        with tempfile.TemporaryDirectory() as d:
            cfg=Path(d)/'client';cfg.write_text('{"active":true}')
            client=Path(d)/'task_cli.py';client.write_text('import sys; print("unified",*sys.argv[1:])')
            env=dict(os.environ,TPROJ_UNIFIED_CONFIG=str(cfg),TPROJ_UNIFIED_TASK_CLI=str(client))
            out=subprocess.run(['bash',str(wrapper),'resume','task','--check'],env=env,capture_output=True,text=True)
            self.assertEqual(out.returncode,0,out.stderr)
            self.assertEqual(out.stdout.strip(),'unified resume task --check')

    def test_cli_check_and_cas_are_distinct(self):
        with patch.object(task_cli,'request',return_value={}) as call,patch('sys.stdout',io.StringIO()),patch('sys.stderr',io.StringIO()):
            self.assertEqual(task_cli.main(['resume','task','--check']),0)
            call.assert_called_with('resume_status',task_id='task')
            self.assertEqual(task_cli.main(['resume','task','--epoch','2']),0)
            call.assert_called_with('resume',task_id='task',expected_epoch=2)
            call.reset_mock()
            self.assertEqual(task_cli.main(['resume','task']),2)
            self.assertEqual(task_cli.main(['resume','task','--check','--epoch','2']),2)
            call.assert_not_called()


if __name__=='__main__':unittest.main()
