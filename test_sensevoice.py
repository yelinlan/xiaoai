# -*- coding: utf-8 -*-
"""SenseVoice + VAD 管线测试：SAPI 合成语音 -> 网关同款识别 -> 打印结果"""
import os
import subprocess
import sys
import wave

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# 1. SAPI 合成 16k 测试语音（两句，中间自然停顿，验证 VAD 断句）
ps = r'''
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.SelectVoice(($s.GetInstalledVoices() | Where-Object {$_.VoiceInfo.Culture.Name -like 'zh*'} | Select-Object -First 1).VoiceInfo.Name)
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$s.SetOutputToWaveFile('C:\Users\Administrator\IdeaProjects\xiaoai\_t2.wav', $fmt)
$s.Speak('今天天气真好我们出去玩吧')
$s.Speak('明天记得带上雨伞')
$s.Dispose()
Write-Output SYNTH_OK
'''
r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True)
print("合成:", r.stdout.decode("gbk", errors="ignore").strip() or r.stderr.decode("gbk", errors="ignore")[:200])

# 2. 走网关同款管线
import importlib.util
spec = importlib.util.spec_from_file_location("app", "app.py")
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)
d = app.dictation
d.ensure()
print("识别后端:", d.asr_kind, "| VAD window_size:", d.vad.config.silero_vad.window_size)

with wave.open("_t2.wav") as w:
    pcm = w.readframes(w.getnframes())
print("测试音频: %.1fs" % (len(pcm) / 32000))

import time
texts = []
t0 = time.monotonic()
for i in range(0, len(pcm), 3200):
    texts.extend(d._feed(pcm[i:i + 3200]))
rest = d._flush()
print("VAD分段定稿:", texts)
print("收尾:", repr(rest))
print("总耗时: %.2fs" % (time.monotonic() - t0))
os.remove("_t2.wav")
