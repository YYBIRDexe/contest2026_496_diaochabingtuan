"""SSH-only local operator surface, separate from the board's HTTP endpoint."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import secrets
import sqlite3
from urllib.parse import urlsplit
try:
    from .human_control import Ledger, Conflict, read_key, unique
except ImportError:
    from human_control import Ledger, Conflict, read_key, unique

PAGE = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>巡检告警 · 人工处理</title>
<style>body{font:17px system-ui,sans-serif;background:#edf3f6;color:#18384a;margin:24px auto;padding:0 20px;max-width:1100px}header,p{line-height:1.6}article{background:white;padding:20px;margin:18px 0;border-left:6px solid #d74b42;border-radius:8px}article.closed{border-color:#238565}h1{font-size:28px}h2{font-size:21px;margin-top:0}small{display:block;color:#486274;overflow-wrap:anywhere}label{display:block;margin:12px 0}input[type=text]{padding:10px;max-width:90%;width:420px;border:1px solid #96aabb;border-radius:5px;font:inherit}button{font:inherit;padding:10px 16px;margin:5px 8px 5px 0;background:#086894;color:white;border:0;border-radius:6px;cursor:pointer}button:disabled{opacity:.45;cursor:default}#message{min-height:30px;font-weight:600}.hint{color:#486274}</style>
<header><h1>巡检告警 · 人工处理</h1><p>回放验收环境 · 操作发送给 Gemini，收到板端保存确认后生效。</p></header>
<label>操作人标识 <input id="actor" type="text" maxlength="32" value="operator" autocomplete="off"></label>
<p id="message" role="status" aria-live="polite">正在读取平台记录…</p><main id="events"></main>
<script>
const csrf='__TOKEN__';let busy=false;const labels={REQUIRED:'待接单',CLAIMED:'已接单',HANDLED:'待复核关闭',CLOSED:'已复核关闭',NOT_REQUIRED:'无需人工'};
function element(tag,text){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e}
async function refresh(){if(busy||document.activeElement?.matches('#events input[type=text]'))return;try{const r=await fetch('/operations');if(!r.ok)throw Error('连接失败');const list=await r.json();const root=document.querySelector('#events');const drafts={};for(const old of root.children){const note=old.querySelector('[data-note]');const check=old.querySelector('[data-check]');drafts[old.dataset.notice]={note:note?.value,check:check?.checked}}
root.replaceChildren();for(const row of list){const n=row.notice,e=n.event;const card=element('article');card.dataset.notice=n.notification_id;card.className=row.human_state==='CLOSED'?'closed':'';card.append(element('h2',e.tag_id+' · '+n.assessment.score+'分 · '+labels[row.human_state]));card.append(element('small',e.event_id+' / 版本 '+e.revision+' / '+e.robot_id+' / '+e.mode));card.append(element('p','历史升级分：'+(n.escalation_score??'未记录')+'；接单人：'+(row.actor||'尚无')));
if(row.waiting)card.append(element('p','等待 Gemini 确认：'+row.waiting.step+'。当前状态尚未变更。'));if(row.last_action?.outcome?.endsWith('REJECTED'))card.append(element('p','上次操作被板端拒绝：'+row.last_action.outcome));
const note=element('input');note.type='text';note.dataset.note='1';note.placeholder='处理或复核说明（必填）';note.maxLength=120;note.value=drafts[n.notification_id]?.note||'';const lab=element('label','说明 ');lab.append(note);card.append(lab);
const checked=element('input');checked.type='checkbox';checked.dataset.check='1';checked.checked=!!drafts[n.notification_id]?.check;const verify=element('label');verify.append(checked,document.createTextNode('我已人工复核本版本的回放事件，确认可关闭'));card.append(verify);
for(const [step,title,required] of [['CLAIM','接单','REQUIRED'],['HANDLE','提交处理结果','CLAIMED'],['CLOSE','复核通过并关闭','HANDLED']]){const b=element('button',title);b.disabled=!!row.waiting||row.human_state!==required||!['GEMINI_REPLAY_NATIVE_C','HOST_NATIVE_C_TRANSPORT_TEST'].includes(n.source);b.onclick=()=>act(e,step,note.value,checked.checked);card.append(b)}root.append(card)}document.querySelector('#message').textContent='已读取 '+list.length+' 个事件的最新版本；“已送达”不等于人工处理完成。'}catch(err){document.querySelector('#message').textContent='连接中断：无法确认最新状态，请勿依据旧页面操作。';document.querySelectorAll('button').forEach(b=>b.disabled=true)}}
async function act(e,step,note,verified){if(busy)return;if(!note.trim()){document.querySelector('#message').textContent='请填写说明。';return}if(step==='CLOSE'&&!verified){document.querySelector('#message').textContent='关闭前请完成人工复核并勾选确认。';return}busy=true;document.querySelectorAll('button').forEach(b=>b.disabled=true);try{const req={request_id:crypto.randomUUID(),event_id:e.event_id,revision:e.revision,step,actor:document.querySelector('#actor').value,note,verified:step==='CLOSE'};const r=await fetch('/actions',{method:'POST',headers:{'Content-Type':'application/json','X-Spine-Operator':csrf},body:JSON.stringify(req)});const result=await r.json();if(!r.ok)throw Error(result.error||'提交失败');document.querySelector('#message').textContent='已提交，等待 Gemini 保存确认。'}catch(err){document.querySelector('#message').textContent='操作未完成：'+err.message}finally{busy=false;setTimeout(refresh,700)}}
refresh();setInterval(refresh,2500);
</script></html>'''

def make_operator_server(path, key, port=0, origins=()):
    ledger = Ledger(path, key)
    token = secrets.token_urlsafe(32)
    permitted = set(origins)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def setup(self):
            super().setup()
            self.connection.settimeout(5)
        def valid_host(self):
            return self.headers.get('Host') in {urlsplit(o).netloc for o in permitted}
        def reply(self, code, obj, mime='application/json; charset=utf-8'):
            data = obj.encode() if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(data)
        def do_GET(self):
            if not self.valid_host():
                return self.reply(403, dict(error='HOST_REJECTED'))
            if self.path == '/':
                return self.reply(200, PAGE.replace('__TOKEN__', token), 'text/html; charset=utf-8')
            if self.path == '/operations':
                return self.reply(200, ledger.view())
            self.reply(404, dict(error='NOT_FOUND'))
        def do_POST(self):
            if not self.valid_host() or self.headers.get('Origin') not in permitted or not secrets.compare_digest(self.headers.get('X-Spine-Operator', ''), token):
                return self.reply(403, dict(error='OPERATOR_SESSION_REQUIRED'))
            if self.path != '/actions':
                return self.reply(404, dict(error='NOT_FOUND'))
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if self.headers.get('Content-Type') != 'application/json' or not 0 < length <= 2048:
                    raise ValueError('size or content type')
                request = json.loads(self.rfile.read(length).decode(), object_pairs_hook=unique)
                self.reply(202, ledger.queue(request))
            except Conflict as exc:
                self.reply(409, dict(error=str(exc)))
            except (ValueError, TypeError, KeyError, UnicodeError):
                self.reply(400, dict(error='INVALID_REQUEST'))
            except sqlite3.Error:
                self.reply(503, dict(error='STORAGE_UNAVAILABLE'))
    server = HTTPServer(('127.0.0.1', port), Handler)
    permitted.add(f'http://127.0.0.1:{server.server_port}')
    server.ledger = ledger
    return server

if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--db', required=True)
    p.add_argument('--key-file', required=True)
    p.add_argument('--port', type=int, default=8133)
    p.add_argument('--origin', action='append', default=[])
    args = p.parse_args()
    server = make_operator_server(args.db, read_key(args.key_file), args.port, args.origin)
    print(f'OPERATOR LOOPBACK {server.server_port}', flush=True)
    server.serve_forever()
