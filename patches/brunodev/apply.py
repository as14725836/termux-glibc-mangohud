#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""应用 brunodev85/wine-10.10-custom 的通用优化补丁。用法: apply.py <wine源码目录>
严格 git apply 优先；否则 git apply --3way（其退出码不可靠）。
每次应用后都扫描补丁涉及的每个文件是否出现冲突标记，有则回滚该文件。
"""
import io, json, os, re, subprocess, sys

src = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
here = os.path.dirname(os.path.abspath(__file__))
data = json.load(io.open(os.path.join(here, 'patches.json'), encoding='utf-8'))
patches = data['patches']
MARK = re.compile(r'^(<{7}|={7}|>{7})', re.M)


def run(a):
    return subprocess.run(a, cwd=src, capture_output=True)


def files_of(txt):
    out = []
    for m in re.finditer(r'^diff --git a/(\S+) b/(\S+)$', txt, re.M):
        for p in (m.group(1), m.group(2)):
            if p != '/dev/null' and p not in out:
                out.append(p)
    return out


def has_markers(paths):
    bad = []
    for p in paths:
        fp = os.path.join(src, p)
        if not os.path.isfile(fp):
            continue
        try:
            t = io.open(fp, encoding='utf-8', errors='replace').read()
        except Exception:
            continue
        if '<<<<<<<' in t and '>>>>>>>' in t:
            bad.append(p)
    return bad


def restore(paths):
    for p in paths:
        run(['git', 'checkout', '--', p])
        run(['git', 'clean', '-f', '--', p])


ok, skipped, failed, reverted = [], [], [], []
for p in patches:
    sha, subj, txt = p['sha'], p['subject'], p['patch']
    files = files_of(txt)
    tmp = '/tmp/_bd_%s.patch' % sha
    io.open(tmp, 'w', encoding='utf-8', errors='surrogateescape').write(txt)

    strict = run(['git', 'apply', '--check', '-p1', tmp]).returncode == 0
    if strict:
        if run(['git', 'apply', '-p1', tmp]).returncode == 0 and not has_markers(files):
            ok.append(sha); print('  [ok]   %s %s' % (sha, subj), flush=True); continue
        else:
            restore(files)
    else:
        if run(['git', 'apply', '--check', '-p1', '--3way', tmp]).returncode == 0:
            run(['git', 'apply', '-p1', '--3way', tmp])
            m = has_markers(files)
            if not m:
                ok.append(sha); print('  [ok]   %s %s (3way)' % (sha, subj), flush=True); continue
            restore(files)
            reverted.extend(m)

    skipped.append(sha)
    print('  [skip] %s %s%s' % (sha, subj, '（版本差异，已回滚冲突）' if not strict else ''), flush=True)

# 全部完成后全局再扫一遗（包含 termux 补丁没跑之前的源码）
left = []
for root, _d, fs in os.walk(src):
    if '/.git' in root:
        continue
    for f in fs:
        if f.endswith(('.c', '.h', '.in', '.ac', '.spec')):
            fp = os.path.join(root, f)
            try:
                t = io.open(fp, encoding='utf-8', errors='replace').read()
            except Exception:
                continue
            if '<<<<<<<' in t and '>>>>>>>' in t and '<<<<<<< HEAD' not in t[:0]:
                rel = os.path.relpath(fp, src)
                if not re.search(r'^(README|WINELIB_README)', rel) and 'autogen' not in rel:
                    left.append(rel)
if left:
    restore(left)

print('', flush=True)
print('brunodev 通用补丁: 成功 %d / 跳过 %d / 冲突回滚文件 %d（共 %d）'
      % (len(ok), len(skipped), len(set(left)), len(patches)), flush=True)
print('  成功: %s' % ' '.join(ok), flush=True)
if skipped: print('  跳过: %s' % ' '.join(skipped), flush=True)
sys.exit(0)
