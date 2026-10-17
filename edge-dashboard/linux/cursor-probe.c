/*
 * cursor-probe —— 直接读取 X 服务端当前的鼠标光标图像，判断是否可见。
 *
 * 为什么需要它（前两次验证都不可靠）：
 *   1. 「截图里没看到光标」—— 只能说明指针当时不在画面里；
 *   2. 「指针附近亮像素数」—— 深色光标在深色背景上检测不到；
 *   3. 「差分法」—— 若 xwd 抓屏本身就不含光标（光标由硬件叠加），
 *      那么两次抓图必然完全相同，DIFF 恒为 0，**永远判定为已隐藏**。
 *
 * 本程序直接问 X 服务端要光标图像（XFixesGetCursorImage），
 * 统计其非透明像素，结论不依赖任何抓屏行为。
 *
 * 只在 XFixes 的 **Get** 接口上工作，完全不碰会让本设备 Xorg 段错误的
 * XFixesSetWindowShapeRegion。
 *
 * 编译：gcc -O2 -o cursor-probe cursor-probe.c -lX11
 *       （设备无 libXfixes.so 符号链接，故显式链接 .so.3）
 * 用法：DISPLAY=:0 ./cursor-probe
 *       退出码 0 = 光标不可见；1 = 光标可见；2 = 无法判定
 */

#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* ---- 手工声明 XFixes 只读接口（设备无 Xfixes.h） ---- */
typedef XID XserverRegion;

/*
 * XFixesCursorImage 的精确内存布局（对照 Xlib 官方定义）。
 *
 * ⚠️ 第一个 dummy 字段不可省略：官方结构在 4 个 unsigned short 之后
 * 紧跟着一个 `unsigned long *pixels`，编译器会插入 4 字节对齐填充
 * （aarch64 上 unsigned long 需 8 字节对齐）。
 * 漏掉这个填充会让 pixels 指针偏移 4 字节，读取时**段错误**（已实测踩过）。
 */
typedef struct {
    unsigned long version;        /* 4 × unsigned long */
    unsigned long serial;
    unsigned long length;
    unsigned long dummy;          /* 对齐填充，勿删 */
    unsigned short width;         /* 4 × unsigned short */
    unsigned short height;
    unsigned short xhot;
    unsigned short yhot;
    unsigned long *pixels;        /* ARGB, 每像素一个 unsigned long */
    void *cursor_serial;
} XFixesCursorImageLocal;

extern int XFixesQueryExtension(Display *dpy, int *event_base, int *error_base);
extern XFixesCursorImageLocal *XFixesGetCursorImage(Display *dpy);
/*
 * 注意：不要调用 XFixesFreeCursorImage。
 * 本设备的 libXfixes.so.3 里没有导出该符号（链接会报
 * undefined reference），而且这只是一次性探针进程，结束后
 * 由系统回收内存即可，无需显式释放。
 */

int main(int argc, char **argv)
{
    int verbose = 0, i;
    for (i = 1; i < argc; i++) {
        if (strcmp(argv[i], "-v") == 0) {
            verbose = 1;
        }
    }

    Display *dpy = XOpenDisplay(NULL);
    if (!dpy) {
        fprintf(stderr, "cursor-probe: 无法连接 X\n");
        return 2;
    }

    int eb = 0, erb = 0;
    if (!XFixesQueryExtension(dpy, &eb, &erb)) {
        printf("XFIXES=no\n");
        fprintf(stderr, "cursor-probe: 无 XFixes 扩展，无法判定\n");
        XCloseDisplay(dpy);
        return 2;
    }
    printf("XFIXES=yes\n");

    XFixesCursorImageLocal *img = XFixesGetCursorImage(dpy);
    if (!img) {
        printf("READ=no\n");
        fprintf(stderr, "cursor-probe: 读取光标图像失败\n");
        XCloseDisplay(dpy);
        return 2;
    }

    unsigned long total = (unsigned long)img->width * (unsigned long)img->height;
    unsigned long opaque = 0;
    unsigned int maxalpha = 0;
    unsigned long sumalpha = 0;

    for (unsigned long k = 0; k < total; k++) {
        /* 低 32 位为 ARGB；高字节是 alpha */
        unsigned int a = (unsigned int)((img->pixels[k] >> 24) & 0xff);
        sumalpha += a;
        if (a > maxalpha) {
            maxalpha = a;
        }
        if (a > 127) {
            opaque++;
        }
    }

    printf("WIDTH=%u\n", (unsigned)img->width);
    printf("HEIGHT=%u\n", (unsigned)img->height);
    printf("HOTSPOT=%u,%u\n", (unsigned)img->xhot, (unsigned)img->yhot);
    printf("TOTAL=%lu\n", total);
    printf("OPAQUE=%lu\n", opaque);
    printf("MAXALPHA=%u\n", maxalpha);
    printf("AVGALPHA=%lu\n", total ? sumalpha / total : 0);

    if (verbose) {
        /* 打印前若干像素的 alpha，便于人工核对 */
        unsigned long n = total < 16 ? total : 16;
        fprintf(stderr, "前 %lu 个像素 alpha:", n);
        for (unsigned long k = 0; k < n; k++) {
            fprintf(stderr, " %u", (unsigned int)((img->pixels[k] >> 24) & 0xff));
        }
        fprintf(stderr, "\n");
    }

    /*
     * 不调用 XFixesFreeCursorImage（设备运行库未导出该符号）。
     * 本进程随即退出，交给系统回收即可。
     */
    XCloseDisplay(dpy);

    /*
     * 判定：完全不透明像素数为 0（或最大 alpha 也很低）= 光标不可见。
     * 透明光标是 1x1 且 alpha=0；正常光标会有几十到上千个不透明像素。
     */
    if (opaque == 0 && maxalpha < 8) {
        printf("VERDICT=HIDDEN\n");
        return 0;
    }
    printf("VERDICT=VISIBLE\n");
    return 1;
}
