"""Explicit task and protocol descriptors; model names never imply a capability.

Design reference: Magpie catalog.Model separates provider, APIs and input/output
modalities. Here verified role allowlists remain authoritative for availability.
"""
from fastapi import Depends

ROLES = {
    'chat': ('聊天与工作', ['text'], ['text'], 'chat_completions'),
    'vision': ('识图', ['text','image'], ['text'], 'chat_completions'),
    'image_generate': ('生图', ['text'], ['image'], 'responses'),
    'image_edit': ('改图', ['text','image'], ['image'], 'images_edits'),
}


def describe(model, role):
    label, inputs, outputs, protocol = ROLES[role]
    provider, _, identifier = model.partition('/')
    provider = provider if identifier else 'configured'
    name = identifier or model
    realm = name.partition(':')[0] if provider=='workbuddy' and ':' in name else None
    return {'id':model,'provider':provider,'realm':realm,'task':role,'task_label':label,
            'input_modalities':inputs,'output_modalities':outputs,'protocol':protocol,
            'verified':True,'availability_basis':'verified_role_allowlist'}


def mount(app, providers, life, user):
    from .app import PREFIX

    @app.get(PREFIX+'/models/capabilities')
    async def capabilities(uid=Depends(user)):
        if not providers or not providers.readiness()['models']:return {'ok':True,'data':[]}
        await providers.models()
        config=providers.config
        roles={'chat':list(dict.fromkeys([config.text_model,*config.chat_models])),
               'vision':life.vision_models,'image_generate':config.image_models,'image_edit':config.image_edit_models}
        return {'ok':True,'data':[describe(mid,role) for role,models in roles.items() for mid in models if mid in providers.discovered_ids]}
