import urllib.request, urllib.parse, json
base='http://127.0.0.1:8000'
ids=['a','b','c']
print('join')
for sid,name in zip(ids,['Alice','Bob','Cleo']):
    data=json.dumps({'name':name}).encode()
    req=urllib.request.Request(base+'/join?sid='+sid,data=data,headers={'Content-Type':'application/json'})
    r=urllib.request.urlopen(req)
    print(sid,r.getcode(),json.load(r))
print('lobby state')
for sid in ids:
    u=base+'/state?'+urllib.parse.urlencode({'sid':sid})
    r=urllib.request.urlopen(u)
    d=json.load(r)
    game=d.get('game') or {}
    print(sid,d.get('pid'), len(d.get('lobby',[])), game.get('started'))
print('start')
req=urllib.request.Request(base+'/start?sid=a', data=b'{}', headers={'Content-Type':'application/json'})
r=urllib.request.urlopen(req)
print(r.getcode(), json.load(r))
print('after start')
for sid in ids:
    u=base+'/state?'+urllib.parse.urlencode({'sid':sid})
    r=urllib.request.urlopen(u)
    d=json.load(r)
    print(sid,d.get('pid'), d.get('game',{}).get('started'), d.get('game',{}).get('players').keys())
