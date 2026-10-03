# -*- coding: utf-8 -*-
"""
生成音频工坊的演示素材库 material_lib/（edge-tts，需联网）
运行：py make_materials.py
"""
import asyncio
import os


def material_lib():
    lib = [
        # (文件名, 音色, 文本)
        ("mat01_xiaoxiao_intro.mp3", "zh-CN-XiaoxiaoNeural", "北京欢迎你，为你开天辟地。"),
        ("mat02_xiaoyi_happy.mp3", "zh-CN-XiaoyiNeural", "哇！今天天气真好呀，我们去公园玩吧！"),
        ("mat03_xiaoyi_coax.mp3", "zh-CN-XiaoyiNeural", "人家想要你陪我嘛～好不好嘛～"),
        ("mat04_yunxi_news.mp3", "zh-CN-YunxiNeural", "各位观众，晚上好，欢迎收看今天的新闻。"),
        ("mat05_yunjian_deep.mp3", "zh-CN-YunjianNeural", "好了，这件事就这么定了。"),
        ("mat06_xiaoxiao_soft.mp3", "zh-CN-XiaoxiaoNeural", "晚安，做个好梦。"),
        ("mat07_yunxi_navi.mp3", "zh-CN-YunxiNeural", "前方五百米右转，然后直行两百米。"),
        ("mat08_xiaoxiao_question.mp3", "zh-CN-XiaoxiaoNeural", "你真的要走了吗？"),
    ]
    os.makedirs("material_lib", exist_ok=True)

    async def gen(name, voice, text):
        import edge_tts
        await edge_tts.Communicate(text, voice).save(
            os.path.join("material_lib", name))

    for name, voice, text in lib:
        try:
            asyncio.run(gen(name, voice, text))
            print(f"[OK] {name}  <-  {text}")
        except Exception as e:
            print(f"[失败] {name}: {e}")

    desc = [
        ("文件", "音色", "内容", "适合测什么"),
        *[(n, v.split("-")[2].replace("Neural", ""), t, hint)
          for (n, v, t), hint in zip(
              lib,
              ("开场/通用", "活泼语气→可爱/快",
               "撒娇语气→音调略高/柔媚", "沉稳/混响",
               "低沉/怪兽", "温柔/慢", "快/加速", "句尾上扬→疑问"))],
    ]
    with open("material_lib/素材清单.txt", "w", encoding="utf-8") as f:
        for row in desc:
            f.write("\t".join(row) + "\n")
    print("\n素材清单 → material_lib/素材清单.txt")
    print("另有音效素材：demo_wavs/（风声/光剑/警报等，素材模式同样可以改方向）")


if __name__ == "__main__":
    material_lib()