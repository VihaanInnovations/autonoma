import subprocess
import threading
import json
import logging
import os
import time
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

class LSPClient:
    """
    A robust JSON-RPC client for communicating with Language Server Protocol (LSP) servers.
    Initially supports python-lsp-server (pylsp).
    """

    def __init__(self, cmd: str = "pylsp", cwd: str = None):
        self.cmd = cmd
        self.cwd = cwd or os.getcwd()
        self.process = None
        self.request_id = 0
        self.lock = threading.Lock()
        self.running = False
        self._responses = {}  # Store responses by request ID (simple sync mechanism for now)

    def start(self):
        """Start the LSP server subprocess."""
        try:
            self.process = subprocess.Popen(
                self.cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=True,
                cwd=self.cwd
            )
            self.running = True
            threading.Thread(target=self._read_loop, daemon=True).start()
            logger.info(f"LSP Client started: {self.cmd}")
            # Initialize immediately
            self.initialize()
        except Exception as e:
            logger.error(f"Failed to start LSP client: {e}")
            raise

    def stop(self):
        """Stop the LSP server."""
        if self.running and self.process:
            self.send_request("shutdown")
            self.send_notification("exit")
            self.process.terminate()
            self.running = False
            logger.info("LSP Client stopped.")

    def _make_header(self, content_length: int) -> bytes:
        return f"Content-Length: {content_length}\r\n\r\n".encode('utf-8')

    def send_request(self, method: str, params: Optional[Dict] = None) -> Any:
        """Send a request and wait for the response (synchronous)."""
        with self.lock:
            self.request_id += 1
            curr_id = self.request_id
            
        request = {
            "jsonrpc": "2.0",
            "id": curr_id,
            "method": method,
            "params": params or {}
        }
        
        self._send(request)
        
        # Wait for response (simple polling for now, could use Condition)
        # TODO: Add timeout
        start_time = time.time()
        while time.time() - start_time < 30.0: # 30s timeout
            if curr_id in self._responses:
                response = self._responses.pop(curr_id)
                if 'error' in response:
                    raise RuntimeError(f"LSP Error: {response['error']}")
                return response.get('result')
            time.sleep(0.01)
            
        raise TimeoutError(f"LSP Request {method} timed out")

    def send_notification(self, method: str, params: Optional[Dict] = None):
        """Send a notification (no response expected)."""
        request = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {}
        }
        self._send(request)

    def _send(self, payload: Dict):
        if not self.process:
            raise RuntimeError("LSP process not running")
            
        body = json.dumps(payload).encode('utf-8')
        header = self._make_header(len(body))
        
        try:
            self.process.stdin.write(header + body)
            self.process.stdin.flush()
        except BrokenPipeError:
            logger.error("LSP Server connection lost")
            self.running = False

    def _read_loop(self):
        """Read stdout from the LSP server."""
        while self.running and self.process:
            try:
                # 1. Read Header
                line = self.process.stdout.readline()
                if not line:
                    break
                
                line = line.strip()
                if not line: continue
                
                content_length = 0
                if line.startswith(b"Content-Length: "):
                    content_length = int(line.split(b": ")[1])
                
                # Consume empty line after header
                while True:
                    next_line = self.process.stdout.readline()
                    if next_line == b'\r\n' or next_line == b'\n':
                        break
                
                # 2. Read Body
                if content_length > 0:
                    body = self.process.stdout.read(content_length)
                    message = json.loads(body)
                    
                    if 'id' in message:
                        # It's a response to a request
                        self._responses[int(message['id'])] = message
                    else:
                        # Log notifications
                        logger.debug(f"LSP Notification: {message.get('method')}")
                        
            except Exception as e:
                logger.error(f"Error in LSP read loop: {e}")
                break

    # --- High Level Methods ---

    def initialize(self):
        cwd = self.cwd
        params = {
            "processId": os.getpid(),
            "rootUri": f"file:///{cwd.replace(os.sep, '/')}",
            "capabilities": {}
        }
        self.send_request("initialize", params)
        self.send_notification("initialized", {})

    def did_open(self, file_path: str, content: str):
        uri = f"file:///{file_path.replace(os.sep, '/')}"
        params = {
            "textDocument": {
                "uri": uri,
                "languageId": "python",
                "version": 1,
                "text": content
            }
        }
        self.send_notification("textDocument/didOpen", params)

    def document_symbol(self, file_path: str) -> List[Dict]:
        uri = f"file:///{file_path.replace(os.sep, '/')}"
        params = {
            "textDocument": { "uri": uri }
        }
        return self.send_request("textDocument/documentSymbol", params)
