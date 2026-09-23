# 人工智能导论 · 课程广场

一个班级共用的课程社区。三个栏目：下节课想听什么、作品与分享、课程资料。支持匿名/实名发帖与评论、点赞、教师公告、作品图片与链接、资料下载、管理后台。

首页有一行发帖框（勾「只给老师看」即为实名课后小票）和「下节课想听什么」投票（赞同即投票，票数最高的一条下节课一定讲）。教师有「待回应」页、排进第 N 讲、站外推送提醒。详见 `docs/2026-09-23-lectures-pending-quickpost.md`。

## 本地启动

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python manage.py migrate
.venv/bin/python manage.py runserver 127.0.0.1:8017
```

开发模式默认只绑定本机。生产环境必须设置 `DJANGO_DEBUG=false` 和独立 `DJANGO_SECRET_KEY`。环境变量见 `.env.example`，应用不自动加载 `.env`，systemd 使用 `EnvironmentFile` 加载生产配置。

## 学生账号

```bash
.venv/bin/python manage.py import_students '/absolute/path/点名册.xlsx' --dry-run
.venv/bin/python manage.py import_students '/absolute/path/点名册.xlsx'
```

XLSX 自动查找「学号」「姓名」列；CSV 使用 `student_id,name` 标题。账号和默认密码为学号，姓名固定绑定名单；不强制改密。重复导入不重置已有密码。名单和数据库只保存在私有目录，不提交源码。忘记密码由教师后台重置。

默认密码容易被知道学号的人猜到；仍在使用默认密码的学生会在页面顶部看到修改提示。平台不把发帖作为可信的成绩或考勤依据。匿名仅对其他同学隐藏身份，管理员可查看，发布界面已说明。图片和音频会原样保留上传时的文件名与元数据，并只通过登录后的私有地址提供；页面中显示的是去除 EXIF/GPS 的缩略图（最长边 1200px），点击“查看原图”得到的仍是原文件。若文件名、原图元数据、图片画面、正文或链接本身包含姓名，匿名选项不能隐藏这些内容。

## 教师管理

```bash
.venv/bin/python manage.py createsuperuser
```

进入 `/admin/`，管理帖子（置顶、准备讲、已回应）、评论、公告、资料、举报及学生账号。管理员使用独立强密码。只上传可分享的最终报告与讲稿，不上传名单或含有未处理个人信息的问卷原始答卷。

教师登录课程广场后，侧边栏“消息通知”会显示学生的新留言；点击可直接跳到相应讨论并回复。学生只会收到与自己有关的消息：帖子被点赞、留言被回复、帖子被排进某一讲。

**每学期开始先在后台「讲次」里录入各讲的日期**：投票截止时间、「排进第 N 讲」、课后小票的归属都依赖它。

侧边栏“待回应”列出学生发了、教师还没接话的帖子和留言，最早的在前。回复、排进讲次或点“无需回复”后消失。配置 `TEACHER_NOTIFY_WEBHOOK`（Server 酱 / 企业微信 / 飞书 / 钉钉）后，`course-square-notify.timer` 每 30 分钟检查一次，有新内容才推送，推送里不含学生姓名。

课后小票在后台「课后小票」查看（含真名）；在「讲次」列表勾选讲次后可导出 CSV，姓名替换为稳定代号，供平台外摘要使用。

## 阿里云部署

适用于有 Python 3.10+ 和 systemd 的 Linux ECS。部署前检查现有站点、端口、内存和磁盘。不要覆盖原有代理配置。

1. 通过已有 SSH 密钥或云控制台连接用户指定的服务器，上传本目录源码，排除 `.venv/`、`data/`、`private/`、`.env*`、`output/`、`test-results/`。名单另外放在服务器权限 0600 的私有目录。
2. 在源码目录以 root 执行 `bash deploy/install.sh 实际域名`。脚本建立独立服务用户、持久存储、版本目录和 systemd 服务，仅监听 `127.0.0.1:8017`。默认要求 HTTPS。
3. 为课程域名配置 HTTPS 虚拟主机，将 `deploy/nginx.conf` 的 location 段加入该虚拟主机。确认 `nginx -t` 成功后 reload。只由可信本机代理设置 `X-Forwarded-Proto`；不要直接向公网开放 8017。
4. 在已加载 `/etc/course-square.env` 的管理员 shell 中，使用 `/opt/course-square/current/.venv/bin/python /opt/course-square/current/manage.py` 执行名单导入和 `createsuperuser`。导入后确认数据库文件仍归 `course-square` 所有。
5. 验证 HTTPS 登录、发帖、评论、匿名显示、权限拦截、图片与资料下载、管理后台和服务重启后数据持久性，再分享链接。

服务器没有域名/TLS 时，应先使用 SSH 端口转发做私有验收，再确定公开访问方案。不要将示例域名或任意其他服务器作为上线目标。

## 备份与回退

```bash
sudo python3 /opt/course-square/current/deploy/backup.py
```

备份包含 SQLite 一致性快照和附件，默认位于 `/var/backups/course-square/`，权限 0600。若要求数据库与附件处于完全同一时点，请在短暂维护窗口停止服务后备份。源码发布不包含数据库或附件。需要异机备份时再指定接收位置。

安装脚本在已有数据库上升级前自动备份，保留全部 release，并将旧 release 路径写入 `/opt/course-square/previous-release.txt`。回退时先停止服务、保存当前数据，再确认迁移兼容性；仅当数据库迁移兼容时切回旧源码，否则恢复对应数据库及附件备份。不要直接删除持久目录。

## 验证

```bash
.venv/bin/python manage.py generate_thumbnails   # 为历史图片补缩略图，可重复执行
.venv/bin/python manage.py collectstatic --noinput   # 有一项测试在 DEBUG=False 下取静态文件，需要先收集
.venv/bin/python manage.py test
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
```

框架版本使用 [Django 官方发布的 5.2 LTS](https://www.djangoproject.com/download/)。所有课程页面和附件均需登录；文件存储目录不公开映射。登录保护、CSRF、上传限制和匿名身份隔离由服务端执行。
