"""港湾记录整理器 v1.2：明确新增的本地合成GUI，不改写历史版本事实。"""
import argparse
import json
from pathlib import Path
from wsgiref.simple_server import make_server, WSGIRequestHandler

from api import application as convert_application, error_response, respond
from core import VERSION

PAGE = Path(__file__).with_name("index.html").read_bytes()


def application(environ, start_response):
    host = environ.get("HTTP_HOST", "")
    expected = "127.0.0.1:" + environ.get("SERVER_PORT", "")
    if host != expected:
        return error_response(start_response, "403 Forbidden", "local_host_required")
    origin = environ.get("HTTP_ORIGIN")
    if origin is not None and origin != "http://" + expected:
        return error_response(start_response, "403 Forbidden", "origin_rejected")
    path = environ.get("PATH_INFO")
    method = environ.get("REQUEST_METHOD")
    headers = [("Cache-Control", "no-store"), ("X-Content-Type-Options", "nosniff"),
               ("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'")]
    if path == "/" and method == "GET":
        return respond(start_response, "200 OK", PAGE, "text/html; charset=utf-8", headers)
    if path == "/version" and method == "GET":
        return respond(start_response, "200 OK", json.dumps({"name": "港湾记录整理器", "version": VERSION}, ensure_ascii=False).encode(), "application/json; charset=utf-8", headers)
    return convert_application(environ, start_response)


class QuietHandler(WSGIRequestHandler):
    def log_message(self, format, *args):
        pass


def main():
    parser = argparse.ArgumentParser(description="本地合成GUI；仅监听127.0.0.1，无用户认证")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--synthetic", action="store_true", required=True)
    args = parser.parse_args()
    with make_server("127.0.0.1", args.port, application, handler_class=QuietHandler) as server:
        print(json.dumps({"url": "http://127.0.0.1:" + str(server.server_port), "version": VERSION}), flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
