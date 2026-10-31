"""Executa unittest preservando falhas e produzindo log+JUnit para a CI."""

import argparse
from pathlib import Path
import sys
import time
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, text):
        for stream in self.streams:
            stream.write(text)

    def flush(self):
        for stream in self.streams:
            stream.flush()


class ReportResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cases = []

    def startTest(self, test):
        self.started = time.perf_counter()
        super().startTest(test)

    def addSuccess(self, test):
        super().addSuccess(test)
        self.cases.append(
            (test.id(), "success", "", time.perf_counter() - self.started)
        )

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.cases.append(
            (
                test.id(),
                "failure",
                self._exc_info_to_string(err, test),
                time.perf_counter() - self.started,
            )
        )

    def addError(self, test, err):
        super().addError(test, err)
        self.cases.append(
            (
                test.id(),
                "error",
                self._exc_info_to_string(err, test),
                time.perf_counter() - self.started,
            )
        )

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.cases.append((test.id(), "skipped", reason, 0))

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            kind = "failure" if issubclass(err[0], test.failureException) else "error"
            self.cases.append(
                (
                    subtest.id(),
                    kind,
                    self._exc_info_to_string(err, test),
                    time.perf_counter() - self.started,
                )
            )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default=".")
    parser.add_argument("--output", default="test-results")
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    suite = unittest.defaultTestLoader.discover(args.start)
    with (out / "unittest.log").open("w", encoding="utf-8") as file:
        result = unittest.TextTestRunner(
            stream=Tee(sys.stderr, file), verbosity=2, resultclass=ReportResult
        ).run(suite)
    root = ET.Element(
        "testsuite",
        tests=str(result.testsRun),
        failures=str(len(result.failures)),
        errors=str(len(result.errors)),
        skipped=str(len(result.skipped)),
    )
    for name, kind, message, elapsed in result.cases:
        node = ET.SubElement(root, "testcase", name=name, time=f"{elapsed:.6f}")
        if kind != "success":
            ET.SubElement(
                node, kind, message=message.splitlines()[-1] if message else ""
            ).text = message
    ET.ElementTree(root).write(
        out / "junit.xml", encoding="utf-8", xml_declaration=True
    )
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
