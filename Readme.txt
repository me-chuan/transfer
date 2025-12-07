基于 TCP/IP Socket 的简易 FTP 客户端与服务器

一、开发与编译环境
    平台与操作系统

    开发与测试平台：PC
    操作系统：Linux（Ubuntu / 其它常见发行版均可）
    也可在 Windows、macOS 下运行（只要有 Python 3 环境）
    编程语言与工具

    语言：Python 3
    Python 版本：建议 Python 3.10 及以上
    使用库：
    标准库：socket、threading、os、tkinter、dataclasses、typing 等
    未使用第三方库，无需额外安装依赖
    编译说明

    Python 脚本为解释执行，无需显式“编译”步骤
    只需保证系统中安装了 Python 3，并可通过 python3 命令调用

二、程序结构说明
    工程目录结构（与本次大作业相关部分）：

    source

    - simple_ftp.py
        自实现的 FTP 客户端“库”，基于原始 TCP socket 实现 FTP 协议的最小子集（USER/PASS/PWD/CWD/MKD/RMD/DELE/RNFR/RNTO/TYPE/PASV/LIST/RETR/STOR/QUIT）。
    - ftp_client.py
        图形化 FTP 客户端，使用 tkinter 实现类似简化版 FileZilla 的界面：
        输入服务器地址、端口、用户名、密码连接服务器
        浏览远程目录、进入/返回目录
        创建/删除/重命名文件夹和文件
        上传/下载文件，新建文本文件等
        内部通过 simple_ftp.FTPConnection 与服务器通信。
    - simple_ftp_server.py
        自实现的简易 FTP 服务器，基于 TCP socket：
        支持用户认证、根目录限制、读/写权限控制
        实现与客户端配套的 FTP 命令子集
        使用被动模式（PASV）进行数据连接。
    - ftp_root
        FTP 服务器根目录，服务器会在这里创建和管理文件/文件夹。

三、运行平台与使用方法
    1. 运行平台要求
    已安装 Python 3 的桌面操作系统，推荐：

    Linux（Ubuntu 等）
    Windows 10/11
    macOS
    如需运行 GUI 客户端，需要系统支持 tkinter 图形界面库（大部分桌面版 Python 默认带有）。

四、服务器运行方法
    启动服务器
    在工程根目录（包含 source、ftp_root 的目录）执行：

    终端会输出类似：

    说明服务器正在监听 2121 端口，使用 ftp_root 作为 FTP 根目录。

    服务器配置说明（在 simple_ftp_server.py 中）
    监听地址与端口：
    用户与权限（在 FTPConfig.__post_init__ 中）：
    perm="r"：只读；perm="rw"：读写。

    远程访问说明
    若仅局域网访问：保持 host="0.0.0.0"，在局域网其他机器用服务器的局域网 IP + 端口 2121 连接即可。
    若公网访问：需额外配置路由器端口映射 / 云服务器安全组，开放 2121 端口。

    注：尽量在linux环境下运行服务端，因为windows环境往往有严格的权限管理，可能使文件操作失败

五、客户端运行与测试方法
    启动图形客户端
    在工程根目录执行：

    将弹出一个类似简化版 FileZilla 的 GUI 窗口。

    客户端连接设置
    在客户端界面顶部输入：

    Host（主机）：
    本机测试：127.0.0.1
    局域网测试：服务器所在机器的局域网 IP，如 192.168.1.100
    远程测试：服务器的公网 IP/域名（需已配置端口转发）
    Port（端口）：2121（与服务器配置一致）
    User（用户名） / Password（密码）：
    读写测试：user / 123456
    只读测试：guest / guest
    点击 “Connect” 按钮进行连接。

    基本功能测试步骤
    连接成功后，可按如下方式测试各项功能：

    目录浏览

    查看远程当前目录内容（根目录 / 对应 ftp_root）。
    双击目录进入下一级，点击 “Up” 返回上一级。
    新建/删除/重命名目录

    使用 “New Folder” 创建目录，检查服务器 ftp_root 下是否生成对应文件夹。
    使用 “Rename” 修改目录名，再检查服务器文件系统。
    使用 “Delete” 删除目录（读写用户），只读用户应被拒绝（返回权限错误）。
    文件上传（STOR）

    点击 “Upload”，选择本地文件。
    上传完成后，在列表中出现该文件，并在 ftp_root 中能看到对应文件。
    文件下载（RETR）

    在 GUI 中选择远程文件，点击 “Download”。
    选择本地保存路径。
    下载完成后，对比文件内容是否一致。
    新建文件

    点击 “New File”，输入文件名和初始内容。
    在服务器 ftp_root 对应目录下查看是否生成内容正确的文件。
    权限测试

    使用 guest / guest 登录，只读用户应能：
    浏览目录 / 下载文件
    不能上传、新建、删除、重命名（会得到 “Permission denied” / 5xx 错误）。

六、说明与限制
    为教学和课程大作业目的实现，仅支持 FTP 协议最小子集：
    控制命令：USER/PASS/PWD/CWD/TYPE/PASV/LIST/RETR/STOR/MKD/RMD/DELE/RNFR/RNTO/QUIT
    只实现被动模式（PASV），不支持主动模式（PORT）。
    未实现完整的错误处理、日志、安全机制，不适合生产环境使用或对外公网开放。
    客户端与服务器均基于阻塞 socket + 线程的简单模型，适合理解协议流程和 socket 编程基础。