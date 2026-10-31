from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


class TestCIReport(unittest.TestCase):
    def test_relatorio_preserva_erro_e_codigo_de_saida(self):
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            tests = work / "cases"
            tests.mkdir()
            (tests / "test_example.py").write_text(
                'import unittest\nclass Example(unittest.TestCase):\n def test_ok(self): pass\n def test_error(self): raise RuntimeError("diagnostico Windows")\n def test_sub(self):\n  with self.subTest(item=1): self.assertEqual(1,2)\n',
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools/run_tests.py"),
                    "--start",
                    str(tests),
                    "--output",
                    str(work / "results"),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 1)
            report = ET.parse(work / "results/junit.xml").getroot()
            self.assertEqual(report.attrib["errors"], "1")
            self.assertEqual(report.attrib["failures"], "1")
            text = (work / "results/unittest.log").read_text(encoding="utf-8")
            self.assertIn("RuntimeError: diagnostico Windows", text)
            self.assertIn("Traceback", text)
