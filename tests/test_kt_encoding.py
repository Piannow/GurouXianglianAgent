"""kt 工具编码回归测试：确保非 UTF-8 文件不会被破坏性改写。

运行：python -m unittest discover -s tests -v
"""
import importlib.util
import os
import shutil
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_agent():
    loader = SourceFileLoader("gurou_agent", os.path.join(ROOT, "gurouxianglian_agent.pyw"))
    spec = importlib.util.spec_from_loader("gurou_agent", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


agent = _load_agent()


class KtEncodingTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kt_enc_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, name, data):
        path = os.path.join(self.tmp, name)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def _read(self, path):
        with open(path, "rb") as f:
            return f.read()

    def test_gbk_detected_as_gb18030(self):
        raw = "中文内容".encode("gbk")
        self.assertIn(agent._detect_encoding(raw), ("gb18030", "gbk"))

    def test_gbk_round_trip_keeps_bytes(self):
        raw = "hello 中文内容\r\n".encode("gbk")
        path = self._write("round_trip.txt", raw)
        text, enc = agent.read_text(path)
        self.assertEqual(text, "hello 中文内容\r\n")
        agent.write_text(path, text, enc)
        self.assertEqual(self._read(path), raw)

    def test_gbk_chinese_can_be_replaced(self):
        raw = "hello 中文内容\r\n".encode("gbk")
        path = self._write("edit.txt", raw)
        result = agent.kt_edit(path, "hello", "hi", backup_dir=self.tmp)
        self.assertIn("[成功]", result)
        self.assertEqual(self._read(path), "hi 中文内容\r\n".encode("gbk"))

    def test_gbk_chinese_old_string_matches(self):
        raw = "前缀 中文 后缀\r\n".encode("gbk")
        path = self._write("cn_edit.txt", raw)
        result = agent.kt_edit(path, "中文", "汉字", backup_dir=self.tmp)
        self.assertIn("[成功]", result)
        self.assertEqual(self._read(path), "前缀 汉字 后缀\r\n".encode("gbk"))

    def test_utf8_bom_is_preserved(self):
        raw = "\ufeff中文内容\r\n".encode("utf-8")
        path = self._write("bom.txt", raw)
        text, enc = agent.read_text(path)
        self.assertEqual(enc, "utf-8-sig")
        agent.write_text(path, text, enc)
        self.assertEqual(self._read(path), raw)

    def test_undecodable_file_is_rejected(self):
        path = self._write("bad.txt", b"abc\xff\xff\r\n")
        with self.assertRaises(ValueError):
            agent.read_text(path)
        # kt_edit / kt_write 都不应改动文件
        before = self._read(path)
        self.assertIn("[错误]", agent.kt_edit(path, "abc", "x", backup_dir=self.tmp))
        self.assertIn("[错误]", agent.kt_write(path, "new content", backup_dir=self.tmp))
        self.assertEqual(self._read(path), before)


if __name__ == "__main__":
    unittest.main()
