#!/usr/bin/env python3
"""
Wine GStreamer GL 支持禁用补丁
用于禁用 unixlib.c 和 wg_parser.c 中的 OpenGL 支持
自动在 Wine 源码树中查找 dlls/winegstreamer/ 目录
"""
import os
import sys
import shutil

def find_winegstreamer_dir():
    """在 Wine 源码树中查找 dlls/winegstreamer/ 目录"""
    # 从当前目录开始向上查找
    current_dir = os.path.abspath('.')
    
    # 最多向上查找 10 层
    for _ in range(10):
        # 检查当前目录是否是 winegstreamer
        if os.path.basename(current_dir) == 'winegstreamer' and os.path.isdir(current_dir):
            return current_dir
        
        # 检查当前目录下是否有 dlls/winegstreamer
        dlls_path = os.path.join(current_dir, 'dlls', 'winegstreamer')
        if os.path.isdir(dlls_path):
            return dlls_path
        
        # 检查当前目录下是否有 winegstreamer
        winegstreamer_path = os.path.join(current_dir, 'winegstreamer')
        if os.path.isdir(winegstreamer_path):
            return winegstreamer_path
        
        # 向上移动一层
        parent_dir = os.path.dirname(current_dir)
        if parent_dir == current_dir:  # 到达根目录
            break
        current_dir = parent_dir
    
    return None

def find_file_in_winegstreamer(filename):
    """在 winegstreamer 目录中查找文件"""
    winegstreamer_dir = find_winegstreamer_dir()
    if not winegstreamer_dir:
        print(f"错误: 找不到 dlls/winegstreamer/ 目录")
        return None
    
    file_path = os.path.join(winegstreamer_dir, filename)
    if os.path.exists(file_path):
        return file_path
    
    # 也尝试在当前目录查找
    if os.path.exists(filename):
        return os.path.abspath(filename)
    
    return None

def disable_gl_unixlib(file_path):
    """禁用 unixlib.c 中的 GL 支持"""
    if not os.path.exists(file_path):
        print(f"跳过 {file_path}: 文件不存在")
        return False
    
    backup_path = file_path + '.bak'
    if not os.path.exists(backup_path):
        shutil.copy2(file_path, backup_path)
        print(f"  已备份: {backup_path}")
    
    with open(file_path, 'r') as f:
        content = f.read()
    
    content = content.replace('#include <gst/gl/gl.h>', '/* #include <gst/gl/gl.h> */')
    content = content.replace('GstGLDisplay *gl_display;', '/* GstGLDisplay *gl_display; */')
    content = content.replace('int wine_gst_no_gl = -1;', '/* int wine_gst_no_gl = -1; */')
    content = content.replace('    static GstGLContext *gl_context;', '    /* static GstGLContext *gl_context; */')
    
    lines = content.split('\n')
    new_lines = []
    found_gl_init = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if 'if (wine_gst_no_gl == -1)' in line and not found_gl_init:
            new_lines.append('#if 0 /* Disable GL support */')
            found_gl_init = True
        if found_gl_init and line.strip() == '}' and i > 0 and lines[i-1].strip().startswith('return'):
            new_lines.append(line)
            new_lines.append('#endif /* Disable GL support */')
            found_gl_init = False
            i += 1
            continue
        new_lines.append(line)
        i += 1
    content = '\n'.join(new_lines)
    
    with open(file_path, 'w') as f:
        f.write(content)
    print(f"✓ {file_path} GL 支持已禁用")
    return True

def disable_gl_wg_parser(file_path):
    """禁用 wg_parser.c 中的 GL 支持"""
    if not os.path.exists(file_path):
        print(f"跳过 {file_path}: 文件不存在")
        return False
    
    backup_path = file_path + '.bak'
    if not os.path.exists(backup_path):
        shutil.copy2(file_path, backup_path)
        print(f"  已备份: {backup_path}")
    
    with open(file_path, 'r') as f:
        content = f.read()
    
    content = content.replace('#include <gst/gl/gl.h>', '/* #include <gst/gl/gl.h> */')
    content = content.replace('extern GstGLDisplay *gl_display;', '/* extern GstGLDisplay *gl_display; */')
    content = content.replace('bool use_opengl;', '/* bool use_opengl; */')
    
    content = content.replace(
        'if ((parser->use_opengl = params->use_opengl && gl_display))',
        'parser->use_opengl = FALSE; /* GL disabled */\n    if (0) /* was: gl_display check */'
    )
    
    with open(file_path, 'w') as f:
        f.write(content)
    print(f"✓ {file_path} GL 支持已禁用")
    return True

def main():
    print("=" * 50)
    print("Wine GStreamer GL 支持禁用补丁")
    print("=" * 50)
    print()
    
    # 自动查找 winegstreamer 目录
    winegstreamer_dir = find_winegstreamer_dir()
    if winegstreamer_dir:
        print(f"找到 winegstreamer 目录: {winegstreamer_dir}")
    else:
        print("警告: 找不到 winegstreamer 目录，将在当前目录查找")
        winegstreamer_dir = '.'
    
    print()
    
    # 查找文件
    unixlib_path = find_file_in_winegstreamer('unixlib.c')
    wg_parser_path = find_file_in_winegstreamer('wg_parser.c')
    
    files_to_process = []
    if unixlib_path:
        files_to_process.append((unixlib_path, disable_gl_unixlib))
    else:
        print("警告: 找不到 unixlib.c")
    
    if wg_parser_path:
        files_to_process.append((wg_parser_path, disable_gl_wg_parser))
    else:
        print("警告: 找不到 wg_parser.c")
    
    if not files_to_process:
        print("\n错误: 没有找到任何需要处理的文件")
        print("请确保在 Wine 源码目录中运行此脚本")
        sys.exit(1)
    
    print()
    
    # 如果命令行指定了文件，使用命令行参数
    if len(sys.argv) > 1:
        files_to_process = []
        for f in sys.argv[1:]:
            if os.path.exists(f):
                if 'unixlib' in f:
                    files_to_process.append((f, disable_gl_unixlib))
                elif 'wg_parser' in f:
                    files_to_process.append((f, disable_gl_wg_parser))
            else:
                print(f"警告: 文件不存在 {f}")
    
    success_count = 0
    for file_path, handler in files_to_process:
        if handler(file_path):
            success_count += 1
    
    print(f"\n处理完成: {success_count}/{len(files_to_process)} 个文件")
    print("\n下一步:")
    print("  1. 返回 Wine 根目录: cd ../..")
    print("  2. 清理并重新编译: make clean && make")

if __name__ == '__main__':
    main()
    
