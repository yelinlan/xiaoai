#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""找音箱（纯只读排查工具）

在本网段里搜一遍，报告哪台设备像是刷了 open-xiaoai 的小爱音箱。
只做 ping / ARP 读取 / TCP 端口探测 / 小米 UDP 握手 / SSH 读取，
不修改任何网络配置，也不改音箱上的任何东西。

用法：
    python find_speaker.py           扫一遍并报告候选
    python find_speaker.py --ssh     扫完再用 apps.json 里的账号 SSH 验证，并打印音箱当前指向
"""
import logging
import socket
import sys
import time

import app

logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
log = logging.getLogger("find")

MIIO_HELLO = b"\x21\x31\x00\x20" + b"\xff" * 28


def miio_probe(base, timeout=2.5):
    """小米私有协议 UDP 54321 握手：先广播再逐个单播，然后收应答。
    有些小米设备不回 ICMP，但会答这个包。"""
    found = {}
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(0.2)
        s.bind(("", 0))
        targets = [("%s.255" % base, 54321)] + \
                  [("%s.%d" % (base, i), 54321) for i in range(1, 255)]
        for t in targets:
            try:
                s.sendto(MIIO_HELLO, t)
            except OSError:
                pass
        s.settimeout(timeout)
        end = time.time() + timeout
        while time.time() < end:
            try:
                data, addr = s.recvfrom(1024)
            except socket.timeout:
                break
            except OSError:
                break
            found[addr[0]] = data[:16].hex()
    finally:
        s.close()
    return found


def main():
    want_ssh = "--ssh" in sys.argv[1:]
    my_ip = app.wait_for_lan_ip(timeout=10)
    print("=" * 68)
    if not my_ip:
        print("❌ 本机拿不到有效的局域网 IP：网卡没连上，或没获取到 DHCP 地址。")
        print("   先看 Wi-Fi 有没有连上，再重跑本工具。")
        return 2
    base = ".".join(my_ip.split(".")[:3])
    print("本机 IP : %s      扫描网段: %s.0/24" % (my_ip, base))
    print("网关端口: %d        音箱应指向 ws://%s:%d" % (app.PORT, my_ip, app.PORT))
    print("=" * 68)

    print("\n[1/3] ping 预热 + 读 ARP 表（只读）…")
    neighbors = app.arp_neighbors(base)
    if not neighbors:
        print("      ARP 表里一个邻居都没有 —— 本机可能压根没接到局域网。")
    for ip, mac in sorted(neighbors, key=lambda x: int(x[0].rsplit(".", 1)[1])):
        print("      %-16s %s" % (ip, mac))

    print("\n[2/3] 探测 22 端口，认 dropbear banner（open-xiaoai 用的就是它）…")
    known = {ip: mac for ip, mac in neighbors}
    cand = app.dropbear_hosts(list(known))
    rest = ["%s.%d" % (base, i) for i in range(1, 255) if "%s.%d" % (base, i) not in known]
    for addr in app.dropbear_hosts(rest):
        if addr not in cand:
            cand.append(addr)
    if cand:
        for addr in cand:
            print("      ✅ %s  %s" % (addr, known.get(addr, app.mac_of(addr) or "MAC 未知")))
    else:
        print("      ❌ 全网段没有任何主机开放 22 端口")

    print("\n[3/3] 小米 UDP 54321 握手（找不回 ICMP 的小米设备）…")
    miio = miio_probe(base)
    if miio:
        for ip, hx in sorted(miio.items()):
            print("      ✅ %s  应答 %s…" % (ip, hx))
    else:
        print("      ❌ 无任何应答 —— 本网段没有在线的小米协议设备")

    print("\n" + "=" * 68)
    if cand:
        meta = app.load_apps().get("_音箱", {})
        user = meta.get("user", "root")
        password = meta.get("password", "open-xiaoai")
        for addr in cand:
            if not want_ssh:
                print("候选音箱: %s（加 --ssh 参数可进一步验证身份并查看当前指向）" % addr)
                continue
            ok, out = app.ssh_speaker(
                addr, user, password,
                "test -f /data/open-xiaoai/server.txt && echo IS_XIAOAI")
            if ok and "IS_XIAOAI" in out:
                ok2, cur = app.ssh_speaker(addr, user, password,
                                           "cat /data/open-xiaoai/server.txt")
                want = "ws://%s:%d" % (my_ip, app.PORT)
                print("🎯 %s 就是小爱音箱" % addr)
                print("   当前指向: %s" % (cur.strip() if ok2 else "读取失败"))
                print("   应该指向: %s   %s" % (want, "✅ 一致" if ok2 and cur.strip() == want else "❌ 不一致"))
                print("   → 直接启动网关（双击 start.bat）就会自动改写并重启音箱 client。")
            elif ok:
                print("候选 %s：SSH 能登但没有 /data/open-xiaoai/server.txt，不是小爱音箱" % addr)
            else:
                print("候选 %s：SSH 登录失败（密码不对？账号见 apps.json 的 _音箱）" % addr)
    else:
        print("结论：本网段找不到小爱音箱。请按顺序检查：")
        print("  1) 音箱通电了吗？指示灯是什么颜色（橙色闪烁＝没连上 WiFi）")
        print("  2) 音箱连的 Wi-Fi 是不是 %s（本机所在的这个）" % _ssid())
        print("  3) 路由器有没有被重置/换过：本机 IP 变了说明 DHCP 重新分配过")
        print("  4) 音箱是不是被重新刷过机（MAC 变了就得重新配网）")
        print("  5) 确认后再跑一次：python find_speaker.py --ssh")
    print("=" * 68)
    return 0 if cand else 1


def _ssid():
    import subprocess
    try:
        out = subprocess.run(["netsh", "wlan", "show", "interfaces"], capture_output=True,
                             creationflags=subprocess.CREATE_NO_WINDOW,
                             timeout=10).stdout.decode("gbk", errors="ignore")
        for line in out.splitlines():
            if "SSID" in line and ":" in line and "BSSID" not in line:
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return "未知"


if __name__ == "__main__":
    sys.exit(main())
