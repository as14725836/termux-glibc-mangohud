#!/usr/bin/env python3
"""
Wine GStreamer GL 支持禁用脚本
精确处理 unixlib.c 和 wg_parser.c
"""
import os
import re
import shutil
import sys

def get_file_path(filename):
    """获取文件路径"""
    if os.path.exists(filename):
        return filename
    sub_path = os.path.join('dlls', 'winegstreamer', filename)
    if os.path.exists(sub_path):
        return sub_path
    if os.path.basename(os.getcwd()) == 'winegstreamer' and os.path.exists(filename):
        return filename
    return None

def disable_gl_in_unixlib(file_path):
    """禁用 unixlib.c 中的 GL 支持"""
    print(f"\n📄 处理: {os.path.basename(file_path)}")
    
    if not os.path.exists(file_path):
        print(f"❌ 文件不存在: {file_path}")
        return False
    
    backup_path = file_path + '.bak'
    if not os.path.exists(backup_path):
        shutil.copy2(file_path, backup_path)
        print(f"   ✅ 已备份: {os.path.basename(backup_path)}")
    
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    
    # 1. 注释掉 GL 头文件
    content = content.replace('#include <gst/gl/gl.h>', '/* #include <gst/gl/gl.h> */')
    
    # 2. 注释掉 GL 变量声明
    content = content.replace('GstGLDisplay *gl_display;', '/* GstGLDisplay *gl_display; */')
    content = content.replace('int wine_gst_no_gl = -1;', '/* int wine_gst_no_gl = -1; */')
    content = content.replace('    static GstGLContext *gl_context;', '    /* static GstGLContext *gl_context; */')
    
    # 3. 用 #if 0 包裹 wg_init_gstreamer 中的 GL 代码
    lines = content.split('\n')
    new_lines = []
    in_wg_init = False
    brace_count = 0
    gl_block_started = False
    
    for line in lines:
        if 'NTSTATUS wg_init_gstreamer' in line:
            in_wg_init = True
            brace_count = 0
        
        if in_wg_init:
            brace_count += line.count('{') - line.count('}')
            
            if 'if (wine_gst_no_gl == -1)' in line and not gl_block_started:
                new_lines.append('#if 0 /* Disable GL support - start */')
                gl_block_started = True
            
            if brace_count == 0 and line.strip() == '}' and gl_block_started:
                new_lines.append('#endif /* Disable GL support - end */')
                gl_block_started = False
                in_wg_init = False
        
        new_lines.append(line)
    
    content = '\n'.join(new_lines)
    
    # 4. 注释掉 gst_object_unref(gl_display)
    content = content.replace('gst_object_unref(gl_display);', '/* gst_object_unref(gl_display); */')
    
    # 5. 添加宏定义
    if '#define HAVE_GST_GL 0' not in content:
        content = content.replace(
            '#include "unix_private.h"',
            '#include "unix_private.h"\n\n/* GL support disabled */\n#define HAVE_GST_GL 0'
        )
    
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"   ✅ 修改完成")
    return True

def disable_gl_in_wg_parser(file_path):
    """禁用 wg_parser.c 中的 GL 支持 - 精确版本"""
    print(f"\n📄 处理: {os.path.basename(file_path)}")
    
    if not os.path.exists(file_path):
        print(f"❌ 文件不存在: {file_path}")
        return False
    
    backup_path = file_path + '.bak'
    if not os.path.exists(backup_path):
        shutil.copy2(file_path, backup_path)
        print(f"   ✅ 已备份: {os.path.basename(backup_path)}")
    
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    
    # 1. 注释掉 GL 头文件
    content = content.replace('#include <gst/gl/gl.h>', '/* #include <gst/gl/gl.h> */')
    
    # 2. 注释掉 extern GstGLDisplay *gl_display
    content = content.replace('extern GstGLDisplay *gl_display;', '/* extern GstGLDisplay *gl_display; */')
    
    # 3. 修改结构体中的 use_opengl - 只改注释
    content = content.replace('    bool use_opengl;', '    bool use_opengl; /* GL support disabled */')
    
    # 4. 精确替换 wg_parser_create 中的 GL 初始化代码
    # 找到要替换的 GL 代码块
    old_gl_block = '''    if (wine_gst_no_gl)
    	params->use_opengl = false;
    	
    if ((parser->use_opengl = params->use_opengl && gl_display))
    {
        if ((parser->context = gst_context_new(GST_GL_DISPLAY_CONTEXT_TYPE, false)))
            gst_context_set_gl_display(parser->context, gl_display);
        else
        {
            GST_ERROR("Failed to create parser context");
            parser->use_opengl = FALSE;
        }
    }'''
    
    new_gl_block = '''    /* GL support disabled */
    parser->use_opengl = FALSE;'''
    
    # 精确替换
    if old_gl_block in content:
        content = content.replace(old_gl_block, new_gl_block)
        print(f"   ✅ 替换 GL 初始化代码")
    else:
        # 尝试更宽松的匹配
        pattern = r'if\s*\(\s*wine_gst_no_gl\s*\)\s*params->use_opengl = false;\s*if\s*\(\s*\(\s*parser->use_opengl = params->use_opengl && gl_display\s*\)\s*\)\s*\{[^}]*\}'
        content = re.sub(pattern, '    /* GL support disabled */\n    parser->use_opengl = FALSE;', content, flags=re.DOTALL)
        print(f"   ✅ 使用正则替换 GL 初始化代码")
    
    # 5. 注释掉所有 gst_gl_* 函数调用（确保没有残留）
    gl_funcs = [
        'gst_context_new.*GST_GL_DISPLAY_CONTEXT_TYPE',
        'gst_context_set_gl_display',
    ]
    for func in gl_funcs:
        pattern = r'(\s*)(%s\s*\([^;]*\);?)' % func
        content = re.sub(pattern, r'\1/* \2 */', content, flags=re.DOTALL)
    
    # 6. 注释掉 context 相关的代码
    content = re.sub(
        r'if\s*\(\s*parser->context\s*\)\s*gst_context_unref\s*\(\s*parser->context\s*\)',
        '/* if (parser->context) gst_context_unref(parser->context) */',
        content
    )
    content = re.sub(
        r'if\s*\(\s*parser->context\s*\)\s*gst_element_set_context\s*\(\s*parser->container\s*,\s*parser->context\s*\)',
        '/* if (parser->context) gst_element_set_context(parser->container, parser->context) - GL disabled */',
        content
    )
    
    # 7. 添加宏定义
    if '#define HAVE_GST_GL 0' not in content:
        content = content.replace(
            '#include "unix_private.h"',
            '#include "unix_private.h"\n\n/* GL support disabled */\n#define HAVE_GST_GL 0'
        )
    
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"   ✅ 修改完成")
    return True

def main():
    print("=" * 60)
    print("Wine GStreamer GL 支持禁用脚本")
    print("=" * 60)
    print()
    
    # 查找文件
    unixlib_path = get_file_path('unixlib.c')
    wg_parser_path = get_file_path('wg_parser.c')
    
    if not unixlib_path and not wg_parser_path:
        print("❌ 找不到 unixlib.c 或 wg_parser.c")
        print("请确保在 Wine 源码根目录或 dlls/winegstreamer/ 目录运行")
        sys.exit(1)
    
    success_count = 0
    total_count = 0
    
    if unixlib_path:
        total_count += 1
        if disable_gl_in_unixlib(unixlib_path):
            success_count += 1
    else:
        print(f"⚠️  警告: 找不到 unixlib.c")
    
    if wg_parser_path:
        total_count += 1
        if disable_gl_in_wg_parser(wg_parser_path):
            success_count += 1
    else:
        print(f"⚠️  警告: 找不到 wg_parser.c")
    
    print()
    print("=" * 60)
    print(f"✅ 完成！成功处理 {success_count}/{total_count} 个文件")
    print()
    print("下一步:")
    print("  1. 清理并重新编译: make clean && make")
    print("  2. 或者直接编译: make")
    print("=" * 60)

if __name__ == '__main__':
    main()
    
