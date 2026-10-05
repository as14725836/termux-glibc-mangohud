#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""应用 brunodev85/wine-10.10-custom 的通用优化补丁。用法: apply.py <wine源码目录>
逐补丁: 先严格 git apply --check；再 git apply --check --3way；最后 patch --dry-run。
真正应用后都会校验返回码，非 0 则回滚该补丁涉及的文件——绝不留下冲突标记。
"""
import io, json, os, re, subprocess, sys

src = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
here = os.path.dirname(os.path.abspath(__file__))
data = json.load(io.open(os.path.join(here, 'patches.json'), encoding='utf-8'))
patches = data['patches']


def run(args):
    return subprocess.run(args, cwd=src, capture_output=True)


def patch_files(txt):
    out = []
    for m in re.finditer(r'^diff --git a/(\S+) b/(\S+)$', txt, re.M):
        for p in (m.group(1), m.group(2)):
            if p != '/dev/null' and p not in out:
                out.append(p)
    return out


def revert(files):
    for f in files:
        run(['git', 'checkout', '--', f])
        run(['git', 'clean', '-f', '--', f])


ok, skipped, failed = [], [], []
for p in patches:
    sha, subj = p['sha'], p['subject']
    txt = p['patch']
    files = patch_files(txt)
    tmp = '/tmp/_bd_%s.patch' % sha
    io.open(tmp, 'w', encoding='utf-8', errors='surrogateescape').write(txt)

    # 1) 严格应用
    if run(['git', 'apply', '--check', '-p1', tmp]).returncode == 0:
        r = run(['git', 'apply', '-p1', tmp])
        if r.returncode == 0:
            ok.append(sha); print('  [ok]   %s %s' % (sha, subj), flush=True); continue
        revert(files)

    # 2) 三方合并（需要仓库里有对应 blob）
    if run(['git', 'apply', '--check', '-p1', '--3way', tmp]).returncode == 0:
        r = run(['git', 'apply', '-p1', '--3way', tmp])
        if r.returncode == 0:
            ok.append(sha); print('  [ok]   %s %s (3way)' % (sha, subj), flush=True); continue
        revert(files)

    # 3) 老式 patch（先 dry-run）
    d = run(['patch', '-p1', '--dry-run', '--forward', '--batch', '-i', tmp])
    if d.returncode == 0:
        r = run(['patch', '-p1', '--forward', '--batch', '-i', tmp])
        if r.returncode == 0:
            ok.append(sha); print('  [ok]   %s %s (patch -p1)' % (sha, subj), flush=True); continue
        revert(files)

    blob = ((d.stdout or b'').decode('utf-8', 'replace') + (d.stderr or b'').decode('utf-8', 'replace')).lower()
    if 'no such file' in blob or "can't find file" in blob or 'does not exist' in blob:
        skipped.append(sha); print('  [skip] %s 目标文件不存在: %s' % (sha, subj), flush=True)
    else:
        failed.append(sha); print('  [fail] %s %s' % (sha, subj), flush=True)

print('', flush=True)
print('brunodev 通用补丁: 成功 %d / 跳过 %d / 失败 %d（共 %d）' % (len(ok), len(skipped), len(failed), len(patches)), flush=True)
print('  成功: %s' % ' '.join(ok))
if skipped: print('  跳过: %s' % ' '.join(skipped))
if failed:  print('  失败: %s' % ' '.join(failed))
with io.open('/tmp/brunodev-patch-report.txt', 'w', encoding='utf-8') as fh:
    fh.write('applied=%d skipped=%d failed=%d\n' % (len(ok), len(skipped), len(failed)))
sys.exit(0)
