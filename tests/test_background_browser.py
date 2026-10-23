from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import time

import pytest

from server.desktop_agent.browser import BackgroundBrowser


@pytest.mark.skipif(not Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome').exists(), reason='real installed Chrome integration check')
def test_background_browser_fill_click_and_stale_ids_preserve_foreground(tmp_path):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b'''<title>Local agent fixture</title><label>Message <input aria-label="Message" id="message"></label>
              <button onclick="document.querySelector('#result').textContent=document.querySelector('#message').value">Apply</button>
              <p id="result">empty</p><input type="password" aria-label="Secret">'''
            self.send_response(200); self.send_header('Content-Type', 'text/html'); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    from AppKit import NSWorkspace
    front = NSWorkspace.sharedWorkspace().frontmostApplication().processIdentifier()
    browser = BackgroundBrowser(tmp_path/'profile')
    try:
        assert browser.perform({'action': 'navigate', 'url': f'http://127.0.0.1:{server.server_port}'})['background']
        for _ in range(20):
            state = browser.perform({'action': 'observe'})
            if state['title'] == 'Local agent fixture': break
            time.sleep(.1)
        field = next(n['id'] for n in state['nodes'] if n['name'] == 'Message')
        assert browser.perform({'action': 'fill', 'generation': state['generation'], 'element': field, 'text': 'background success'})['ok']
        with pytest.raises(ValueError, match='stale_browser_element'):
            browser.perform({'action': 'click', 'generation': state['generation'], 'element': field})
        state = browser.perform({'action': 'observe'})
        button = next(n['id'] for n in state['nodes'] if n['name'] == 'Apply')
        assert browser.perform({'action': 'click', 'generation': state['generation'], 'element': button})['ok']
        state = browser.perform({'action': 'observe'})
        assert 'background success' in state['text']
        password = next(n['id'] for n in state['nodes'] if n['type'] == 'password')
        assert not browser.perform({'action': 'fill', 'generation': state['generation'], 'element': password, 'text': 'rejected'})['ok']
        assert NSWorkspace.sharedWorkspace().frontmostApplication().processIdentifier() == front
        assert browser.process.poll() is None
    finally:
        browser.close(); server.shutdown(); server.server_close(); thread.join(timeout=5)
    assert browser.process is None
