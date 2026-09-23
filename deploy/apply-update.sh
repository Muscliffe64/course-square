#!/usr/bin/env bash
# 2026-09-21 审计修复上线脚本。在解压后的更新目录里以 root 执行：
#   bash deploy/apply-update.sh
# 第 1 步不通过时不会改动服务器上的任何东西。
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
HOST="${1:-123.57.56.38}"

echo "== 1/3 核对服务器当前代码 = 本次修改的基线"
if ! (cd /opt/course-square/current && md5sum -c --quiet "$HERE/deploy/pre-change.md5"); then
  echo "!! 服务器上的代码和本地改动前的版本不一致，已停止，没有做任何改动。"
  echo "!! 请把上面的输出复制给 Claude。"
  exit 1
fi
echo "   一致。"

echo "== 2/3 安装新版本（自动备份 → 迁移 → 补缩略图 → 静态文件 → 重启）"
cd "$HERE"
bash deploy/install.sh "$HOST"

echo "== 3/3 验证"
sleep 3
systemctl is-active course-square nginx
echo -n "healthz: "; curl -s -H "X-Forwarded-Proto: https" http://127.0.0.1:8017/healthz/; echo
echo -n "外网登录页 HTTP 状态: "; curl -sk -o /dev/null -w "%{http_code}\n" "https://$HOST/login/"
echo -n "数据库日志模式: "; runuser -u course-square -- python3 -c "import sqlite3;print(sqlite3.connect('/var/lib/course-square/db.sqlite3').execute('pragma journal_mode').fetchone()[0])"
echo "缩略图数量: $(ls /var/lib/course-square/media/post-thumbs 2>/dev/null | wc -l)"
ls -l /var/lib/course-square/ | grep sqlite
echo "当前版本: $(readlink /opt/course-square/current)"
echo "上一版本: $(cat /opt/course-square/previous-release.txt)"
echo "== 完成"
