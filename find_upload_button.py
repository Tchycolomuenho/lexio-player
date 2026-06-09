import json, websocket, time, urllib.request, base64

# Refresh page IDs
pages = json.loads(urllib.request.urlopen('http://localhost:9222/json').read())
mf_page = None
for p in pages:
    if 'mediafire' in p['url'].lower() and 'myfiles' in p['url'].lower():
        mf_page = p
        break

if not mf_page:
    print("NO_MEDIAFIRE_PAGE")
    exit()

print(f"Using: {mf_page['url']}")
ws_url = mf_page['webSocketDebuggerUrl']

ws = websocket.create_connection(ws_url, timeout=10, origin='http://localhost:9222')

def send_cmd(ws, method, params=None, id=1):
    msg = {'id': id, 'method': method}
    if params:
        msg['params'] = params
    ws.send(json.dumps(msg))
    while True:
        resp = json.loads(ws.recv())
        if resp.get('id') == id:
            return resp

# Consume events
def consume_events(ws, count=5):
    for _ in range(count):
        try:
            ws.settimeout(0.5)
            evt = json.loads(ws.recv())
            # print(f"EVENT: {evt.get('method', '?')}")
        except:
            break

send_cmd(ws, 'Page.enable', id=1)
send_cmd(ws, 'Runtime.enable', id=2)
time.sleep(2)
consume_events(ws, 10)

# Get all buttons/interactive elements
resp = send_cmd(ws, 'Runtime.evaluate', {
    'expression': '''(function() {
        var els = document.querySelectorAll('button, a, [role=button], [data-testid]');
        var results = [];
        els.forEach(function(el, i) {
            var txt = (el.innerText || el.textContent || '').trim().substring(0, 40);
            var testid = el.getAttribute('data-testid') || '';
            var role = el.getAttribute('role') || '';
            var aria = el.getAttribute('aria-label') || '';
            var cls = (el.className || '').substring(0, 60);
            var href = el.href || '';
            var tag = el.tagName;
            results.push({i: i, tag: tag, text: txt, testid: testid, aria: aria, role: role, cls: cls, href: href.substring(0, 100)});
        });
        return JSON.stringify(results);
    })()'''
}, id=3)

consume_events(ws, 5)
result = resp.get('result', {}).get('result', {}).get('value', '[]')
buttons = json.loads(result)

# Look for upload-related buttons
for b in buttons:
    txt_upper = (b['text'] + ' ' + b['aria'] + ' ' + b['testid']).upper()
    if 'UPLOAD' in txt_upper or 'ADD' in txt_upper or 'NEW' in txt_upper or 'CREATE' in txt_upper:
        print(f"FOUND: {b}")

print("\n--- ALL BUTTONS ---")
for b in buttons:
    if b['text'] or b['aria'] or b['testid']:
        print(f"[{b['i']}] tag={b['tag']} text='{b['text']}' aria='{b['aria']}' testid='{b['testid']}'")

ws.close()
