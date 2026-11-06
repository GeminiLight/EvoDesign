# WP25 acceptance-review script (see migration/PHASE2_REPORT.md §3).
import json, time, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
class H(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def do_POST(self):
        n=int(self.headers.get('content-length',0)); raw=self.rfile.read(n)
        sc=self.path.split('/')[1]
        if sc.startswith('echo'):
            body=json.loads(raw or b'{}')
            with open(sys.argv[2], 'a') as fh:
                fh.write(json.dumps({'tag': sc, 'path': self.path, 'body': body, 'headers': {k.lower(): v for k, v in self.headers.items() if k.lower() in ('user-agent', 'authorization', 'x-test')}}) + '\n')
            if body.get('stream'):
                self.send_response(200); self.send_header('content-type','text/event-stream'); self.end_headers()
                self.wfile.write(b'data: {"id":"x","object":"chat.completion.chunk","created":1,"model":"m","choices":[{"index":0,"delta":{"role":"assistant","content":"ok"},"finish_reason":null}]}\n\n')
                self.wfile.write(b'data: {"id":"x","object":"chat.completion.chunk","created":1,"model":"m","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'); return
            b=json.dumps({"id":"x","object":"chat.completion","created":1,"model":"m","choices":[{"index":0,"message":{"role":"assistant","content":"ok"},"finish_reason":"stop"}]}).encode()
            self.send_response(200); self.send_header('content-type','application/json'); self.send_header('content-length',str(len(b))); self.end_headers(); self.wfile.write(b); return
        def send(code, body):
            b=json.dumps(body).encode(); self.send_response(code); self.send_header('content-type','application/json'); self.send_header('content-length',str(len(b))); self.end_headers(); self.wfile.write(b)
        if sc=='s429q': send(429, {"error":{"message":"You exceeded your current quota","type":"insufficient_quota","code":"insufficient_quota"}})
        elif sc=='s429': send(429, {"error":{"message":"Rate limit reached","type":"requests","code":"rate_limit_exceeded"}})
        elif sc=='s503': send(503, {"error":{"message":"Service unavailable","type":"server_error"}})
        elif sc=='s401': send(401, {"error":{"message":"bad key","type":"invalid_request_error","code":"invalid_api_key"}})
        elif sc=='s400': send(400, {"error":{"message":"bad request","type":"invalid_request_error"}})
        elif sc=='s404': send(404, {"error":{"message":"no model","type":"invalid_request_error"}})
        elif sc=='slow': time.sleep(3); send(200, {})
        elif sc=='badsse':
            self.send_response(200); self.send_header('content-type','text/event-stream'); self.end_headers()
            self.wfile.write(b'data: {"id":"x","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"hi"}}]}\n\n'); self.wfile.write(b'data: {not json\n\n'); self.wfile.flush()
        elif sc=='cut':
            self.send_response(200); self.send_header('content-type','text/event-stream'); self.end_headers()
            self.wfile.write(b'data: {"id":"x","object":"chat.completion.chunk","created":1,"model":"m","choices":[{"index":0,"delta":{"content":"hi"}}]}\n\n'); self.wfile.flush(); self.connection.shutdown(2)
        elif sc=='empty':
            self.send_response(200); self.send_header('content-type','text/event-stream'); self.end_headers(); self.wfile.write(b'data: [DONE]\n\n')
        else: send(500, {"error":{"message":"overloaded"}})
ThreadingHTTPServer(('127.0.0.1', int(sys.argv[1])), H).serve_forever()
