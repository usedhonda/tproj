#!/usr/bin/env python3
"""Reject unsupported Responses parents while preserving image and face outputs."""
import base64, contextlib, io, json, re, sys
from pathlib import Path
from unittest.mock import patch
import urllib.error
source_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / 'extensions/persona/tproj-pane-bg'
source = source_path.read_text()
import tempfile
workspace = tempfile.TemporaryDirectory()
root = Path(workspace.name)
auth = root / 'fixture-auth.json'
auth.write_text(json.dumps({'tokens': {'access_token': 'fixture-token', 'account_id': 'fixture-account'}}))
image = root / 'fixture.png'
image.write_bytes(b'fixture')
match = re.search(r'^GPT_IMAGE_RESPONSE_MODEL="([^"]+)"', source, re.M)
parent = match.group(1) if match else 'gpt-5.5'
for function in ('request_gpt_image', 'gpt_face_box_norm'):
    code = re.search(r'^' + function + r"\(\).*?<<'PY'\n(.*?)\nPY", source, re.M | re.S).group(1)
    response_path = root / 'fixture-response.json'
    argv = (['-', 'portrait', 'avoid', str(response_path), str(root/'fixture-error.json'),
             str(auth), 'gpt-image-2', '5', '', '1024x1536', '0', parent]
            if function == 'request_gpt_image' else ['-', str(image), str(auth), '5', parent])
    def respond(request, **kwargs):
        body = json.loads(request.data)
        if body['model'] != 'gpt-6.1-sol':
            raise urllib.error.HTTPError(request.full_url, 400, 'model_not_found', {}, io.BytesIO(b'unsupported parent'))
        if function == 'request_gpt_image':
            assert body['tools'][0]['model'] == 'gpt-image-2'
            event = {'type':'response.output_item.done', 'item':{'result':base64.b64encode(b'fixture'*1000).decode()}}
        else:
            event = {'delta':json.dumps({'x0':.2,'y0':.1,'x1':.8,'y1':.5})}
        return io.BytesIO(('data: '+json.dumps(event)+'\n').encode())
    output = io.StringIO()
    with patch.object(sys, 'argv', argv), patch('urllib.request.urlopen', respond), contextlib.redirect_stdout(output):
        exec(compile(code, function, 'exec'), {'__name__':'__main__'})
    if function == 'request_gpt_image':
        assert json.loads(response_path.read_text())['candidates']
    else:
        assert output.getvalue().strip() == '0.5000 0.3000 0.4000'
print("PASS GPT Image request and face detection use supported parent")
