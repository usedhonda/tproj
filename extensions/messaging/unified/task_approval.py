"""Read direct native approval evidence; never accept message text as authority."""
from __future__ import annotations
import hashlib
import json
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
