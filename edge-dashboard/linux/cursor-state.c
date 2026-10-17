/*
 * cursor-state —— 判定屏幕上此刻显示的光标是否可见（不依赖抓屏、不解析光标图像）。
 *
 * 前三种验证方法全部失败，记录如下以免重蹈覆辙：
 *   1. 「截图里没光标」—— 只能说明指针当时不在画面里；
 *   2. 「指针附近亮像素」—— 深色光标在深色背景上检测不到；
 *   3. 「差分法」—— 实测证明 **xwd 抓屏根本不含光标**：
 *      故意把光标设成正常箭头时，两次抓图差分依然为 0。
 *      所以差分法无论光标是否可见都返回 DIFF=0，永远假通过。
 *   4. 「解析 XFixesCursorImage」—— 结构体内存布局靠手工推断，
 *      实测字段读出来恒为 0，同样不可信。
 *
 * 本程序的思路（不碰上面任何坑）：
 *   X 的光标是**逐窗口**属性。窗口的 cursor 为 None 时，实际显示的是
 *   其祖先窗口里最近的一个非 None 光标。所以：
 *     1. 找到指针所在的窗口；
 *     2. 沿父链向上找第一个 cursor != None 的窗口 —— 那就是当前生效的光标；
 *     3. 与我们自己创建的 1x1 全透明光标比较 XID。
 *        X 服务端会对相同的光标资源去重，所以只要窗口挂的是同样的透明光标，
 *        XID 就应当一致。
 *
 *   为了排除「XID 恰好不同」的误判，额外用 XQueryBestCursor 之类的信息不足，
 *   因此再加入一条独立证据：同时报告根窗口与其子窗口的 cursor 是否为 None，
 *   以及最终生效光标的 XID，交由调用方交叉判断。
 *
 * 编译：gcc -O2 -o cursor-state cursor-state.c -lX11
 * 用法：DISPLAY=:0 ./cursor-state
 *       退出码 0 = 光标不可见；1 = 光标可见；2 = 无法判定
 */

#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static Cursor make_invisible(Display *dpy, Window root)
{
    char zero[1] = { 0 };
    Pixmap src = XCreateBitmapFromData(dpy, root, zero, 1, 1);
    if (!src) {
        return None;
    }
    XColor dummy;
    memset(&dummy, 0, sizeof(dummy));
    Cursor c = XCreatePixmapCursor(dpy, src, src, &dummy, &dummy, 0, 0);
    XFreePixmap(dpy, src);
    return c;
}

int main(void)
{
    Display *dpy = XOpenDisplay(NULL);
    if (!dpy) {
        fprintf(stderr, "cursor-state: 无法连接 X\n");
        return 2;
    }

    Window root = DefaultRootWindow(dpy);

    /* 指针所在窗口 */
    Window rr, child;
    int rx = 0, ry = 0, wx = 0, wy = 0;
    unsigned int mask = 0;
    if (!XQueryPointer(dpy, root, &rr, &child, &rx, &ry, &wx, &wy, &mask)) {
        printf("POINTER=unknown\n");
        fprintf(stderr, "cursor-state: 无法查询指针\n");
        XCloseDisplay(dpy);
        return 2;
    }

    Window start = (child != None) ? child : root;
    printf("POINTER_WINDOW=%lu\n", (unsigned long)start);
    printf("POINTER_POS=%d,%d\n", rx, ry);

    /*
     * 沿父链向上找第一个定义了光标的窗口 —— 那就是当前实际显示的光标。
     * 同时记录链上各窗口的 cursor，便于诊断。
     */
    Cursor ours = make_invisible(dpy, root);
    printf("OUR_CURSOR=%lu\n", (unsigned long)ours);

    Window w = start;
    Cursor effective = None;
    Window effective_win = None;
    int depth = 0;

    while (w != None && depth < 32) {
        XWindowAttributes a;
        if (!XGetWindowAttributes(dpy, w, &a)) {
            break;
        }
        printf("  chain[%d] win=%lu cursor=%lu\n", depth, (unsigned long)w,
               (unsigned long)a.cursor);
        if (a.cursor != None) {
            effective = a.cursor;
            effective_win = w;
            break;
        }
        Window r, parent, *kids = NULL;
        unsigned int n = 0;
        if (!XQueryTree(dpy, w, &r, &parent, &kids, &n)) {
            break;
        }
        if (kids) {
            XFree(kids);
        }
        if (parent == w) {
            break;
        }
        w = parent;
        depth++;
    }

    printf("EFFECTIVE_WINDOW=%lu\n", (unsigned long)effective_win);
    printf("EFFECTIVE_CURSOR=%lu\n", (unsigned long)effective);

    XCloseDisplay(dpy);

    /*
     * 判定：
     *   - 父链上找不到任何非 None 光标 → 用系统默认光标（可见）→ VISIBLE
     *   - 生效光标 XID 与我们创建的透明光标一致 → HIDDEN
     *   - 其它 → 无法确定，报 UNKNOWN 让调用方用其它证据交叉判断
     */
    if (effective == None) {
        printf("VERDICT=VISIBLE\n");
        printf("REASON=父链上无自定义光标，将使用系统默认箭头\n");
        return 1;
    }
    if (effective == ours) {
        printf("VERDICT=HIDDEN\n");
        printf("REASON=生效光标与我们的 1x1 透明光标 XID 相同\n");
        return 0;
    }
    printf("VERDICT=UNKNOWN\n");
    printf("REASON=生效光标是另一个资源（XID 不同），需交叉判断\n");
    return 2;
}
