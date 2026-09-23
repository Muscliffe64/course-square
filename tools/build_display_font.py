"""生成标题用的宋体子集 static/board/fonts/cs-display.woff2。

标题字体只用在「固定文案」上（品牌名、页面大标题、热榜标题和名次数字、登录页），
所以只需要把这些字打进子集，文件很小。帖子标题等用户内容仍然用系统黑体。

改了下面 DISPLAY_TEXT 里涉及的模板文案，或者新加了用 var(--display) 的地方，要重新跑一遍：

    python3 tools/build_display_font.py /path/to/NotoSerifCJK-Black.ttc

字体：思源宋体 / Noto Serif CJK SC Black，SIL Open Font License 1.1（见 static/board/fonts/OFL.txt）。
"""
import sys
from pathlib import Path
from fontTools.ttLib import TTCollection, TTFont
from fontTools import subset

DISPLAY_TEXT = [
    "课程广场", "人工智能导论",
    # 页面大标题（.page-heading h1）
    "下节课想听什么", "作品与分享", "课程资料", "待回应", "消息通知", "账号设置", "修改密码",
    "把内容调整好", "把想法放在这里",
    # 空状态、错误页
    "删除这条内容？", "密码已修改", "这条内容不在这里了", "没有找到这个页面", "暂时无法完成这个操作",
    "请重新打开登录页面", "本周还没有新资料新动态", "课程资料，陆续更新", "从一个小小的想法开始", "暂时没有消息",
    # 登录页
    "好奇心，在这里相遇。", "欢迎回到课堂",
    # 热榜
    "想听热榜", "0123456789",
]

def main(src):
    out = Path(__file__).resolve().parent.parent / "static/board/fonts/cs-display.woff2"
    if src.endswith(".ttc"):
        fonts = TTCollection(src).fonts
        font = next(f for f in fonts if "SC" in f["name"].getDebugName(1))
    else:
        font = TTFont(src)
    text = "".join(DISPLAY_TEXT)
    opts = subset.Options(); opts.flavor = "woff2"; opts.layout_features = ["kern", "palt", "vert"]
    opts.name_IDs = ["*"]; opts.notdef_outline = True
    sub = subset.Subsetter(opts); sub.populate(text=text); sub.subset(font)
    font.flavor = "woff2"; font.save(out)
    print(out, out.stat().st_size, "bytes,", len(set(text)), "chars")

if __name__ == "__main__":
    main(sys.argv[1])
