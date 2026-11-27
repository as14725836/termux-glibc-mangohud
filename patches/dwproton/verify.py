#!/usr/bin/env python3
"""Check retained DWProton edits after all CI injectors; never compile or run Wine."""
import argparse
import hashlib
import os
from pathlib import Path
import runpy
import sys

HERE = Path(__file__).resolve().parent


def ci_paths(text):
    """Mirror the workflow's existing global Termux /tmp substitutions."""
    return text.replace('/tmp/', '/data/data/com.termux/files/usr/tmp/').replace(
        '"/tmp"', '"/data/data/com.termux/files/usr/tmp"')


def additions(patch):
    result = {}
    target = None
    for line in patch.read_text().splitlines():
        if line.startswith('+++ b/'):
            target = line[6:]
            result[target] = []
        elif line.startswith('+') and not line.startswith('+++'):
            if target is None:
                raise ValueError('Patch addition without a target: ' + str(patch))
            result[target].append(line[1:])
    return result


def verify(source, fsync_status):
    patches = ['03-tgmux-shm-path.patch', '05-tgmux-integration.patch']
    if fsync_status in ('applied', 'already-applied'):
        patches.append('02-fsync.patch')
    elif fsync_status not in ('skipped-missing', 'skipped-incompatible'):
        raise ValueError('Unexpected fsync status: ' + fsync_status)
    targets = set()
    for patch in patches:
        for name, added in additions(HERE / patch).items():
            targets.add(name)
            actual = (source / name).read_text()
            if patch == '03-tgmux-shm-path.patch':
                # New shared headers must retain their entire policy, including
                # fallbacks; accept pristine helper output or CI path rewriting.
                expected = '\n'.join(added) + '\n'
                if actual not in (expected, ci_paths(expected)):
                    raise ValueError('Shared header changed or incomplete: ' + name)
            else:
                # Extra injectors may insert code or change indentation. Every
                # substantive added line must still occur in source order.
                lines = iter(line.strip() for line in actual.splitlines())
                for line in added:
                    if not line.strip():
                        continue
                    accepted = {line.strip(), ci_paths(line).strip()}
                    if not any(candidate in accepted for candidate in lines):
                        raise ValueError(f'{patch}: missing retained edit in {name}: {line.strip()}')
    loader = (source / 'dlls/ntdll/unix/loader.c').read_text()
    guard = runpy.run_path(str(HERE.parent / 'wow64/inject_preloader_wow64_guard.py'))
    if guard['HELPER'] not in loader or guard['SINGLE_EXEC_GUARDED'] not in loader:
        raise ValueError('Complete one-argument WoW64 foreign-host guard is required')
    if '#include <sys/utsname.h>' not in loader:
        raise ValueError('WoW64 host guard requires sys/utsname.h')
    if 'static void preloader_exec( char **argv, WORD machine )' in loader:
        raise ValueError('Generic loader change was reverted')
    for name in ('server/inproc_sync.c', 'server/ntsync_tmp.h', 'server/protocol.def',
                 'include/wine/server_protocol.h', 'dlls/ntdll/unix/sync.c'):
        path = source / name
        if path.is_file():
            if 'NTSYNC_DISABLED_FOR_TERMUX' in path.read_text():
                raise ValueError('Native synchronization was disabled in ' + name)
            targets.add(name)
    return ''.join(f'{hashlib.sha256((source / name).read_bytes()).hexdigest()}  {name}\n'
                   for name in sorted(targets))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--fsync-status', required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args()
    try:
        manifest = verify(args.source.resolve(), args.fsync_status)
        digest = hashlib.sha256(manifest.encode()).hexdigest()
        args.manifest.write_text(manifest)
        if os.environ.get('GITHUB_ENV'):
            with open(os.environ['GITHUB_ENV'], 'a') as stream:
                stream.write('DWPROTON_FINAL_SOURCE_STATUS=verified\n')
                stream.write('DWPROTON_FINAL_SOURCE_SHA256=' + digest + '\n')
        print('DWProton final source verified; target manifest SHA256: ' + digest)
    except (OSError, ValueError) as exc:
        print('ERROR: ' + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
