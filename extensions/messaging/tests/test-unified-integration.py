#!/usr/bin/env python3
"""Protected mailbox transitions and terminal adapter integration, no live sends."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'unified'
sys.path.insert(0, str(ROOT))
from hub import Hub
from host import Host, paste_parts
from protocol import HubError
from receipt import normalize_prompt


class Integration(unittest.TestCase):
    def test_reply_after_alias_rename_probe_claim_and_retirement(self):
        with tempfile.TemporaryDirectory() as tmp:
            hub = Hub(Path(tmp)/'hub.db', {'admin_token':'admin','hosts':{'h':'token'},'probe_message_ids':['m','r']})
            call=lambda op,**kw:hub.dispatch(dict(kw,op=op,host_id='h',host_token='token'))
            projects=[dict(project_id='p',alias='project',host_id='h',path='/project')]
            hub.directory_import(dict(admin_token='admin',projects=projects))
            for side in ('cc','cdx'):
                call('endpoint_register',endpoint_id=side,participant_id='p:'+side,session='s',pane='%1',pid=10,pid_start='1',runtime_id=side,platform=side)
            hub.dispatch(dict(op='maintenance',admin_token='admin',mode='probe'))
            call('submit',message=dict(message_id='m',sender_endpoint='cc',target='cdx',body='a\n$ `literal`'))
            self.assertEqual(len(call('claim',endpoint_id='cdx',limit=1)['messages']),1)
            projects[0]['alias']='renamed'
            hub.directory_import(dict(admin_token='admin',projects=projects,expected_revision=1))
            call('submit',message=dict(message_id='r',in_reply_to='m',sender_endpoint='cdx',body='back'))
            reply=call('query',message_id='r',endpoint_id='cc')
            self.assertEqual((reply['recipient_endpoint'],reply['thread_id'],reply['target_address']),('cc','m','renamed.cc'))
            call('receipt',endpoint_id='cdx',message_id='m',state='presented')
            with self.assertRaises(HubError):call('receipt',endpoint_id='cdx',message_id='m',state='uncertain')
            call('endpoint_retire',endpoint_id='cc')
            with self.assertRaises(HubError):call('submit',message=dict(message_id='m',sender_endpoint='cc',target='cdx',body='a\n$ `literal`'))
            hub.close()

    def test_host_submission_and_exact_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            host=Host({'journal':str(Path(tmp)/'journal.db')})
            ep={'endpoint_id':'e','runtime_id':'runtime'}
            host.caller=lambda pid,uid,req:ep
            calls=[]
            host.hub=lambda op,**args:calls.append((op,args)) or {'state':'queued'}
            req=dict(op='send',submission_id='id',target='target.cc',body='line\nline')
            host.dispatch(req,os.getpid(),os.getuid())
            with self.assertRaises(HubError):host.dispatch(dict(req,body='changed'),os.getpid(),os.getuid())
            import hashlib
            prompt='[tproj-message:m] literal'
            host.db.execute('INSERT INTO deliveries VALUES(?,?,?,?,?,?)',('m','e','{}','dispatching',hashlib.sha256(prompt.encode()).hexdigest(),0));host.db.commit()
            with self.assertRaises(HubError):host.dispatch(dict(op='prompt_receipt',message_id='m',runtime_id='runtime',prompt='wrong'),os.getpid(),os.getuid())
            host.dispatch(dict(op='prompt_receipt',message_id='m',runtime_id='runtime',prompt=prompt),os.getpid(),os.getuid())
            self.assertEqual(calls[-1][1]['state'],'presented')
            host.db.close()

    def test_native_paste_receipt_keeps_sender_marker(self):
        header='[from:project.cc] [tproj-message:message]'
        body='line1\nline2'
        wrapped=header+' \n\n<pasted_content id="abc">\n'+body+'\n</pasted_content id="abc">\n'
        self.assertEqual(normalize_prompt(wrapped),header+' '+body)
        self.assertTrue(normalize_prompt(wrapped).startswith('[from:'))
        literal, pasted = paste_parts('cdx', header+' ', body)
        self.assertEqual(literal, '')
        self.assertEqual(pasted, header+' '+body)
        literal, pasted = paste_parts('cc', header+' ', body)
        self.assertEqual(normalize_prompt(literal+'<pasted_content id="x">\n'+pasted+'\n</pasted_content id="x">'), header+' '+body)

    def test_relative_status_uses_authenticated_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            host=Host({'journal':str(Path(tmp)/'journal.db')})
            host.caller=lambda pid,uid,req:dict(project_id='remote-project')
            host.hub=lambda op,**kw:dict(participants=[dict(participant_id='local-project:cdx',address='local.cdx'),dict(participant_id='remote-project:cdx',address='remote.cdx')])
            result=host.dispatch(dict(op='status',target='cdx'),os.getpid(),os.getuid())
            self.assertEqual(result['address'],'remote.cdx')
            host.db.close()

    def test_guard_never_accepts_fresh_idle_draft_or_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            tool=Path(tmp)/'tmux'
            tool.write_text('#!/bin/bash\ncase "$1" in display-message) echo 0;; show-options) echo idle;; capture-pane) cat "$FIXTURE";; esac\n');tool.chmod(0o755)
            fixture=Path(tmp)/'capture'; env=dict(os.environ,PATH=tmp+':'+os.environ['PATH'],FIXTURE=str(fixture))
            for capture,safe in [('❯ \n',True),('❯ user draft\n',False),('❯ \nsecond line draft\n',False),('Permission required\n❯ Allow command\n  Deny\n',False)]:
                fixture.write_text(capture)
                result=subprocess.run(['bash',str(ROOT/'terminal-guard.sh'),'%1'],env=env,capture_output=True,text=True)
                self.assertEqual(result.returncode==0,safe,result.stdout+result.stderr)

if __name__=='__main__':unittest.main()
