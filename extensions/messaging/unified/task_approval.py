"""Read direct native approval evidence; never accept message text as authority."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import re
from protocol import HubError


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


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


def validate_records(records, platform, intent, scope, evidence_hash):
    """An exact direct user instruction or its immediately preceding proposal."""
    plan = None
    for record in records:
        item = texts(record, platform)
        if not item: continue
        role,text = item
        if role == 'assistant':
            match = re.search(r'<proposed_plan>\s*(.*?)\s*</proposed_plan>', text, re.S)
            if match: plan = match.group(1)
            continue
        if digest(text) != evidence_hash:
            plan = None
            continue
        # Transport/hook/tool-result injections are not a user approval source.
        if re.search(r'\[from:|\[tproj-message:|\[OpenClaw Agent|<tool_result|<system-reminder|<codex_internal_context',text,re.I):
            break
        # The native user's wording is authoritative; no magic approval phrase.
        # This binds the exact scope, not a paraphrase or an agent-authored expansion.
        direct = isinstance(scope, str) and bool(scope.strip()) and scope == text
        confirms_plan = text.strip().lower() in ('implement the plan.', 'implement the plan', '実行して', '実装して', 'すすめて', '進めて', 'つづけて')
        if not direct and not (confirms_plan and plan is not None and scope.strip() == plan):
            break
        if not intent or intent not in scope:
            break
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
                if header.get('type') != 'session_meta' or meta.get('id') != tid or not meta.get('cwd') or Path(meta['cwd']).resolve() != Path(project).resolve():
                    raise HubError('approval_unattested','native transcript header does not match bound conversation')
            else:
                def bound_records(source):
                    for row in source:
                        if row.get('type') in ('user','assistant'):
                            if row.get('sessionId') != tid or not row.get('cwd') or Path(row['cwd']).resolve() != Path(project).resolve():
                                raise HubError('approval_unattested','native transcript record does not match bound conversation')
                        yield row
                records = bound_records(records)
            result=validate_records(records,platform,req.get('intent'),req.get('scope'),req.get('evidence_hash'))
    except (ValueError,TypeError,OSError):
        raise HubError('approval_unattested','native approval evidence is unavailable') from None
    return dict(result,approval_id=req.get('approval_id'),host_attested=True,source_endpoint=ep['endpoint_id'])
