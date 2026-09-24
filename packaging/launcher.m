/*
 * launcher.m — Motion Arcade 的 Mach-O 启动器
 * ==========================================
 * 为什么需要它（这是整个项目最容易踩的坑）：
 *
 *   macOS 的摄像头授权（TCC）是**按"责任进程"的代码签名**来判定的。
 *   如果直接从 IDE / 终端启动 python，责任进程就是 IDE 本身；
 *   而 IDE 的 Info.plist 里没有 NSCameraUsageDescription，
 *   于是 macOS 会**静默拒绝**摄像头请求 —— 不弹窗、不报错，
 *   只留下 OpenCV 的 "not authorized to capture video"。
 *   给 IDE 配"完全磁盘访问"也没用，这是内核层面的保护。
 *
 *   解决办法是让一个真正的 .app 包来发起请求：
 *     1) 可执行文件必须是**真正的 Mach-O**（不能是 shell 脚本，
 *        因为 `exec python` 会把签名身份丢掉）；
 *     2) Info.plist 里声明 NSCameraUsageDescription；
 *     3) ad-hoc 签名后，系统弹窗会以这个 App 的名义出现，用户点允许即可。
 *
 *   本程序只做三件事：请求权限 → 把日志落盘 → execv 换进 python。
 */
#import <AVFoundation/AVFoundation.h>
#import <Foundation/Foundation.h>
#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

/* 由可执行文件路径反推项目目录：
 *   .../motion_arcade/MotionArcade.app/Contents/MacOS/MotionArcade
 *   连续 4 次截断最后一个 '/' 之后的部分，得到 .../motion_arcade
 */
static void project_dir(char *out, size_t n) {
    char path[PATH_MAX];
    uint32_t sz = sizeof(path);
    if (_NSGetExecutablePath(path, &sz) != 0) {
        snprintf(out, n, ".");
        return;
    }
    for (int i = 0; i < 4; i++) {
        char *slash = strrchr(path, '/');
        if (!slash) break;
        *slash = '\0';
    }
    snprintf(out, n, "%s", path);
}

int main(int argc, char *argv[]) {
    @autoreleasepool {
        char dir[PATH_MAX];
        project_dir(dir, sizeof(dir));

        /* 日志落盘：.app 没有终端，stdout/stderr 必须重定向，
         * 否则排查摄像头问题时什么都看不到。
         * 注意 stdout / stderr 要用各自独立的文件描述符打开，
         * 否则两个 freopen("w") 会互相覆盖。 */
        char log_path[PATH_MAX];
        snprintf(log_path, sizeof(log_path), "%s/run.log", dir);
        FILE *f = freopen(log_path, "w", stdout);
        (void)f;
        int fd = open(log_path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
        if (fd >= 0) {
            dup2(fd, STDERR_FILENO);
            close(fd);
        }

        printf("[launcher] 项目目录：%s\n", dir);
        fflush(stdout);

        /* 请求摄像头权限。只有在 App 包的 Info.plist 里声明了
         * NSCameraUsageDescription，这个弹窗才会出现。 */
        AVAuthorizationStatus status =
            [AVCaptureDevice authorizationStatusForMediaType:AVMediaTypeVideo];
        if (status == AVAuthorizationStatusNotDetermined) {
            dispatch_semaphore_t sem = dispatch_semaphore_create(0);
            __block BOOL granted = NO;
            [AVCaptureDevice requestAccessForMediaType:AVMediaTypeVideo
                                     completionHandler:^(BOOL ok) {
                granted = ok;
                dispatch_semaphore_signal(sem);
            }];
            dispatch_semaphore_wait(sem, dispatch_time(DISPATCH_TIME_NOW, 60 * NSEC_PER_SEC));
            printf("[launcher] 用户授权结果：%s\n", granted ? "允许" : "拒绝");
        } else {
            printf("[launcher] 摄像头授权状态已存在：%ld（0=未决定 1=受限 2=拒绝 3=允许）\n",
                   (long)status);
        }
        fflush(stdout);

        /* 换进 python。execv 会保留当前进程的签名身份，
         * 因此摄像头授权依然归属本 App。 */
        char py[PATH_MAX];
        char script[PATH_MAX];
        snprintf(py, sizeof(py), "%s/.venv/bin/python", dir);
        snprintf(script, sizeof(script), "%s/main.py", dir);
        if (access(py, X_OK) != 0) {
            snprintf(py, sizeof(py), "/usr/bin/env");
            char *eargv[] = {"python3", script, NULL};
            printf("[launcher] 未找到 .venv，回退系统 python3\n");
            fflush(stdout);
            execvp("python3", eargv);
            perror("[launcher] exec python3 失败");
            return 1;
        }
        printf("[launcher] 启动：%s %s\n", py, script);
        fflush(stdout);
        char *eargv[] = {py, script, NULL};
        execv(py, eargv);
        perror("[launcher] exec python 失败");
        return 1;
    }
}
