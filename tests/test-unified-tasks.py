import sqlite3
import unittest
from extensions.messaging.unified.tasks import TaskAuthority, TaskAuthorityError

A = {"endpoint_id":"e1","incarnation":"i1","host_id":"h1","project_id":"p1"}
B = {"endpoint_id":"e2","incarnation":"i2","host_id":"h2","project_id":"p2"}

def authority(): return TaskAuthority(sqlite3.connect(":memory:", isolation_level=None))

def make_task(t):
    t.dispatch({"op":"approval","approval_id":"a","intent_hash":"ih","scope_hash":"sh","evidence_hash":"eh","source_endpoint":"e1","host_attested":True}, A)
    return t.dispatch({"op":"submit","idempotency_key":"k","intent_hash":"ih","scope_hash":"sh","approval_id":"a","payload":{"x":1},"executor":A}, A)["task"]

class TestTasks(unittest.TestCase):
 def test_approval_submit_and_idempotency(self):
    t=authority(); first=make_task(t); second=make_task(t)
    assert second["task_id"] == first["task_id"]
    with self.assertRaises(TaskAuthorityError): t.dispatch({"op":"approval","approval_id":"bad","intent_hash":"i","scope_hash":"s","evidence_hash":"e","source_endpoint":"e1"},A)

 def test_incarnation_fence_and_handoff(self):
    t=authority(); task=make_task(t); tid=task["task_id"]
    with self.assertRaises(TaskAuthorityError): t.dispatch({"op":"progress","task_id":tid,"expected_epoch":0}, {**A,"incarnation":"old"})
    t.dispatch({"op":"ack","task_id":tid,"expected_epoch":0},A)
    t.dispatch({"op":"prepare_handoff","task_id":tid,"expected_epoch":0,"target":B},A)
    with self.assertRaises(TaskAuthorityError): t.dispatch({"op":"commit_handoff","task_id":tid,"expected_epoch":0,"target":B},A)
    t.dispatch({"op":"release_handoff","task_id":tid,"expected_epoch":0},A)
    t.dispatch({"op":"accept_handoff","task_id":tid,"expected_epoch":0},B)
    t.dispatch({"op":"commit_handoff","task_id":tid,"expected_epoch":0,"target":B},A)
    with self.assertRaises(TaskAuthorityError): t.dispatch({"op":"progress","task_id":tid,"expected_epoch":0},A)
    assert t.dispatch({"op":"active"},A)["tasks"]

 def test_operation_quiescence_and_cancel(self):
    t=authority(); tid=make_task(t)["task_id"]
    t.dispatch({"op":"ack","task_id":tid,"expected_epoch":0},A)
    op=t.dispatch({"op":"begin_operation","task_id":tid,"expected_epoch":0,"tool_use_id":"u1"},A)
    with self.assertRaises(TaskAuthorityError): t.dispatch({"op":"prepare_handoff","task_id":tid,"expected_epoch":0,"target":B},A)
    t.dispatch({"op":"end_operation","token":op["token"]},A)
    t.dispatch({"op":"cancel","task_id":tid,"expected_epoch":0},A)
    with self.assertRaises(TaskAuthorityError): t.dispatch({"op":"begin_operation","task_id":tid,"expected_epoch":0,"tool_use_id":"u2"},A)

 def test_foreign_approval_and_visibility(self):
    t=authority(); make_task(t)
    with self.assertRaises(TaskAuthorityError): t.dispatch({"op":"submit","idempotency_key":"k2","intent_hash":"ih","scope_hash":"sh","approval_id":"a"},B)
    self.assertEqual(t.dispatch({"op":"list"},B)["tasks"], [])

if __name__ == '__main__': unittest.main()
