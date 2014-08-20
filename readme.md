# WebRTC audio example

本工程是一个 WebRTC 实验页面，实现了多人音频聊天效果

在 Chrome 36 下测试通过

前端采用了 WebRTC api，[libmp3lame](https://github.com/akrennmair/libmp3lame-js)

后端采用了 Python Tornado

运行方法：

运行 run.py 后访问 https://本机ip:8888/login 输入名称后进入聊天页面

首次进入需要添加安全例外，因为 Chrome 只能记住 HTTPS 页面的 WebRTC 音频设备的许可状态
