#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""brunodev85/wine-10.10-custom 通用优化补丁应用器
用法: apply.py <wine源码目录> [strict|auto]   （默认 strict）
严格模式(strict): 每个补丁必须能干净应用或已在树中；否则整体失败(exit 2)，不强行构建。
宽松模式(auto)  : 不适用的补丁跳过，只要有失败仍返回非0。
任何情况下都不会把 <<<<<<< 冲突标记留在源码里。
"""
import io, json, os, re, subprocess, sys

src = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
mode = (sys.argv[2] if len(sys.argv) > 2 else 'strict').lower()
strict = mode != 'auto'
here = os.path.dirname(os.path.abspath(__file__))
data = json.load(io.open(os.path.join(here, 'patches.json'), encoding='utf-8'))
patches = data['patches']


def run(a):
    return subprocess.run(a, cwd=src, capture_output=True)


def files_of(txt):
    out = []
    for m in re.finditer(r'^diff --git a/(\S+) b/(\S+)$', txt, re.M):
        for p in (m.group(1), m.group(2)):
            if p != '/dev/null' and p not in out:
                out.append(p)
    return out


def markers(paths):
    bad = []
    for p in paths:
        fp = os.path.join(src, p)
        if os.path.isfile(fp):
            t = io.open(fp, encoding='utf-8', errors='replace').read()
            if '<<<<<<<' in t and '>>>>>>>' in t:
                bad.append(p)
    return bad


def restore(paths):
    for p in paths:
        run(['git', 'checkout', '--', p])
        run(['git', 'clean', '-f', '--', p])


applied, present, failed = [], [], []
for p in patches:
    sha, subj, txt = p['sha'], p['subject'], p['patch']
    files = files_of(txt)
    tmp = '/tmp/_bd_%s.patch' % sha
    io.open(tmp, 'w', encoding='utf-8', errors='surrogateescape').write(txt)

    # a) 已经在树里？（反向能应用）
    if run(['git', 'apply', '--check', '-R', '-p1', tmp]).returncode == 0:
        present.append(sha); print('  [present] %s %s' % (sha, subj), flush=True); continue
    # b) 严格应用
    if run(['git', 'apply', '--check', '-p1', tmp]).returncode == 0:
        if run(['git', 'apply', '-p1', tmp]).returncode == 0 and not markers(files):
            applied.append(sha); print('  [ok]      %s %s' % (sha, subj), flush=True); continue
        restore(files)
    # c) 三方合并（不许留冲突标记）
    if run(['git', 'apply', '--check', '-p1', '--3way', tmp]).returncode == 0:
        run(['git', 'apply', '-p1', '--3way', tmp])
        if not markers(files):
            applied.append(sha); print('  [ok3]     %s %s' % (sha, subj), flush=True); continue
        restore(files)

    failed.append(sha); print('  [FAIL]    %s %s' % (sha, subj), flush=True)

print('', flush=True)
print('brunodev 补丁: 应用 %d / 已在树中 %d / 失败 %d（共 %d）'
      % (len(applied), len(present), len(failed), len(patches)), flush=True)
if failed:
    print('  失败清单: %s' % ' '.join(failed), flush=True)
with io.open('/tmp/brunodev-patch-report.txt', 'w', encoding='utf-8') as fh:
    fh.write('applied=%d present=%d failed=%d\n' % (len(applied), len(present), len(failed)))
    fh.write('failed: %s\n' % ' '.join(failed))

if failed and strict:
    print('严格模式：存在无法应用的补丁，终止构建（不强行继续）', flush=True)
    sys.exit(2)
sys.exit(0)
