#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小爱语音遥控电脑（open-xiaoai 网关 · 最小版）

监听 ws://0.0.0.0:4399，接收小爱音箱 client 转发的语音识别事件，
匹配「打开/关闭 + 应用名」后在电脑上执行，并用音箱原生 TTS 播确认语。

协议参考: https://github.com/coderzc/open-xiaoai packages/client-rust
  - 文本帧: {"Request":{id,command,payload}} / {"Event":{id,event,data}} / {"Response":{id,code,msg,data}}
  - 二进制帧: 音频流 Stream JSON（本版本用不到，忽略）
  - run_shell 的 payload 是裸字符串命令（不是对象）
  - client 断线后每秒自动重连，服务重启无需动音箱
"""
import asyncio
import ctypes
import json
import logging
import os
import re
import socket
import subprocess
import sys
import time
import uuid
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from ctypes import wintypes
from pathlib import Path
from urllib.parse import quote

import numpy as np
import websockets

BASE_DIR = Path(__file__).resolve().parent
APPS_FILE = BASE_DIR / "apps.json"
LOG_FILE = BASE_DIR / "gateway.log"
SPEAKER_FILE = BASE_DIR / "speaker.json"   # 扫描发现的音箱 IP 记录

HOST, PORT = "0.0.0.0", int(os.environ.get("GATEWAY_PORT", "4399"))
DEDUP_WINDOW = 4.0     # 相同识别文本的去重窗口（秒）
SUPPRESS_NATIVE = True  # 网关接管指令时，重启小爱语音服务掐断原生抢答（不需要时改为 False）
SUPPRESS_SETTLE = 1.5   # 掐断后等待音频服务恢复的秒数（太短会导致紧随的 TTS 播不出来）

# ---------------- 听写模式 ----------------
DICTATION_TIMEOUT = 90      # 听写中连续这么久没说话自动结束（秒）
DICTATION_HARD_LIMIT = 600  # 单次听写最长时长（秒）
HOTKEY = "ctrl+alt+x"       # 电脑端切换听写的热键
MODEL_DIR = Path(os.environ.get(
    "SHERPA_MODEL_DIR",
    r"C:\Users\Administrator\.zcode\models\sherpa-onnx-streaming-zipformer-zh-14M-2023-02-23"))
SENSEVOICE_DIR = Path(os.environ.get(
    "SENSEVOICE_DIR",
    r"C:\Users\Administrator\.zcode\models\sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"))
VAD_PATH = Path(os.environ.get(
    "SILERO_VAD", r"C:\Users\Administrator\.zcode\models\silero_vad.onnx"))
WAKE_RE = re.compile(r"^(?:小爱同学|小爱小爱)[,，。]?\s*")
DICT_START_RE = re.compile(r"^(?:帮我|请)?(?:开始|进入|打开)(?:一下)?听写(?:模式)?(?:吧|呗|呀|啊)?$")
DICT_STOP_RE = re.compile(r"^(?:帮我|请)?(?:结束|停止|退出|关掉)(?:一下)?听写(?:模式)?(?:吧|呗|呀|啊)?$")
# 一次性输入：「(小爱同学，)输入/打字 XXX」直接打进当前焦点输入框
RE_TYPE = re.compile(
    r"^(?:小爱同学|喵喵|帮我|请|麻烦)*[,，。]?\s*(?:输入|打字)(?:一下)?"
    r"(?P<text>.+?)(?:吧|呗|呀|啊|哈|哦|啦)*[。，,！!？?~\s]*$")

log = logging.getLogger("gateway")

clients = set()           # 当前连接的音箱 client
recent_dispatched = []    # [(时间, 归一化文本)] 指令去重


# ---------------- 协议封装 ----------------
def wrap_request(command, payload):
    msg = {"id": uuid.uuid4().hex, "command": command, "payload": payload}
    return json.dumps({"Request": msg}, ensure_ascii=False)


def unwrap(text):
    """拆掉枚举包装 {"Event":{...}} -> ("Event", {...})；兼容裸结构。"""
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None, None
    if isinstance(obj, dict):
        for key in ("Event", "Request", "Response", "Stream"):
            if key in obj and isinstance(obj[key], dict):
                return key, obj[key]
        return "Raw", obj
    return None, None


async def speak(ws, text):
    """用音箱原生 TTS 说话：run_shell 调 tts_play.sh，payload 为裸字符串。"""
    script = "/usr/sbin/tts_play.sh '%s'" % text.replace("'", "")
    try:
        await ws.send(wrap_request("run_shell", script))
        log.info("🔊 确认语 -> 音箱: %s", text)
    except Exception as e:
        log.warning("确认语发送失败: %s (%s)", text, e)


# ---------------- instruction 事件解析 ----------------
def extract_final_texts(data):
    """提取 is_final=true 的识别文本。

    client 真实上报结构（已从 client-rust 源码确认）:
      data = {"NewLine": "<一行JSON字符串>"}   # FileMonitorEvent::NewLine
    该行JSON为: {header:{dialog_id,...}, payload:{is_final, results:[{text,...}]}}
    """
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            return []
    if not isinstance(data, dict):
        return []

    # 拆掉 FileMonitorEvent 的枚举包装，内层才是日志行 JSON
    inner = data.get("NewLine")
    if isinstance(inner, str):
        try:
            data = json.loads(inner)
        except json.JSONDecodeError:
            return []

    texts = []
    payload = data.get("payload") if isinstance(data, dict) else None
    if isinstance(payload, dict) and payload.get("is_final") is True:
        for r in payload.get("results") or []:
            if isinstance(r, dict) and isinstance(r.get("text"), str) and r["text"].strip():
                texts.append(r["text"].strip())

    if not texts:
        # 兜底：结构有出入时，宽松地找 is_final=true 且带 text 的节点
        def walk(o):
            if isinstance(o, dict):
                if o.get("is_final") is True and isinstance(o.get("text"), str) and o["text"].strip():
                    texts.append(o["text"].strip())
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(data)
    return texts


# ---------------- 应用表与指令匹配 ----------------
def load_apps():
    try:
        apps = json.loads(APPS_FILE.read_text(encoding="utf-8"))
        if isinstance(apps, dict):
            return apps
    except Exception as e:
        log.error("读取 apps.json 失败: %s", e)
    return {}


def find_app(apps, name):
    """应用名匹配：精确键 > 别名 > 正则模式（patterns 为正则表达式列表，
    对识别出的应用名做 fullmatch；匹配前去掉所有空格并忽略大小写，
    这样「v s code」「py charm」等 ASR 分词变体也能命中）。"""
    name = name.strip().lower()
    name_nospace = name.replace(" ", "")
    candidates = {name, name_nospace} - {""}
    for key, conf in apps.items():
        if key.startswith("_"):
            continue  # "_搜索" 等配置项不参与应用匹配
        if key.lower() in candidates:
            return key, conf
        if not isinstance(conf, dict):
            continue
        aliases = [str(a).strip().lower().replace(" ", "") for a in conf.get("aliases", [])]
        if name_nospace in aliases:
            return key, conf
        for pat in conf.get("patterns", []):
            try:
                if any(re.fullmatch(pat, c, re.IGNORECASE) for c in candidates):
                    return key, conf
            except re.error:
                log.warning("apps.json 中 %s 的正则无效: %s", key, pat)
    return None, None


RE_SEARCH = re.compile(
    r"^(?:小爱同学|喵喵|帮我|请|麻烦|用浏览器|浏览器|打开浏览器)*[,，。]?\s*"
    r"(?:搜索|搜一下|搜|查一下|查|百度一下)(?:一下)?"
    r"(?P<query>.+?)(?:吧|呗|呀|啊|哈|哦|啦)*[。，,！!？?~\s]*$")
RE_OPEN = re.compile(
    r"^(?:小爱同学|喵喵|帮我|请|麻烦|用浏览器|浏览器)*[,，。]?\s*(?:打开|启动|运行|开一下|开)(?:一下)?"
    r"(?P<app>[A-Za-z0-9\u4e00-\u9fa5·]+?)(?:吧|呗|呀|啊|哈|哦|啦|一下)*[。，,！!？?~\s]*$")
RE_CLOSE = re.compile(
    r"^(?:小爱同学|喵喵|帮我|请|麻烦)*[,，。]?\s*(?:关闭|退出|结束|关掉|关了|杀掉)(?:一下)?"
    r"(?P<app>[A-Za-z0-9\u4e00-\u9fa5·]+?)(?:吧|呗|呀|啊|哈|哦|啦|一下)*[。，,！!？?~\s]*$")


def match_command(text):
    """返回 (action, target)。
    action: search / open / close / None。搜索优先于打开（兼容「打开浏览器搜XX」）。"""
    text = text.strip()
    m = RE_SEARCH.fullmatch(text)
    if m and m.group("query").strip():
        return ("search", m.group("query").strip())
    m = RE_OPEN.fullmatch(text)
    if m:
        return ("open", m.group("app"))
    m = RE_CLOSE.fullmatch(text)
    if m:
        return ("close", m.group("app"))
    return None, None


# ---------------- 动作执行 ----------------
def is_process_running(process):
    r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq %s" % process],
                       capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    return process.lower() in r.stdout.decode("gbk", errors="ignore").lower()


def open_target(conf):
    """打开应用/网址/自定义命令；返回是否成功"""
    if conf.get("url"):
        webbrowser.open(conf["url"])
        return True
    if conf.get("cmd"):
        subprocess.Popen(conf["cmd"], shell=True)
        return True
    path = conf.get("path")
    if path and Path(path).exists():
        os.startfile(path)  # noqa: S606
        return True
    return False


def close_app(conf):
    proc = conf.get("process")
    if not proc:
        return False
    if not is_process_running(proc):
        return True  # 本来就没开，视为关闭成功（确认语会说"没在运行"）
    cf = subprocess.CREATE_NO_WINDOW
    # 先优雅关闭（发 WM_CLOSE）；QQ 这类应用会假死无视消息，必须复核后强杀
    subprocess.run(["taskkill", "/IM", proc], capture_output=True, creationflags=cf)
    if is_process_running(proc):
        subprocess.run(["taskkill", "/F", "/IM", proc], capture_output=True, creationflags=cf)
        time.sleep(0.5)
    return not is_process_running(proc)


# ---------------- 键盘注入（听写上屏） ----------------
_PUL = ctypes.POINTER(ctypes.c_ulong)


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", _PUL)]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", _PUL)]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


def foreground_window_title():
    """当前焦点窗口标题（打字去向诊断用）"""
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        buf = ctypes.create_unicode_buffer(256)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, 256)
        return buf.value.strip() or "未知窗口"
    except Exception:
        return "未知窗口"


def type_text_sendinput(text):
    """用 KEYEVENTF_UNICODE 把文字直接打进当前焦点输入框（绕过输入法，不动剪贴板）"""
    KEYEVENTF_UNICODE, KEYEVENTF_KEYUP, INPUT_KEYBOARD = 0x0004, 0x0002, 1
    codes = []
    for ch in text:
        b = ch.encode("utf-16-le")
        for i in range(0, len(b), 2):
            codes.append(b[i] | (b[i + 1] << 8))
    inputs = []
    for code in codes:
        for flags in (KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP):
            ki = _KEYBDINPUT(0, code, flags, 0, None)
            inputs.append(_INPUT(INPUT_KEYBOARD, _INPUTUNION(ki=ki)))
    if not inputs:
        return
    arr = (_INPUT * len(inputs))(*inputs)
    user32 = ctypes.windll.user32
    user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int]
    sent = user32.SendInput(len(inputs), arr, ctypes.sizeof(_INPUT))
    if sent != len(inputs):
        err = ctypes.GetLastError()
        log.error("SendInput 只送达 %d/%d（GetLastError=%d，cbSize=%d）",
                  sent, len(inputs), err, ctypes.sizeof(_INPUT))


# ---------------- 听写模式 ----------------
class Dictation:
    """录音流 -> sherpa-onnx 流式识别 -> endpoint 断句 -> SendInput 上屏"""

    def __init__(self):
        self.active = False
        self.engine = "xiaoai"        # xiaoai=小爱云端识别(每句带唤醒词) / local=本地模型(免唤醒词)
        self.recording_started = False
        self.asr_kind = "streaming"   # streaming=流式小模型 / sensevoice=VAD断句+整句识别(质量更好)
        self.ready = False
        self.rec = None               # 流式识别器
        self.stream = None
        self.off_rec = None           # SenseVoice 整句识别器
        self.vad = None               # silero VAD
        self.buf = bytearray()
        self.worker = None
        self.watchdog = None
        self.started_at = 0.0
        self.last_activity = 0.0
        self.lock = asyncio.Lock()

    def unload(self):
        """释放本地模型内存（约几百MB）；下次听写自动重载，仅多等1-2秒"""
        import gc
        self.ready = False
        self.rec = None
        self.stream = None
        self.off_rec = None
        self.vad = None
        self.asr_kind = "streaming"
        gc.collect()
        log.info("🧹 本地识别模型已卸载，内存已释放")

    def ensure(self):
        """惰性创建识别后端：优先 SenseVoice(质量好)，模型缺失则回落流式小模型"""
        if self.ready:
            return
        import sherpa_onnx
        if ((SENSEVOICE_DIR / "model.int8.onnx").exists()
                and (SENSEVOICE_DIR / "tokens.txt").exists() and VAD_PATH.exists()):
            self.off_rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                model=str(SENSEVOICE_DIR / "model.int8.onnx"),
                tokens=str(SENSEVOICE_DIR / "tokens.txt"),
                num_threads=2, use_itn=True)
            cfg = sherpa_onnx.VadModelConfig()
            cfg.silero_vad.model = str(VAD_PATH)
            cfg.silero_vad.threshold = 0.5
            cfg.silero_vad.min_speech_duration = 0.25
            cfg.silero_vad.min_silence_duration = 0.5
            cfg.sample_rate = 16000
            self.vad = sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=120)
            self.asr_kind = "sensevoice"
            log.info("📝 本地识别后端: SenseVoice + VAD")
        elif (MODEL_DIR / "tokens.txt").exists():
            self.rec = sherpa_onnx.OnlineRecognizer.from_transducer(
                tokens=str(MODEL_DIR / "tokens.txt"),
                encoder=str(MODEL_DIR / "encoder-epoch-99-avg-1.int8.onnx"),
                decoder=str(MODEL_DIR / "decoder-epoch-99-avg-1.int8.onnx"),
                joiner=str(MODEL_DIR / "joiner-epoch-99-avg-1.int8.onnx"),
                num_threads=2, sample_rate=16000, feature_dim=80,
                enable_endpoint_detection=True,
                rule1_min_trailing_silence=2.0,
                rule2_min_trailing_silence=1.0,
                rule3_min_utterance_length=20,
                decoding_method="greedy_search")
            self.stream = self.rec.create_stream()
            self.asr_kind = "streaming"
            log.info("📝 本地识别后端: 流式 zipformer (%s)", MODEL_DIR.name)
        else:
            raise RuntimeError("未找到任何本地模型目录")
        self.ready = True

    def _decode_segment(self, samples):
        """SenseVoice: 整句解码一段音频（VAD 给的是 float32，识别器要 int16）"""
        samples = np.asarray(samples, dtype=np.int16)
        stream = self.off_rec.create_stream()
        stream.accept_waveform(16000, samples)
        self.off_rec.decode_stream(stream)
        return stream.result.text.strip()

    def _feed(self, pcm):
        """喂入一段 PCM，返回本次产生的定稿文本列表"""
        samples = np.frombuffer(pcm, dtype=np.int16)
        if samples.size == 0:
            return []
        if self.asr_kind == "sensevoice":
            self.vad.accept_waveform(samples)  # int16 直喂（实测 float32 不会产出段落）
            texts = []
            while not self.vad.empty():
                seg = self.vad.front
                samples = np.asarray(seg.samples, dtype=np.int16).copy()  # pop 会令引用失效，先复制
                self.vad.pop()
                text = self._decode_segment(samples)
                if text:
                    texts.append(text)
            return texts
        # 流式小模型路径
        self.stream.accept_waveform(16000, samples)
        while self.rec.is_ready(self.stream):
            self.rec.decode_stream(self.stream)
        if self.rec.is_endpoint(self.stream):
            text = self.rec.get_result(self.stream).strip()
            self.rec.reset(self.stream)
            return [text] if text else []
        return []

    def _flush(self):
        try:
            if self.asr_kind == "sensevoice":
                texts = []
                while not self.vad.empty():
                    seg = self.vad.front
                    samples = np.asarray(seg.samples, dtype=np.int16).copy()
                    self.vad.pop()
                    text = self._decode_segment(samples)
                    if text:
                        texts.append(text)
                seg = self.vad.current_segment  # 收尾：进行中未定稿的段落（属性，非方法）
                if seg is not None and len(np.asarray(seg.samples)):
                    text = self._decode_segment(seg.samples)
                    if text:
                        texts.append(text)
                return "".join(texts).strip()
            self.stream.input_finished()
            while self.rec.is_ready(self.stream):
                self.rec.decode_stream(self.stream)
            return self.rec.get_result(self.stream).strip()
        except Exception as e:
            log.error("听写收尾失败: %s", e)
            return ""
        finally:
            if self.asr_kind == "streaming":
                self.stream = self.rec.create_stream()  # 下次听写用新流

    async def on_audio(self, frame):
        """处理 client 发来的二进制帧（裸 Stream JSON: {id,tag,bytes:[...]}）"""
        try:
            obj = json.loads(frame)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
        if not isinstance(obj, dict) or obj.get("tag") != "record":
            return
        try:
            self.buf.extend(bytes(bytearray(obj.get("bytes") or [])))
        except (TypeError, ValueError):
            return
        self.last_activity = time.monotonic()

    async def _worker(self, ws):
        loop = asyncio.get_running_loop()
        try:
            while self.active:
                if self.buf:
                    chunk = bytes(self.buf)
                    self.buf.clear()
                    texts = await loop.run_in_executor(None, self._feed, chunk)
                    for text in texts:
                        await loop.run_in_executor(None, type_text_sendinput, text)
                        log.info("⌨️ 已输入: %s", text)
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.error("听写线程异常: %s", e)

    async def _watchdog(self, ws):
        try:
            while True:
                await asyncio.sleep(2)
                now = time.monotonic()
                if now - self.started_at > DICTATION_HARD_LIMIT:
                    await stop_dictation(ws, "听写时间太长，自动结束")
                    return
                if now - self.last_activity > DICTATION_TIMEOUT:
                    await stop_dictation(ws, "一段时间没说话，嘟~")
                    return
        except asyncio.CancelledError:
            pass


dictation = Dictation()
current_ws = None  # 当前音箱连接，供热键线程使用


async def start_dictation(ws):
    async with dictation.lock:
        if dictation.active:
            await speak(ws, "已经在听写中了")
            return
        cfg = load_apps().get("_听写", {})
        if not cfg.get("enabled", False):
            await speak(ws, "听写功能未开启，需要在apps配置里打开")
            return
        engine = cfg.get("engine", "xiaoai")
        if engine == "local":
            try:
                await asyncio.to_thread(dictation.ensure)
            except Exception as e:
                log.warning("本地听写不可用(%s)，改用小爱云端识别", e)
                engine = "xiaoai"
        dictation.engine = engine
        dictation.recording_started = False
        dictation.active = True
        dictation.started_at = time.monotonic()
        dictation.last_activity = time.monotonic()
        dictation.watchdog = asyncio.create_task(dictation._watchdog(ws))

    if engine == "local":
        # 先播提示语、再开录音——顺序反了音箱自己的声音会被录进输入框
        await speak(ws, "")
        await asyncio.sleep(0.3)
        try:
            await ws.send(wrap_request("start_recording",
                {"pcm": "noop", "channels": 1, "bits_per_sample": 16,
                 "sample_rate": 16000, "period_size": 360, "buffer_size": 1440}))
            dictation.recording_started = True
            dictation.worker = asyncio.create_task(dictation._worker(ws))
        except Exception as e:
            log.error("start_recording 发送失败: %s", e)
            await stop_dictation(ws, "录音启动失败，嘟~")
            return
        log.info("📝 听写开始 (engine=local)")
    else:
        await speak(ws, "好的，开始听写，每句话开头说小爱同学")
        log.info("📝 听写开始 (engine=xiaoai)")


async def stop_dictation(ws, reason="嘟~"):
    async with dictation.lock:
        if not dictation.active:
            return
        dictation.active = False
        recording = dictation.recording_started
        dictation.recording_started = False
    for t in (dictation.worker, dictation.watchdog):
        if t:
            t.cancel()
    dictation.worker = dictation.watchdog = None
    if recording:
        try:
            await ws.send(wrap_request("stop_recording", None))
        except Exception:
            pass
        rest = await asyncio.to_thread(dictation._flush)
        if rest:
            await asyncio.to_thread(type_text_sendinput, rest)
            log.info("⌨️ 已输入(收尾): %s", rest)
        await asyncio.to_thread(dictation.unload)  # 常驻友好：每次听写结束即释放模型内存
    await speak(ws, reason)
    log.info("📝 %s", reason)


async def toggle_dictation():
    if dictation.active:
        await stop_dictation(current_ws)
    else:
        await start_dictation(current_ws)


def setup_hotkey(loop):
    """电脑端热键切换听写（可选；失败不影响语音控制）。听写开关关闭时不注册。"""
    if not load_apps().get("_听写", {}).get("enabled", False):
        log.info("⌨️ 听写功能已关闭（_听写.enabled=false），热键未注册")
        return
    try:
        import keyboard

        def _toggle():
            if current_ws is None:
                return
            asyncio.run_coroutine_threadsafe(toggle_dictation(), loop)

        keyboard.add_hotkey(HOTKEY, _toggle, suppress=False)
        log.info("⌨️ 听写热键已注册: %s", HOTKEY)
    except Exception as e:
        log.warning("热键注册失败: %s（语音「开始听写」不受影响）", e)


async def suppress_native(ws):
    """接管指令时重启小爱语音服务，掐断原生抢答。
    与官方 open-xiaoai speaker.rs 的 abort_xiaoai 同款命令，服务会自动拉起，
    instruction.log 监视器感知到文件变化后继续工作。"""
    try:
        await ws.send(wrap_request(
            "run_shell", "/etc/init.d/mico_aivs_lab restart >/dev/null 2>&1"))
        log.info("✂️ 已掐断原生抢答")
    except Exception as e:
        log.warning("掐断抢答失败: %s", e)


async def handle_instruction(ws, data):
    texts = extract_final_texts(data)
    if not texts:
        return
    log.info("🎤 识别: %s", texts)

    now = time.monotonic()
    global recent_dispatched
    recent_dispatched = [(t, s) for (t, s) in recent_dispatched if now - t < DEDUP_WINDOW]

    apps = load_apps()
    for text in texts:
        clean = WAKE_RE.sub("", text).strip()

        # ---- 听写模式中的语音分流 ----
        if dictation.active:
            dictation.last_activity = time.monotonic()
            if DICT_STOP_RE.fullmatch(clean) or DICT_STOP_RE.fullmatch(text.strip()):
                await stop_dictation(ws)
            elif DICT_START_RE.fullmatch(clean):
                await speak(ws, "已经在听写中了")
            else:
                # 小爱引擎：每句话带唤醒词，云端识别后直接打进输入框（本地引擎走录音流）
                if dictation.engine == "xiaoai" and clean:
                    m = RE_TYPE.fullmatch(clean)  # 听写中说「输入XXX」只打内容
                    content = m.group("text").strip() if m else clean
                    if content:
                        if SUPPRESS_NATIVE:
                            await suppress_native(ws)
                            await asyncio.sleep(SUPPRESS_SETTLE)
                        await asyncio.to_thread(type_text_sendinput, content)
                        log.info("⌨️ 已输入到「%s」: %s", foreground_window_title(), content)
                # 本地引擎：内容由录音流负责上屏，这里忽略（防止同一句输入两次）
            continue

        # ---- 一次性输入：「输入XXX」直接打进焦点输入框（无需进入听写模式） ----
        m = RE_TYPE.fullmatch(clean)
        if m and m.group("text").strip():
            typed = m.group("text").strip()
            if SUPPRESS_NATIVE:
                await suppress_native(ws)
                await asyncio.sleep(SUPPRESS_SETTLE)
            await asyncio.to_thread(type_text_sendinput, typed)
            log.info("⌨️ 已输入到「%s」: %s", foreground_window_title(), typed)
            continue  # 成功不播确认语，打出来的字就是反馈

        # ---- 听写开关指令 ----
        if DICT_START_RE.fullmatch(clean):
            if SUPPRESS_NATIVE:
                await suppress_native(ws)
                await asyncio.sleep(SUPPRESS_SETTLE)
            await start_dictation(ws)
            continue

        key = text.lower().replace(" ", "")
        if any(s == key for (_, s) in recent_dispatched):
            log.info("… 4秒内重复指令，忽略: %s", text)
            continue
        recent_dispatched.append((now, key))

        action, app_name = match_command(clean)
        if not action:
            continue  # 非遥控指令，留给原生小爱
        # 网关接管这条指令：掐断原生抢答，稍等再播确认语，避免两句话叠在一起
        if SUPPRESS_NATIVE:
            await suppress_native(ws)
            await asyncio.sleep(SUPPRESS_SETTLE)
        app_key, conf = find_app(apps, app_name)

        if action == "search":
            meta = apps.get("_搜索", {})
            tpl = meta.get("url", "https://www.baidu.com/s?wd={}")
            engine = meta.get("name", "百度")
            webbrowser.open(tpl.format(quote(app_name)))
            await speak(ws, "好的，已用%s搜索%s" % (engine, app_name))
        elif action == "open":
            if conf is None:
                await speak(ws, "这个%s我还不会打开，请在apps配置里添加" % app_name)
                continue
            ok = await asyncio.to_thread(open_target, conf)
            await speak(ws, ("好的，%s已打开" % app_key) if ok else ("打开%s失败了" % app_key))
        elif action == "close":
            if conf is None:
                await speak(ws, "这个%s我还不认识" % app_name)
                continue
            if conf.get("url") and not conf.get("process"):
                await speak(ws, "网页可关不了，要关浏览器就说关闭谷歌浏览器")
                continue
            was_running = is_process_running(conf.get("process") or "")
            ok = await asyncio.to_thread(close_app, conf)
            if ok and not was_running:
                await speak(ws, "%s本来就没在运行" % app_key)
            else:
                await speak(ws, ("好的，%s已关闭" % app_key) if ok else ("关闭%s失败了" % app_key))


# ---------------- WebSocket 服务 ----------------
async def handler(ws):
    global current_ws
    peer = ws.remote_address
    log.info("✅ 音箱已连接: %s", peer)
    clients.add(ws)
    current_ws = ws
    try:
        async for raw in ws:
            if isinstance(raw, bytes):
                if dictation.active:
                    await dictation.on_audio(raw)
                continue  # 二进制帧：只有听写模式用（录音流）
            kind, body = unwrap(raw)
            if kind == "Event" and body.get("event") == "instruction":
                log.info("📩 instruction: %s", json.dumps(body.get("data"), ensure_ascii=False)[:200])
                await handle_instruction(ws, body.get("data"))
            elif kind == "Event":
                log.debug("事件: %s", body.get("event"))
            elif kind == "Request":
                log.info("收到音箱请求: %s", body.get("command"))
                await ws.send(json.dumps({"Response": {
                    "id": body.get("id"), "code": -1, "msg": "not supported"}},
                    ensure_ascii=False))
            elif kind == "Response":
                log.debug("音箱响应: %s", json.dumps(body, ensure_ascii=False)[:200])
    except websockets.ConnectionClosed:
        pass
    finally:
        clients.discard(ws)
        log.info("❌ 音箱断开: %s", peer)


def local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("223.5.5.5", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


# ---------------- 音箱自动发现与指向自愈 ----------------
def ssh_speaker(ip, user, password, command, timeout=12):
    """Windows OpenSSH + SSH_ASKPASS 免交互执行音箱命令，返回 (是否成功, 输出)。
    注意：askpass 文件不能即用即删——ssh 认证过程中会多次调用它。"""
    askpass = _ensure_askpass(password)
    env = dict(os.environ, SSH_ASKPASS=askpass, SSH_ASKPASS_REQUIRE="force", DISPLAY=":0")
    try:
        r = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=NUL",
             "-o", "HostKeyAlgorithms=+ssh-rsa", "-o", "ConnectTimeout=8",
             "%s@%s" % (user, ip), command],
            env=env, capture_output=True, timeout=timeout, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW)
        return r.returncode == 0, r.stdout.strip()
    except Exception:
        return False, ""


def _ensure_askpass(password):
    """askpass 用固定路径持久保存，避免 ssh 认证中途找不到文件"""
    askpass = BASE_DIR / "xiaoai_askpass.bat"
    content = "@echo %s" % password
    try:
        if not askpass.exists() or askpass.read_text() != content:
            askpass.write_text(content)
    except OSError:
        askpass.write_text(content)
    return str(askpass)


def load_speaker_record():
    try:
        return json.loads(SPEAKER_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


_client_ssh = None  # 持有 client 的长连 SSH 会话（client 是其前台进程）


def speaker_connected():
    """本机 4399 上有没有来自局域网的 ESTABLISHED 连接（即音箱 client 已连上）"""
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True,
                             creationflags=subprocess.CREATE_NO_WINDOW,
                             timeout=10).stdout.decode("gbk", errors="ignore")
        for line in out.splitlines():
            if ":4399" in line and "ESTABLISHED" in line:
                return True
    except Exception:
        pass
    return False


def start_client_via_ssh(ip, user, password, server_addr):
    """通过常驻 SSH 会话重启音箱上的 client：
    会话内存活期间 client 存活；会话断开（网关退出/被杀）client 随之退出，
    下次 ensure_speaker 会重新拉起。旧会话/旧 client 先杀后启。"""
    global _client_ssh
    if _client_ssh is not None:
        try:
            _client_ssh.kill()
        except Exception:
            pass
        _client_ssh = None
    askpass = _ensure_askpass(password)
    env = dict(os.environ, SSH_ASKPASS=askpass, SSH_ASKPASS_REQUIRE="force", DISPLAY=":0")
    cmd = ("kill -9 $(pidof client) 2>/dev/null; "
           "sleep 0.3; /data/open-xiaoai/client %s" % server_addr)
    errfile = open(BASE_DIR / "client_ssh.log", "ab")
    try:
        _client_ssh = subprocess.Popen(
            ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=NUL",
             "-o", "HostKeyAlgorithms=+ssh-rsa", "-o", "ServerAliveInterval=30",
             "%s@%s" % (user, ip), cmd],
            env=env, stdout=errfile, stderr=errfile,
            stdin=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW)
        return True
    except Exception as e:
        log.error("SSH 拉起 client 失败: %s", e)
        return False
    finally:
        errfile.close()


def scan_speaker(user, password):
    """扫描本机 /24 网段：开 22 端口且 SSH banner 为 dropbear 的设备挨个验证，
    能读到 /data/open-xiaoai/server.txt 的就是小爱音箱。"""
    base = ".".join(local_ip().split(".")[:3])

    def probe(addr):
        try:
            s = socket.create_connection((addr, 22), timeout=0.6)
            banner = s.recv(64).decode(errors="ignore")
            s.close()
            if banner.startswith("SSH-2.0-dropbear"):
                return addr
        except OSError:
            pass
        return None

    candidates = []
    with ThreadPoolExecutor(max_workers=64) as ex:
        for r in ex.map(probe, ["%s.%d" % (base, i) for i in range(1, 255)]):
            if r:
                candidates.append(r)
    log.info("🔎 网段扫描完成，dropbear 设备: %s", candidates or "无")
    for addr in candidates:
        ok, out = ssh_speaker(addr, user, password,
                              "test -f /data/open-xiaoai/server.txt && echo IS_XIAOAI")
        if ok and "IS_XIAOAI" in out:
            return addr
    return None


async def ensure_speaker():
    """网关启动时的自愈：确认音箱可达且指向本机最新 IP，变了就 SSH 改写并重启其 client。"""
    meta = load_apps().get("_音箱", {})
    user = meta.get("user", "root")
    password = meta.get("password", "open-xiaoai")
    my_ip = local_ip()
    want = "ws://%s:4399" % my_ip

    rec = load_speaker_record()
    ip = rec.get("ip")
    log.info("🔎 检查音箱（记录IP: %s | 本机IP: %s）", ip or "无", my_ip)

    def is_speaker(addr):
        ok, out = ssh_speaker(addr, user, password,
                              "test -f /data/open-xiaoai/server.txt && echo IS_XIAOAI")
        return ok and "IS_XIAOAI" in out

    if not (ip and await asyncio.to_thread(is_speaker, ip)):
        ip = await asyncio.to_thread(scan_speaker, user, password)
        if not ip:
            log.warning("⚠️ 未找到小爱音箱（音箱没开/不同网段/密码不对），原生功能不受影响")
            return
        log.info("✅ 扫描发现小爱音箱: %s", ip)
    else:
        log.info("✅ 记录的音箱可达: %s", ip)

    ok, cur = await asyncio.to_thread(ssh_speaker, ip, user, password,
                                      "cat /data/open-xiaoai/server.txt")
    if ok and cur.strip() == want:
        log.info("✅ 音箱指向已是本机（%s），无需修改", want)
    else:
        log.info("🔧 音箱指向（%s）过期，改为 %s", cur.strip() or "读取失败", want)
        ok, _ = await asyncio.to_thread(
            ssh_speaker, ip, user, password,
            "echo '%s' > /data/open-xiaoai/server.txt" % want)
        if not ok:
            log.error("🔧 server.txt 写入失败")
            return

    # client 没连上来时通过长连 SSH 会话重启它（client 作为会话前台进程，
    # 由网关持有会话；音箱上没有 nohup/setsid，无法脱离会话后台运行）
    await asyncio.sleep(5)  # 给 client 一点重连时间，避免无谓重启
    if speaker_connected():
        log.info("✅ 音箱 client 已连接本机，无需重启")
    else:
        log.info("🔧 音箱 client 未连接，通过 SSH 会话重启…")
        ok = await asyncio.to_thread(start_client_via_ssh, ip, user, password, want)
        log.info("🔧 client 重启: %s", "成功" if ok else "失败")

    try:
        SPEAKER_FILE.write_text(json.dumps(
            {"ip": ip, "last_seen": time.strftime("%Y-%m-%d %H:%M:%S")},
            ensure_ascii=False), encoding="utf-8")
        log.info("💾 音箱信息已记录到 %s", SPEAKER_FILE.name)
    except Exception as e:
        log.warning("记录音箱信息失败: %s", e)


async def main():
    # pythonw 无窗口运行时 sys.stdout/stderr 为 None，做兼容（日志只写文件）
    handlers = [logging.FileHandler(LOG_FILE, encoding="utf-8")]
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None:
                stream.reconfigure(errors="replace")
        except Exception:
            pass
    if sys.stdout is not None:
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers)
    log.info("🚀 小爱语音遥控网关启动 ws://%s:%d", local_ip(), PORT)
    log.info("等待音箱连接…（音箱侧需指向 ws://%s:4399）", local_ip())
    setup_hotkey(asyncio.get_running_loop())
    asyncio.create_task(ensure_speaker())  # 后台自愈：发现音箱并校正指向
    async with websockets.serve(handler, HOST, PORT):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
