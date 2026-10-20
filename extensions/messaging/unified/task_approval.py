"""Read direct native approval evidence; never accept message text as authority."""
from __future__ import annotations
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
import re
from protocol import HubError


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def project_directory(path):
    """Resolve a directory to its nearest repository, including worktrees."""
    path = Path(path).resolve()
    return next((parent for parent in (path, *path.parents)
                 if (parent / '.git').exists()), None)


def matches_project(cwd, project):
    if not isinstance(cwd, str) or not cwd:
        return False
    bound = Path(project).resolve()
    observed = Path(cwd).resolve()
    root = project_directory(bound) or bound
    # A cwd change is not a new conversation, but sibling/nested repositories
    # must not borrow approval from this project.
    if observed != root and root not in observed.parents:
        return False
    observed_root = project_directory(observed)
    return observed_root is None or observed_root == root


def texts(record, platform):
    if platform == 'cdx':
        if record.get('type') != 'response_item': return None
        record = record.get('payload', {})
    elif record.get('type') not in ('user','assistant'):
        return None
    else:
        record = record.get('message', {})
    if record.get('role') not in ('user','assistant'): return None
    content = record.get('content', '')
    if isinstance(content, list):
        content = '\n'.join(x.get('text','') for x in content if isinstance(x,dict) and x.get('type') in ('text','input_text','output_text'))
    return record['role'], content


def validate_records(records, platform, intent, scope, evidence_hash, evidence_records=None):
    """An exact direct user instruction or its immediately preceding proposal."""
    if not isinstance(intent, str) or not intent.strip():
        raise HubError('approval_unattested', 'nonempty audit intent required')
    if evidence_records is not None:
        if (not isinstance(evidence_records, list) or not evidence_records
                or len(evidence_records) > 32
                or any(not isinstance(h, str) or not re.fullmatch(r'[0-9a-f]{64}', h) for h in evidence_records)
                or len(set(evidence_records)) != len(evidence_records)):
            raise HubError('approval_unattested', 'invalid ordered evidence hashes')
        selected = []
        for record in records:
            item = texts(record, platform)
            if not item or item[0] != 'user':
                continue
            text = item[1]
            if digest(text) in evidence_records:
                if re.search(r'\[from:|\[tproj-message:|\[OpenClaw Agent|<tool_result|<system-reminder|<codex_internal_context', text, re.I):
                    raise HubError('approval_unattested', 'injected record is not approval evidence')
                selected.append(text)
        if [digest(t) for t in selected] != evidence_records:
            raise HubError('approval_unattested', 'evidence records missing, ambiguous or out of order')
        if scope != '\n\n'.join(selected):
            raise HubError('approval_unattested', 'scope differs from ordered native evidence')
        return {'intent_hash': digest(intent), 'scope_hash': digest(scope),
                'evidence_hash': digest(json.dumps(evidence_records, separators=(',', ':')))}
    plan = None
    for record in records:
        item = texts(record, platform)
        if not item: continue
        role,text = item
        if role == 'assistant':
            match = re.search(r'<proposed_plan>\s*(.*?)\s*</proposed_plan>', text, re.S)
            if match: plan = match.group(1)
            continue
        # Every user record consumes the pending proposal, even a rejected
        # candidate. Identical approval wording may approve a later proposal.
        candidate_plan, plan = plan, None
        if digest(text) != evidence_hash:
            continue
        # Transport/hook/tool-result injections are not a user approval source.
        if re.search(r'\[from:|\[tproj-message:|\[OpenClaw Agent|<tool_result|<system-reminder|<codex_internal_context',text,re.I):
            continue
        # The native user's wording is authoritative; no magic approval phrase.
        # This binds the exact scope, not a paraphrase or an agent-authored expansion.
        direct = isinstance(scope, str) and bool(scope.strip()) and scope == text
        confirms_plan = text.strip().lower() in ('implement the plan.', 'implement the plan', '実行して', '実装して', 'すすめて', '進めて', 'つづけて')
        if not direct and not (confirms_plan and candidate_plan is not None and isinstance(scope, str) and scope.strip() == candidate_plan):
            continue
        return {'intent_hash':digest(intent),'scope_hash':digest(scope),'evidence_hash':evidence_hash}
    raise HubError('approval_unattested','scope must match a native direct instruction or its approved proposed_plan')



def native_goal_evidence(records, native_id):
    """Read-only user-goal evidence, NOT a tool grant or task approval.

    Caller must bind the native ID/header/project and supply only top-level live
    rollout records. Nested compacted/replacement histories are never traversed.
    Revalidate the latest evidence at use; do not persist this as a blanket grant.
    """
    if not isinstance(native_id, str) or not native_id:
        raise HubError('approval_unattested', 'native Goal binding required')
    counts = Counter()
    current = None
    state = None
    status = None
    prefix = '<codex_internal_context source="user_goal">'
    suffix = '</codex_internal_context>'
    for record in records:
        if not isinstance(record, dict) or record.get('type') != 'response_item':
            continue
        item = record.get('payload')
        if not isinstance(item, dict): continue
        ident = item.get('id')
        if isinstance(ident, str): counts[ident] += 1
        meta = item.get('internal_chat_message_metadata_passthrough')
        if not isinstance(meta, dict): continue
        kinds = meta.get('content_item_kinds')
        if not isinstance(kinds, list) or not any(isinstance(k, str) and k.startswith('user.goal') for k in kinds):
            continue
        # Any malformed/incomplete newer Goal annotation invalidates the old
        # objective; never silently fall back to its more permissive evidence.
        content = item.get('content')
        stamp = meta.get('create_time')
        valid = (item.get('type') == 'message' and item.get('role') == 'user'
                 and kinds == ['user.goal'] and isinstance(ident, str) and bool(ident)
                 and type(stamp) in (int, float) and math.isfinite(stamp) and stamp > 0
                 and isinstance(content, list) and len(content) == 1
                 and isinstance(content[0], dict) and content[0].get('type') == 'input_text'
                 and isinstance(content[0].get('text'), str))
        if not valid:
            current = state = None
            status = None
            continue
        text = content[0]['text']
        if not text.startswith(prefix) or not text.endswith(suffix):
            current = state = None
            status = None
            continue
        lines = text[len(prefix):-len(suffix)].strip().splitlines()
        update = {}
        try:
            if lines == ['User cleared the goal.']:
                current = state = None
                status = None
                continue
            for line in lines:
                if line.startswith('User set the goal: ') and not update:
                    objective = json.loads(line[len('User set the goal: '):])
                    if (not isinstance(objective, str) or not objective.strip()
                            or len(json.dumps(objective, ensure_ascii=False).encode()) > 700):
                        raise ValueError()
                    update['objective'] = objective
                elif line.startswith('User set goal status: ') and 'status' not in update and line.endswith('.'):
                    value = json.loads(line[len('User set goal status: '):-1])
                    if value not in ('active', 'paused', 'blocked', 'usage_limited', 'budget_limited', 'complete'):
                        raise ValueError()
                    update['status'] = value
                else: raise ValueError()
            if not update: raise ValueError()
        except (ValueError, TypeError):
            current = state = None
            status = None
            continue
        evidence = {'record_id': ident, 'create_time': stamp}
        if 'objective' in update:
            current = dict(evidence, objective=update['objective'])
        if 'status' in update: status = update['status']
        state = evidence
    if (not current or not state or counts[current['record_id']] != 1
            or counts[state['record_id']] != 1):
        raise HubError('approval_unattested', 'current native Goal setter missing or ambiguous')
    proof = dict(native_id=native_id, setter_record_id=current['record_id'],
                 setter_create_time=current['create_time'], state_record_id=state['record_id'],
                 state_create_time=state['create_time'], scope_hash=digest(current['objective']), status=status)
    return dict(proof, objective=current['objective'], source='native_user_goal',
                evidence_hash=digest(json.dumps(proof, sort_keys=True, separators=(',', ':'))),
                execution_authorized=False)


def validate_native_goal_evidence(records, native_id, scope, setter_record_id, evidence_hash):
    """Exact current evidence identity only; latest operation/scope checks remain."""
    proof = native_goal_evidence(records, native_id)
    if (proof['objective'] != scope or proof['setter_record_id'] != setter_record_id
            or proof['evidence_hash'] != evidence_hash
            or proof['status'] in ('paused', 'blocked', 'usage_limited', 'budget_limited', 'complete')):
        raise HubError('approval_unattested', 'native Goal evidence changed or is inactive')
    return proof

def attest(ep, req, home=None):
    home = Path(home or Path.home())
    platform=ep.get('platform')
    tid = next((ep.get(k) for k in ('thread_id','session_id','observed_runtime_id','runtime_id') if isinstance(ep.get(k),str) and re.fullmatch(r'[0-9a-fA-F-]{36}',ep[k])), None)
    if not isinstance(tid,str) or not re.fullmatch(r'[0-9a-fA-F-]{36}',tid):
        raise HubError('approval_unattested','native conversation ID unavailable')
    if platform == 'cdx':
        root=home/'.codex/sessions';paths=list(root.glob('[0-9][0-9][0-9][0-9]/[0-9][0-9]/[0-9][0-9]/rollout-*-'+tid+'.jsonl'))
    elif platform == 'cc':
        root=home/'.claude/projects';paths=list(root.glob('*/'+tid+'.jsonl'))
    else: raise HubError('approval_unattested','native AI conversation required')
    paths=[p for p in paths if p.is_file() and not any(x.is_symlink() for x in (p,*p.parents))]
    if len(paths)!=1: raise HubError('approval_unattested','native transcript is missing or ambiguous')
    try:
        with paths[0].open() as stream:
            records=(json.loads(line) for line in stream if line.strip())
            project = ep.get('project_path')
            if not project:
                raise HubError('approval_unattested','bound project path unavailable')
            if platform == 'cdx':
                header = next(records, {})
                meta = header.get('payload') or {}
                if header.get('type') != 'session_meta' or meta.get('id') != tid or not matches_project(meta.get('cwd'), project):
                    raise HubError('approval_unattested','native transcript header does not match bound conversation')
            else:
                def bound_records(source):
                    for row in source:
                        if row.get('type') in ('user','assistant'):
                            if row.get('sessionId') != tid or not matches_project(row.get('cwd'), project):
                                raise HubError('approval_unattested','native transcript record does not match bound conversation')
                        yield row
                records = bound_records(records)
            result=validate_records(records,platform,req.get('intent'),req.get('scope'),req.get('evidence_hash'),req.get('evidence_records'))
    except (ValueError,TypeError,OSError):
        raise HubError('approval_unattested','native approval evidence is unavailable') from None
    return dict(result,approval_id=req.get('approval_id'),host_attested=True,source_endpoint=ep['endpoint_id'])
