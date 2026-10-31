#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本机自测：模拟音箱 client 连上网关，发送 instruction 事件，
不需要音箱参与即可验证「识别 -> 匹配 -> 执行 -> 确认语」整条链路。

用法:  python selftest.py 打开QQ
"""
import asyncio
import json
import os
import sys
import uuid

import websockets

URI = "ws://127.0.0.1:%s" % os.environ.get("GATEWAY_PORT", "4399")


def event_text(text, dialog="d1"):
    """按真实链路封装一条最终识别事件：
    client 上报 {"Event":{data={"NewLine":"<日志行JSON>"}}}，日志行内才是 payload"""
    line = json.dumps({
        "header": {"dialog_id": dialog, "id": uuid.uuid4().hex,
                   "name": "RecognizeResult", "namespace": "SpeechRecognizer"},
        "payload": {"is_final": True, "is_vad_begin": False,
                    "results": [{"confidence": 0.9, "text": text}]},
    }, ensure_ascii=False)
    return json.dumps({"Event": {
        "id": uuid.uuid4().hex,
        "event": "instruction",
        "data": {"NewLine": line},
    }}, ensure_ascii=False)


async def main():
    text = sys.argv[1] if len(sys.argv) > 1 else "打开QQ"
    async with websockets.connect(URI) as ws:
        print(f"[模拟client] 已连接，发送识别文本: {text}")
        await ws.send(event_text(text))
        try:
            while True:
                msg = await asyncio.wait_for(ws.recv(), timeout=5)
                if isinstance(msg, bytes):
                    continue
                kind, body = ("Request", json.loads(msg).get("Request")) if '"Request"' in msg else (None, None)
                if kind == "Request" and body:
                    print(f"[模拟client] 收到网关指令: {body.get('command')} payload={body.get('payload')!r}")
                    await ws.send(json.dumps({"Response": {
                        "id": body.get("id"), "code": 0, "msg": "success"}}))
                else:
                    print(f"[模拟client] 其他消息: {msg[:200]}")
        except asyncio.TimeoutError:
            print("[模拟client] 5秒内无更多消息，结束")
    print("提示: 请观察屏幕（应用是否启动/关闭）和网关窗口日志。")


if __name__ == "__main__":
    asyncio.run(main())
