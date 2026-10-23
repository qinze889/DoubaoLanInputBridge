import argparse
import os
from pathlib import Path
import uvicorn
from .app import create_app
from .providers import Providers, ProviderConfig

parser = argparse.ArgumentParser()
parser.add_argument('--data', type=Path, required=True)
parser.add_argument('--host', default='127.0.0.1')
parser.add_argument('--port', type=int, default=18767)
args = parser.parse_args()
if args.host not in {'127.0.0.1', '::1'}:
    parser.error('Bind to loopback; use the HTTPS reverse proxy for external access')
app = create_app(args.data, admin_token=os.environ.get('SHENGJIAN_CORE_ADMIN_TOKEN'), providers=Providers(ProviderConfig.from_environment()))
uvicorn.run(app, host=args.host, port=args.port, access_log=False, ws_max_size=256*1024)
