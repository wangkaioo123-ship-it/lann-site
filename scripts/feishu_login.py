"""
一次性授权脚本：在本机起一个小服务接住飞书回调，完成"以王凯身份"的登录。

流程：
  1) 启动本地服务监听 http://localhost:8765/callback
  2) 打印授权链接，你在浏览器打开并点"授权"
  3) 浏览器自动跳回本机，脚本拿到授权码并换成 user token，存到 secrets/
  授权一次即可，之后会自动用 refresh_token 续期。

运行：python -m scripts.feishu_login
"""

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

from services import feishu_oauth

_HOST = "localhost"
_PORT = 8765

# 用于在回调线程与主线程间传递授权码
_holder = {"code": None, "error": None}
_done = threading.Event()


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        code = query.get("code", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        if code:
            _holder["code"] = code
            msg = "授权成功！可以关闭这个页面，回到 Claude 这边即可。"
        else:
            _holder["error"] = self.path
            msg = "没拿到授权码，请回到 Claude 这边看提示。"
        self.wfile.write(f"<html><body style='font-family:sans-serif;font-size:18px'>{msg}</body></html>".encode("utf-8"))
        _done.set()

    def log_message(self, *args):
        pass  # 静音 http 日志


def main():
    server = HTTPServer((_HOST, _PORT), _CallbackHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    url = feishu_oauth.build_authorize_url()
    print("请在浏览器打开下面这个链接，登录并点【授权】：\n")
    print(url)
    print("\n（正在等待你完成授权……最多等 5 分钟）")

    if not _done.wait(timeout=300):
        print("\n超时未收到授权，请重试。")
        server.shutdown()
        return

    server.shutdown()
    if _holder["error"]:
        print(f"\n授权回调异常：{_holder['error']}")
        return

    print("\n已收到授权码，正在换取 token ...")
    data = feishu_oauth.exchange_code(_holder["code"])
    print("✅ 登录成功！user token 已保存到 secrets/，有效期内自动续期。")
    print(f"   （scope={data.get('scope', '(未返回)')}）")


if __name__ == "__main__":
    main()
