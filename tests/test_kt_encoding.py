"""编码探测与安全写回的回归测试（只依赖标准库）。

运行：python -m unittest discover -s tests -v
"""

import importlib.util
import os
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_agent():
    spec = importlib.util.spec_from_file_location(
        "gurouxianglian_agent", os.path.join(ROOT, "gurouxianglian_agent.pyw")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


agent = load_agent()


class EncodingTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)

    def write(self, name, data):
        path = os.path.join(self._dir.name, name)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def read(self, path):
        with open(path, "rb") as f:
            return f.read()

    def test_gbk_file_round_trip_keeps_bytes(self):
        """GBK 文件改动后必须仍以 GBK 写回，中文不能被替换成 U+FFFD。"""
        path = self.write("gbk.txt", "hello 中文内容\r\n".encode("gbk"))
        text, enc = agent.read_text(path)
        self.assertEqual(text, "hello 中文内容\r\n")
        self.assertEqual(enc, "gb18030")

        result = agent.kt_edit(path, "hello", "hi")
        self.assertIn("[成功]", result)
        self.assertEqual(self.read(path), "hi 中文内容\r\n".encode("gbk"))

    def test_gbk_chinese_can_be_replaced(self):
        """GBK 文件里的中文必须能被匹配替换，而不是报“未找到目标字符串”。"""
        path = self.write("config.txt", "状态=开启\r\n".encode("gbk"))
        result = agent.kt_edit(path, "开启", "关闭")
        self.assertIn("[成功]", result)
        self.assertEqual(self.read(path), "状态=关闭\r\n".encode("gbk"))

    def test_utf8_bom_is_preserved(self):
        path = self.write("bom.txt", b"\xef\xbb\xbfhello\r\n")
        text, enc = agent.read_text(path)
        self.assertEqual((text, enc), ("hello\r\n", "utf-8-sig"))
        agent.kt_edit(path, "hello", "hi")
        self.assertEqual(self.read(path), b"\xef\xbb\xbfhi\r\n")

    def test_undecodable_file_is_rejected_instead_of_rewritten(self):
        """无法判定编码时应抛错并保留原文件，不能带着替换字符写回。"""
        path = self.write("broken.bin", b"\xff\xff\xff\xff")
        with self.assertRaises(ValueError):
            agent.read_text(path)
        self.assertEqual(self.read(path), b"\xff\xff\xff\xff")


if __name__ == "__main__":
    unittest.main()
