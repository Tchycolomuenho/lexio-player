import json, websocket, time, urllib.request

pages = json.loads(urllib.request.urlopen('http://localhost:9222/json').read())
mf_page = None
for p in pages:
    if 'app.mediafire.com' in p['url']:
        mf_page = p
        break
if not mf_page:
    print("NO_MEDIAFIRE_PAGE")
    exit()

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

def consume(n=10):
    for _ in range(n):
        try: ws.settimeout(0.3); ws.recv()
        except: pass

send_cmd(ws, 'Page.enable', id=1)
send_cmd(ws, 'Runtime.enable', id=2)
time.sleep(2)
consume(10)

# Check the Photos folder which has 9 files - maybe the user uploaded there?
# First let's see what the file list actually shows
resp = send_cmd(ws, 'Runtime.evaluate', {
    'expression': '''(function() {
        // Get all file/folder names from the page
        var allDivs = document.querySelectorAll('div, span, button');
        var items = [];
        allDivs.forEach(function(el) {
            var txt = (el.innerText || el.textContent || '').trim();
            if (txt && txt.length > 3 && txt.length < 60) {
                items.push(txt);
            }
        });
        return JSON.stringify(items);
    })()'''
}, id=3)
consume(5)
val = resp.get('result',{}).get('result',{}).get('value','')
items = json.loads(val)
# Filter interesting items
interesting = [i for i in items if 'Lexio' in i or 'Setup' in i or 'Study' in i or 'Player' in i or '.exe' in i]
print(f"File matches: {interesting}")

# Get full file listing
resp = send_cmd(ws, 'Runtime.evaluate', {
    'expression': '''(function() {
        var files = [];
        var items = document.querySelectorAll('[role=listitem], [data-file], [data-filename], .file-item, [class*=file]');
        items.forEach(function(el) {
            var t = (el.innerText || el.textContent || '').trim().substring(0, 100);
            if (t) files.push(t);
        });
        // Also check aria-labels of file items
        var fileEls = document.querySelectorAll('[aria-label*=\"file\"], [aria-label*=\"File\"]');
        fileEls.forEach(function(el) {
            files.push(el.getAttribute('aria-label'));
        });
        return JSON.stringify(files.slice(0, 30));
    })()'''
}, id=4)
consume(5)
val2 = resp.get('result',{}).get('result',{}).get('value','[]')
file_items = json.loads(val2)
print(f"File items: {file_items}")

# Also check the full innerHTML for LexioStudyPlayer
resp = send_cmd(ws, 'Runtime.evaluate', {
    'expression': '''(function() {
        var html = document.body?.innerHTML || '';
        var idx = html.indexOf('LexioStudyPlayer');
        var snippet = '';
        if (idx >= 0) {
            snippet = html.substring(Math.max(0, idx-100), idx + 200);
        }
        return JSON.stringify({found: idx >= 0, snippet: snippet});
    })()'''
}, id=5)
consume(3)
val3 = resp.get('result',{}).get('result',{}).get('value','{}')
print(f"\nSearch for 'LexioStudyPlayer' in DOM: {val3}")

ws.close()
