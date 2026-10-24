import secrets,time
from fastapi.testclient import TestClient
from server.core_v2.app import PREFIX,create_app

def test_voice_diagnostics_are_private_bounded_and_reject_content(tmp_path):
    app=create_app(tmp_path,admin_token='test-admin-'+'x'*40)
    with TestClient(app) as c:
        store=app.state.store;u=store.register('voice-events','voice-events-password',store.invite(0));headers={'Authorization':'Bearer '+u['token']}
        body={'stage':'capture','code':'microphone_denied','mode':'hold'}
        assert c.post(PREFIX+'/voice/client-events',json=body).status_code==401
        assert c.post(PREFIX+'/voice/client-events',headers=headers,json={**body,'text':'private dialogue'}).status_code==422
        assert c.post(PREFIX+'/voice/client-events',headers=headers,json={**body,'code':'Bearer secret'}).status_code==422
        assert c.post(PREFIX+'/voice/client-events',headers=headers,json={**body,'stage':'prompt'}).status_code==422
        with store.tx() as db:db.execute('INSERT INTO voice_client_events VALUES(?,?,?,?,?)',(u['user_id'],'asr','voice_connection_ended','live',time.time()-8*86400))
        for _ in range(12):assert c.post(PREFIX+'/voice/client-events',headers=headers,json=body).status_code==200
        assert c.post(PREFIX+'/voice/client-events',headers=headers,json=body).status_code==429
        assert store.db.execute('SELECT COUNT(*) FROM voice_client_events').fetchone()[0]==12
        assert c.get(PREFIX+'/voice/client-events',headers=headers).status_code==405
        for asset in ['voice-flow.js','push-to-talk.js']:assert c.get(PREFIX+'/console/'+asset).status_code==200
