#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""应用 brunodev85/wine-10.10-custom 的通用优化补丁。用法: apply.py <wine源码目录>"""
import io, json, os, subprocess, sys

src = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
here = os.path.dirname(os.path.abspath(__file__))
data = json.load(io.open(os.path.join(here, 'patches.json'), encoding='utf-8'))
patches = data['patches']

ok, skipped, failed = [], [], []
for p in patches:
    sha, subj = p['sha'], p['subject']
    tmp = '/tmp/_bd_%s.patch' % sha
    io.open(tmp, 'w', encoding='utf-8', errors='surrogateescape').write(p['patch'])

    def run(args):
        return subprocess.run(args, cwd=src, capture_output=True)

    r = run(['git', 'apply', '--check', '-p1', '--3way', '--whitespace=nowarn', tmp])
    if r.returncode == 0:
        run(['git', 'apply', '-p1', '--3way', '--whitespace=nowarn', tmp])
        ok.append(sha); print('  [ok]   %s %s' % (sha, subj), flush=True)
        continue
    r2 = run(['patch', '-p1', '--dry-run', '--forward', '--batch', '-i', tmp])
    if r2.returncode == 0:
        run(['patch', '-p1', '--forward', '--batch', '-i', tmp])
        ok.append(sha); print('  [ok]   %s %s (patch -p1)' % (sha, subj), flush=True)
        continue
    blob = ((r.stderr or b'').decode('utf-8','replace') + (r2.stdout or b'').decode('utf-8','replace')).lower()
    if 'does not exist' in blob or 'no such file' in blob or "can't find file" in blob:
        skipped.append(sha); print('  [skip] %s 目标文件不存在（版本差异）: %s' % (sha, subj), flush=True)
    else:
        failed.append(sha); print('  [fail] %s %s' % (sha, subj), flush=True)

print('', flush=True)
print('brunodev 通用补丁: 成功 %d / 跳过 %d / 失败 %d（共 %d）' % (len(ok), len(skipped), len(failed), len(patches)), flush=True)
print('  成功: %s' % ' '.join(ok))
if skipped: print('  跳过: %s' % ' '.join(skipped))
if failed:  print('  失败: %s' % ' '.join(failed))
with io.open('/tmp/brunodev-patch-report.txt', 'w', encoding='utf-8') as fh:
    fh.write('applied=%d skipped=%d failed=%d\n' % (len(ok), len(skipped), len(failed)))
    fh.write('ok: %s\nskip: %s\nfail: %s\n' % (' '.join(ok), ' '.join(skipped), ' '.join(failed)))
sys.exit(0)
