"""Interactive enrollment; stores only a scoped device token in private local config."""
import argparse
import getpass
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import urllib.request
import venv

REPOSITORY = Path(__file__).resolve().parents[1]
SERVER = 'https://test.xjiaoai.com/shengjian/api/v2'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def api(path, token='', body=None, method=None):
    request = urllib.request.Request(SERVER+path, data=json.dumps(body).encode() if body is not None else None,
        method=method, headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    with urllib.request.build_opener(NoRedirect).open(request,timeout=30) as response:
        return json.load(response)


def private_json(path, value):
    fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as output:
        json.dump(value,output,ensure_ascii=False,indent=2)


def main():
    parser=argparse.ArgumentParser(description='登记电脑，授权指定工作目录的 Agent 任务和系统状态监控。')
    parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--name',default='我的 '+('Mac' if sys.platform=='darwin' else '电脑'))
    parser.add_argument('--data',type=Path)
    parser.add_argument('--autostart',action='store_true',help='登录系统时启动此连接器（Mac LaunchAgent / Windows 启动目录）')
    args=parser.parse_args()
    workspace=args.workspace.expanduser().resolve()
    if workspace in {Path.home(),Path(workspace.anchor)}:
        parser.error('请使用独立任务目录，不要选择用户主目录或磁盘根目录')
    if args.autostart and sys.platform not in {'darwin','win32'}:
        parser.error('本安装器的自动启动仅支持 Mac 和 Windows')
    root=args.data or (Path.home()/'Library/Application Support/ShengjianAgent' if sys.platform=='darwin' else Path(os.environ.get('LOCALAPPDATA',Path.home()/'.local/share'))/'ShengjianAgent')
    root=root.expanduser().resolve();root.mkdir(parents=True,exist_ok=True,mode=0o700)
    config=root/'device.json'
    if config.exists():
        parser.error('设备已登记；请使用现有配置运行，或先在账号设备页撤销后人工移走旧配置')
    node,npm=shutil.which('node'),shutil.which('npm')
    if not node or not npm:
        parser.error('请先安装 Node.js（含 npm），再运行安装器')
    runtime=root/'python'
    if not (runtime/('Scripts/python.exe' if os.name=='nt' else 'bin/python')).exists():
        venv.EnvBuilder(with_pip=True).create(runtime)
    python=runtime/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    subprocess.run([str(python),'-m','pip','install','--disable-pip-version-check','-r',str(REPOSITORY/'server/requirements-agent.txt')],check=True)
    harness=root/'harness'
    npm_command = [node,str(Path(npm).parent/'node_modules/npm/bin/npm-cli.js')] if os.name=='nt' else [npm]
    subprocess.run([*npm_command,'install','--prefix',str(harness),'--save-exact','--ignore-scripts','@deepseek-ai/dsh@0.2.1-rc.2'],check=True)
    app=root/'app';(app/'server').mkdir(parents=True,exist_ok=True)
    shutil.copytree(REPOSITORY/'server/desktop_agent',app/'server/desktop_agent',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__'))
    print('请输入声笺账号；密码仅用于本次登录，不会保存。')
    username=input('用户名：').strip();password=getpass.getpass('密码：')
    identity=api('/auth/login',body={'username':username,'password':password})
    password=''
    session=identity['token']
    device=None
    try:
        models=api('/models',session)['data']
        model=next(m['id'] for m in models if 'text' in m['input_modalities'])
        device=api('/devices',session,{'name':args.name,'capabilities':['tasks','metrics']})
        workspace.mkdir(parents=True,exist_ok=True)
        value={'server':SERVER,'device_id':device['id'],'token':device['token'],'workspace':str(workspace),
               'text_model':model,'harness_executable':[node,str(harness/'node_modules/@deepseek-ai/dsh/lib/bin.js')]}
        codex=shutil.which('codex')
        if codex:value['codex_executable']=codex
        private_json(config,value)
        api('/devices/'+device['id'],session,{'grants':['tasks','metrics']},method='PATCH')
    except Exception:
        if device:
            api('/devices/'+device['id'],session,method='DELETE')
            config.unlink(missing_ok=True)
        raise
    finally:
        api('/auth/logout',session,{})
    command=[str(python),'-m','server.desktop_agent','--config',str(config),'--data',str(root/'state')]
    if args.autostart and sys.platform=='darwin':
        target=Path.home()/'Library/LaunchAgents/com.shengjian.desktop-agent.plist'
        if target.exists():raise SystemExit('已有自动启动文件；请检查后手动启动，安装器未覆盖。')
        target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('wb') as output:plistlib.dump({'Label':'com.shengjian.desktop-agent','ProgramArguments':command,'WorkingDirectory':str(app),'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':15,'StandardOutPath':'/dev/null','StandardErrorPath':'/dev/null'},output)
        target.chmod(0o600)
        subprocess.run(['launchctl','bootstrap','gui/'+str(os.getuid()),str(target)],check=True)
        print('电脑已登记，任务连接器将随登录启动。可在手机设备页撤销其授权。')
    elif args.autostart and sys.platform=='win32':
        startup=Path(os.environ['APPDATA'])/'Microsoft/Windows/Start Menu/Programs/Startup/ShengjianAgent.vbs'
        if startup.exists():raise SystemExit('已有自动启动文件；未覆盖。')
        # Windows argument quoting is delegated to the standard library; no shell command interpolation.
        payload='Set s = CreateObject("WScript.Shell")\n'
        payload+='s.CurrentDirectory = "'+str(app).replace('"','""')+'"\n'
        line=subprocess.list2cmdline(command)
        payload+='s.Run "'+line.replace('"','""')+'", 0, False\n'
        startup.write_text(payload,encoding='utf-16')
        subprocess.Popen(command,cwd=app,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
        print('电脑已登记，任务连接器将随登录启动。可在手机设备页撤销其授权。')
    else:
        print('电脑已登记。连接器工作目录：'+str(app))
        if os.name=='nt':print(subprocess.list2cmdline(command))
        else:
            import shlex
            print(shlex.join(command))


if __name__=='__main__':
    try:main()
    except (urllib.error.URLError,subprocess.CalledProcessError):raise SystemExit('安装或账号连接失败；未输出密码及认证详情。') from None
