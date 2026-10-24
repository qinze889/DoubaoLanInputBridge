import secrets
import pytest
from fastapi.testclient import TestClient
from server.core_v2.app import PREFIX,create_app
from server.core_v2.store import Fault


def test_unlimited_is_admin_only_and_usage_keeps_original_billing_mode(tmp_path):
    app=create_app(tmp_path,admin_token='test-admin-'+'x'*40)
    with TestClient(app) as c:
        store=app.state.store;u=store.register('quota-user','quota-password-1234',store.invite(0));uid=u['user_id'];auth={'Authorization':'Bearer '+u['token']};admin={'Authorization':'Bearer '+'test-admin-'+'x'*40}
        body={'user_id':uid,'unlimited':True,'request_id':secrets.token_hex(16)}
        assert c.patch(PREFIX+'/admin/quota',headers=auth,json=body).status_code==401
        assert c.patch(PREFIX+'/admin/quota',headers=admin,json=body).json()['unlimited']
        assert c.patch(PREFIX+'/admin/quota',headers=admin,json=body).status_code==200
        assert c.get(PREFIX+'/me',headers=auth).json()['unlimited']
        store.reserve(uid,'free-image',10000,'fp');store.set_unlimited(uid,False,secrets.token_hex(16));store.settle(uid,'free-image',10000)
        assert store.wallet(uid)=={'balance':0,'reserved':0}
        with pytest.raises(Fault,match='insufficient_credits'):store.reserve(uid,'limited-again',1,'fp')
        store.credit(uid,100,secrets.token_hex(16));store.reserve(uid,'old-paid',50,'fp');store.set_unlimited(uid,True,secrets.token_hex(16));store.settle(uid,'old-paid',10)
        assert store.wallet(uid)=={'balance':90,'reserved':0}
        assert store.usages(uid)[0]['state']=='settled'
