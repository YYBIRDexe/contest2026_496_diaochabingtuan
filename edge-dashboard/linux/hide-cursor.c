/*
 * hide-cursor —— 让 X 会话彻底不显示鼠标光标。
 *
 * 为什么自己写：
 *   触控屏上不需要指针，但 X 默认始终显示。M1 上没有 unclutter，
 *   且设备无外网装不了包，所以用自带的 gcc 编译一个。
 *
 * 核心原理（含一次重要修正）：
 *   X 的光标是**逐窗口**属性。只对根窗口设置是不够的 —— 子窗口
 *   （浏览器内容区、桌面、面板等）会覆盖它，指针移上去光标就恢复可见。
 *   所以必须**递归遍历整棵窗口树**，给每个窗口都设透明光标，
 *   并在 --watch 模式下持续跟进新出现的窗口。
 *
 *   ⚠️ 不要用 XFixesSetWindowShapeRegion(..., None)：
 *   本设备 Xorg（1.20.4 + hobot fbdev）会因此**段错误崩溃**（实测踩过）。
 *   纯 XDefineCursor 属 X11 核心协议，安全且足够。
 *
 * 编译（设备无 libXfixes.so 符号链接，故显式写 .so.3；
 *       本程序其实只依赖 libX11）：
 *   gcc -O2 -o hide-cursor hide-cursor.c -lX11
 *
 * 用法：
 *   ./hide-cursor              设置一次（含所有子窗口）后退出
 *   ./hide-cursor --watch      常驻，持续跟进新窗口（推荐用于看板）
 *   ./hide-cursor --check      只报告编译配置，不连接 X
 */

#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static Cursor g_invisible = None;
static int g_count = 0;

/* 构造 1x1 全透明光标 */
static Cursor make_invisible_cursor(Display *dpy, Window root)
{
    char zero[1] = { 0 };
    Pixmap src = XCreateBitmapFromData(dpy, root, zero, 1, 1);
    if (!src) {
        return None;
    }
    XColor dummy;
    memset(&dummy, 0, sizeof(dummy));
    Cursor cur = XCreatePixmapCursor(dpy, src, src, &dummy, &dummy, 0, 0);
    XFreePixmap(dpy, src);
    return cur;
}

/*
 * 递归给窗口及其所有子窗口设置透明光标。
 *
 * 这就是修复点：上一版只 set 根窗口，于是指针一进入 Firefox 就恢复可见。
 */
static void apply_tree(Display *dpy, Window w)
{
    XDefineCursor(dpy, w, g_invisible);
    g_count++;

    Window r, parent, *children = NULL;
    unsigned int n = 0;
    if (XQueryTree(dpy, w, &r, &parent, &children, &n)) {
        for (unsigned int i = 0; i < n; i++) {
            apply_tree(dpy, children[i]);
        }
        if (children) {
            XFree(children);
        }
    }
}

int main(int argc, char **argv)
{
    int watch = 0, check_only = 0, quiet = 0, i;
    for (i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--watch") == 0) {
            watch = 1;
        } else if (strcmp(argv[i], "--check") == 0) {
            check_only = 1;
        } else if (strcmp(argv[i], "--quiet") == 0) {
            quiet = 1;
        }
    }

    if (check_only) {
        fprintf(stderr, "hide-cursor 版本: 递归窗口树（纯 XDefineCursor）\n");
        fprintf(stderr, "作用范围: 根窗口 + 所有子窗口\n");
        fprintf(stderr, "默认行为: %s\n", watch ? "常驻跟进新窗口" : "设置一次后退出");
        return 0;
    }

    Display *dpy = XOpenDisplay(NULL);
    if (!dpy) {
        fprintf(stderr, "hide-cursor: 无法连接 X（DISPLAY=%s）\n",
                getenv("DISPLAY") ? getenv("DISPLAY") : "(未设置)");
        return 1;
    }

    Window root = DefaultRootWindow(dpy);
    g_invisible = make_invisible_cursor(dpy, root);
    if (g_invisible == None) {
        fprintf(stderr, "hide-cursor: 创建透明光标失败\n");
        _exit(1);
    }

    g_count = 0;
    apply_tree(dpy, root);
    XSync(dpy, False);

    if (!quiet) {
        fprintf(stderr, "hide-cursor: 已对 %d 个窗口设置透明光标%s\n",
                g_count, watch ? "，进入常驻跟进" : "");
    }

    if (!watch) {
        /*
         * 用 _exit 而非 return：XCloseDisplay 会触发 Xlib 的 IO 错误处理器
         * （服务端在连接关闭时报 "X connection broken"），那会调用 exit(1)，
         * 把成功的退出码改坏，让 start.sh 误判为失败。
         */
        _exit(0);
    }

    /*
     * 常驻：浏览器新建窗口、面板重绘等都会产生新的子窗口，
     * 新窗口没有透明光标，指针移上去就会重新出现。
     * 所以每秒重扫一遍窗口树补齐。
     */
    for (;;) {
        sleep(1);
        while (XPending(dpy)) {
            XEvent e;
            XNextEvent(dpy, &e);
        }
        g_count = 0;
        apply_tree(dpy, root);
        XSync(dpy, False);
    }

    XCloseDisplay(dpy);
    return 0;
}
