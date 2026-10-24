import json
import httpx
import pytest
from fastapi.testclient import TestClient
from server.core_v2.app import create_app,PREFIX
from server.core_v2.providers import Providers,ProviderConfig


@pytest.fixture
def visual(tmp_path,monkeypatch):
    monkeypatch.setenv('SHENGJIAN_LIFE_VISION_MODELS','["vision","alternative"]')
    calls=[]
    def upstream(req):
        if req.method=='GET':return httpx.Response(200,json={'data':[{'id':x} for x in ['text','vision','alternative']]})
        calls.append(json.loads(req.content))
        assert req.headers['Authorization']=='Bearer private-provider-key'
        return httpx.Response(200,content='data: {"choices":[{"delta":{"content":"红色圆形。"}}]}\n\ndata: {"usage":{"total_tokens":5}}\n\ndata: [DONE]\n\n'.encode(),headers={'content-type':'text/event-stream'})
    provider=Providers(ProviderConfig(model_base='https://model.invalid/v1',model_key='private-provider-key',text_model='text',vision_model='vision',voice_effort='low'),transport=httpx.MockTransport(upstream))
    app=create_app(tmp_path,admin_token='x'*40,providers=provider)
    one=app.state.store.register('visual-one','isolated-password-123',app.state.store.invite(1000));two=app.state.store.register('visual-two','isolated-password-123',app.state.store.invite(1000))
    image=app.state.life.store.add_image(one['user_id'],b'isolated-image',1,1,'visual-test-image-123')
    with TestClient(app) as client:yield app,client,one,two,image,calls


def question(client,user,images,**extra):
    body={'model':'text','life_images':images,'messages':[{'role':'user','content':'这张图里是什么？'}],'stream':True,'max_tokens':512,**extra}
    return client.post(PREFIX+'/model/v1/chat/completions',headers={'Authorization':'Bearer '+user['token']},json=body)


def test_private_image_refs_resolve_server_side_selected_model_stream_and_usage(visual):
    app,c,one,_,image,calls=visual
    app.state.life.store.preferences(one['user_id'],{'vision_model':'alternative'})
    r=question(c,one,[image['id']],reasoning_effort='low')
    assert r.status_code==200 and '[DONE]' in r.text and r.headers['x-vision-model']=='alternative'
    sent=calls[0];assert sent['model']=='alternative' and 'life_images' not in sent and 'reasoning_effort' not in sent
    assert sent['messages'][-1]['content'][0]['text']=='这张图里是什么？'
    assert sent['messages'][-1]['content'][1]['image_url']['url'].startswith('data:image/jpeg;base64,')
    assert '不可信' in sent['messages'][0]['content'] and 'private-provider-key' not in r.text
    from server.core_v2.providers import RESPONSE_STYLE
    assert any(m['role']=='system' and RESPONSE_STYLE in m['content'] for m in sent['messages'])
    assert app.state.store.wallet(one['user_id'])=={'balance':999,'reserved':0}


def test_cross_account_image_is_denied_without_model_call_or_charge(visual):
    app,c,one,two,image,calls=visual
    assert question(c,two,[image['id']]).status_code==404
    assert not calls and app.state.store.wallet(two['user_id'])['balance']==1000


def test_task_device_token_cannot_read_life_images(visual):
    _,c,one,_,image,calls=visual
    header={'Authorization':'Bearer '+one['token']}
    device=c.post(PREFIX+'/devices',headers=header,json={'name':'test device','capabilities':['tasks']}).json()
    c.patch(PREFIX+'/devices/'+device['id'],headers=header,json={'grants':['tasks']}).raise_for_status()
    assert question(c,{'token':device['token']},[image['id']]).status_code==401
    assert not calls


@pytest.mark.parametrize('refs',['bad',[None],['x'],['a'*32]*3])
def test_invalid_visual_refs_rejected(visual,refs):
    _,c,one,_,_,calls=visual
    assert question(c,one,refs).status_code==400 and not calls


def test_only_current_user_message_can_bind_image_and_unverified_model_is_refused(visual):
    app,c,one,_,image,calls=visual
    assert question(c,one,[image['id']],messages=[{'role':'assistant','content':'bad'}]).status_code==400
    app.state.life.store.preferences(one['user_id'],{'vision_model':'not-verified'})
    assert question(c,one,[image['id']]).status_code==409 and not calls


def test_chat_device_can_only_see_exact_attached_images_on_running_owned_turn(visual):
    app,c,one,two,image,calls=visual
    store=app.state.store
    device=store.enroll(one['user_id'],'chat desktop',['tasks'])
    store.authorize_device(one['user_id'],device['id'],['tasks'])
    other=store.enroll(one['user_id'],'other desktop',['tasks'])
    store.authorize_device(one['user_id'],other['id'],['tasks'])
    store.heartbeat(device['id'],{'harness_chat':True});app.state.peers[device['id']]=object()
    import secrets
    payload={'text':'看图并保存结果','request_id':secrets.token_hex(16),'conversation_id':secrets.token_hex(16),'life_images':[image['id']]}
    r=c.post(PREFIX+'/assistant/chat',headers={'Authorization':'Bearer '+one['token']},json=payload)
    assert r.status_code==200,r.text
    task=r.json()['task'];ident=task['id']
    assert question(c,device,[image['id']],vision_task=ident).status_code==403
    store.dispatch(device['id']);store.device_event(device['id'],ident,{'type':'task.state','state':'running'},'start')
    assert question(c,other,[image['id']],vision_task=ident).status_code==403
    # The model choice freezes with this turn; a setting change does not reroute it.
    app.state.life.store.preferences(one['user_id'],{'vision_model':'alternative'})
    r=question(c,device,[image['id']],vision_task=ident)
    assert r.status_code==200 and r.headers['x-vision-model']=='vision'
    assert 'vision_task' not in calls[-1] and 'life_images' not in calls[-1]
    assert question(c,device,['a'*32],vision_task=ident).status_code==403
    store.cancel(one['user_id'],ident)
    assert question(c,device,[image['id']],vision_task=ident).status_code==403
    app.state.peers.clear()
