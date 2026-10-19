#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""反检测补丁总入口（供 run 脚本过长的 workflow 步骤使用）

GitHub Actions 对单个 step 的 run 脚本有 21000 字符上限
（"Exceeded max expression length 21000"）。termux-glibc-wine.yml 的
"构建 Proton WOW64" 步骤本来就接近上限，因此把两侧注入逻辑收进本脚本，
workflow 里只留一行调用。

用法:
    apply_stealth.py <wine源码目录>

环境变量（模拟 workflow inputs）:
    A / ANTI_DETECT      'true'/'false'，默认 true  —— 跑 inject_anti_detect.py
    R / REGISTRY_STEALTH 'true'/'false'，默认 false —— 跑 inject_registry_stealth.py

两个子脚本本身幂等：已注入会自行输出 OK(already) 并退出 0。
任何失败只打印 WARN，本脚本始终返回 0，不阻断构建。
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable or 'python3'


def flag(*names, default='false'):
    for n in names:
        v = os.environ.get(n)
        if v is not None and v != '':
            return v.strip().lower() == 'true'
    return default == 'true'


def run(script, src):
    path = os.path.join(HERE, script)
    if not os.path.isfile(path):
        print('WARN: %s 不存在，跳过' % script)
        return
    try:
        p = subprocess.Popen([PY, path, src], stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT)
        out = p.communicate()[0]
        txt = out.decode('utf-8', 'replace').strip()
        if txt:
            print(txt)
        if p.returncode != 0:
            print('WARN: %s 退出码 %d（不阻断构建）' % (script, p.returncode))
    except Exception as exc:  # noqa: BLE001
        print('WARN: %s 执行异常 %s（不阻断构建）' % (script, exc))


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    if not os.path.isdir(src):
        print('WARN: 源码目录不存在: %s' % src)
        return 0
    # 缺头文件信息（便于日志中确认注入环境）
    print('--- stealth patches on %s ---' % os.path.abspath(src))
    if flag('A', 'ANTI_DETECT', 'ENABLE_ANTI_DETECT', default='true'):
        run('inject_anti_detect.py', src)
    else:
        print('skip anti-detect (A=false)')
    if flag('R', 'REGISTRY_STEALTH', 'ENABLE_REGISTRY_STEALTH', default='false'):
        run('inject_registry_stealth.py', src)
    else:
        print('skip registry-stealth (R=false)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
