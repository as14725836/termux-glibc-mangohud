#!/usr/bin/env python3
import re

file_path = "dlls/winegstreamer/unixlib.c"

# 读取文件
with open(file_path, 'r') as f:
    content = f.read()

# 1. 注释掉 GL 头文件
content = content.replace('#include <gst/gl/gl.h>', '/* #include <gst/gl/gl.h> */')

# 2. 注释掉 GL 变量声明
content = content.replace('GstGLDisplay *gl_display;', '/* GstGLDisplay *gl_display; */')
content = content.replace('int wine_gst_no_gl = -1;', '/* int wine_gst_no_gl = -1; */')

# 3. 注释掉 GL 上下文变量
content = content.replace('    static GstGLContext *gl_context;', '    /* static GstGLContext *gl_context; */')

# 4. 在 wine_gst_no_gl 检查前添加 #if 0
content = content.replace(
    '\tif (wine_gst_no_gl == -1)',
    '#if 0 /* Disable GL support */\n\tif (wine_gst_no_gl == -1)'
)

# 5. 在函数结束前添加 #endif
# 找到 wg_init_gstreamer 函数的结束位置
lines = content.split('\n')
new_lines = []
found_func = False
count_braces = 0

for i, line in enumerate(lines):
    if 'NTSTATUS wg_init_gstreamer' in line:
        found_func = True
        count_braces = 0
    
    if found_func:
        count_braces += line.count('{') - line.count('}')
        
        # 在函数结束前添加 #endif
        if count_braces == 0 and line.strip() == '}':
            new_lines.append('#endif /* Disable GL support */')
            found_func = False
    
    new_lines.append(line)

content = '\n'.join(new_lines)

# 写入文件
with open(file_path, 'w') as f:
    f.write(content)

print("GL 支持已禁用")
