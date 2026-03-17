import urllib.request, urllib.parse, json
for sid in ['one','two','three']:
    u=urllib.parse.urlencode({'sid':sid})
    r=urllib.request.urlopen('http://127.0.0.1:8000/state?'+u)
    d=json.load(r)
    print(sid, d.get('pid'), d.get('lobby_count'), d.get('game', {}).get('started'))

print('start', urllib.request.urlopen('http://127.0.0.1:8000/start?sid=one', data=b'').read())
for sid in ['one','two','three']:
    u=urllib.parse.urlencode({'sid':sid})
    r=urllib.request.urlopen('http://127.0.0.1:8000/state?'+u)
    d=json.load(r)
    print('after', sid, d.get('pid'), d.get('lobby_count'), d.get('game', {}).get('started'))
