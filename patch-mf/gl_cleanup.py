#!/usr/bin/env python3
"""GL cleanup for no-GL builds - idempotent."""
for path in ['dlls/winegstreamer/unixlib.c', 'dlls/winegstreamer/wg_parser.c']:
    if not os.path.exists(path):
        continue
    t = open(path).read()
    t = t.replace('#include <gst/gl/gl.h>\n', '')
    t = t.replace('GstGLDisplay *gl_display;\n', '')
    t = t.replace('    static GstGLContext *gl_context;\n', '')
    t = t.replace('extern GstGLDisplay *gl_display;\n', '')
    t = t.replace('    bool use_opengl;\n', '')
    i = t.find('    if (!(gl_display = gst_gl_display_new()))')
    j = t.find('    if (!media_converter_init())', i)
    if i > 0 and j > i:
        t = t[:i] + t[j:]
    i = t.find('    if (!strcmp(name, "video/x-raw") && parser->use_opengl)')
    j = t.find('    else if (!strcmp(name, "video/x-raw"))', i)
    if i > 0 and j > i:
        t = t[:i] + t[j:]
        t = t.replace('    else if (!strcmp(name, "video/x-raw"))', '    if (!strcmp(name, "video/x-raw"))', 1)
    i = t.find('    if ((parser->use_opengl = params->use_opengl && gl_display))')
    j = t.find('    if (!(parser->task_pool = wg_task_pool_new()))', i)
    if i > 0 and j > i:
        t = t[:i] + t[j:]
    open(path, 'w').write(t)
print('GL cleanup done')
