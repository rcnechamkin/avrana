#!/usr/bin/env python3
"""Run only explicitly selected stdlib tests; never discover live service tests."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def yaml_guard():
    """The G1 compose and bypass-path tests need PyYAML and skip without it (AVR-386). Say so loudly,
    and fail when AVRANA_REQUIRE_YAML=1 so a gate that relies on them cannot pass by skipping."""
    if importlib.util.find_spec('yaml') is not None:
        return
    message = 'PyYAML not importable: G1 compose-declaration and bypass-path tests will be SKIPPED'
    if os.environ.get('AVRANA_REQUIRE_YAML') == '1':
        sys.exit(f'FAIL {message} (AVRANA_REQUIRE_YAML=1)')
    print(f'WARN {message}', file=sys.stderr)


def main():
    yaml_guard()
    subprocess.run([sys.executable, '-B', '-m', 'unittest', 'discover', '-s', str(ROOT / 'tests'), '-p', 'test_*.py'], check=True)
    subprocess.run([sys.executable, '-B', str(ROOT / 'services/avrana-imax-verify/tests/test_classify.py')], check=True)
    path = ROOT / 'services/avrana-kindle-connector/tests/test_kindle.py'
    spec = importlib.util.spec_from_file_location('kindle_tests', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # The production test file also holds live gating checks that start containers through
    # Docker (anything using its curl() helper). Those are never run from here.
    import inspect
    tests = [(name, value) for name, value in vars(module).items()
             if name.startswith('test_') and callable(value) and 'curl(' not in inspect.getsource(value)]
    for name, test in tests:
        test()
        print('PASS', name)
    print(f'{len(tests)} offline Kindle tests passed')
    subprocess.run([sys.executable, '-B', '-m', 'unittest', 'discover', '-s', str(ROOT / 'services/avrana-kindle-connector/tests'), '-p', 'test_authz.py'], check=True)
    subprocess.run([sys.executable, '-B', '-m', 'unittest', 'discover', '-s', str(ROOT / 'services/backups/tests'), '-p', 'test_*.py'], check=True)
    subprocess.run([sys.executable, '-B', '-m', 'unittest', 'discover', '-s', str(ROOT / 'services/avrana-assistant/tests'), '-p', 'test_*.py'], check=True)
    home = ROOT / 'services/avrana-home'
    subprocess.run([sys.executable, '-B', '-m', 'unittest', 'discover', '-s', str(home / 'tests'),
                    '-t', str(home), '-p', 'test_*.py'], check=True)


if __name__ == '__main__':
    main()
