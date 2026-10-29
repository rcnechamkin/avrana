"""Static checks on the GitHub Actions workflows (decision D-8).

The workflow is read as text, comments are removed, and the rest is matched (standard library only). It is
also parsed as YAML when PyYAML is installed, which CI requires (AVRANA_REQUIRE_YAML=1): from 2026-10-14 to
2026-10-27 the text checks passed while GitHub rejected the file as invalid YAML.
Nothing here runs a workflow or contacts GitHub.
"""
from pathlib import Path
import os
import re
import unittest

try:
    import yaml
except ImportError:  # the parse test reports NOT RUN, or fails when AVRANA_REQUIRE_YAML=1
    yaml = None

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / '.github' / 'workflows'
MAIN = WORKFLOWS / 'offline-tests.yml'
REQUIREMENTS = ROOT / '.github' / 'requirements-ci.txt'
HOME_LOCK = ROOT / 'services' / 'avrana-home' / 'requirements.lock'
INSTALL_COMMAND = ('python -m pip install --disable-pip-version-check --no-cache-dir --no-deps '
                   '--only-binary=:all: --require-hashes -r .github/requirements-ci.txt')
INSTALL = f"run: '{INSTALL_COMMAND}'"   # quoted: the command holds ": ", which ends a plain YAML scalar


def code_of(path):
    """The file without comments or blank lines, so prose in a comment cannot trip or hide a check."""
    lines = []
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = re.sub(r'\s+#.*$', '', raw)
        if line.strip() and not line.lstrip().startswith('#'):
            lines.append(line)
    return '\n'.join(lines)


class EveryWorkflowTests(unittest.TestCase):
    def workflows(self):
        found = sorted(WORKFLOWS.glob('*.y*ml'))
        self.assertIn(MAIN, found)
        return found

    def test_no_secrets_and_no_privileged_triggers(self):
        for path in self.workflows():
            code = code_of(path)
            with self.subTest(workflow=path.name):
                self.assertNotIn('secrets.', code)
                self.assertNotRegex(code, r'(?i)\bsecrets\s*:')
                self.assertNotRegex(code, r'(?i)\binherit\b')
                self.assertNotIn('pull_request_target', code)
                self.assertNotIn('workflow_run', code)

    def test_permissions_are_read_only(self):
        for path in self.workflows():
            code = code_of(path)
            with self.subTest(workflow=path.name):
                self.assertRegex(code, r'(?m)^permissions:\n  contents: read\n(?!  )')
                self.assertNotRegex(code, r'(?i):\s*write\b')
                self.assertNotIn('write-all', code)

    def test_no_line_endings_surprise(self):
        for path in self.workflows():
            self.assertNotIn(b'\r', path.read_bytes(), path.name)

    def test_plain_run_values_are_valid_yaml_scalars(self):
        """Standard library: a one-line `run:` value that is not quoted or a block scalar may not hold ": " or
        " #" (YAML reads a mapping or a comment there), and may not start with a YAML indicator."""
        for path in self.workflows():
            for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                match = re.match(r'\s*(?:- )?run: (.*)$', line)
                if not match or match.group(1)[:1] in ("'", '"', '|', '>'):
                    continue
                with self.subTest(workflow=path.name, line=number):
                    self.assertNotIn(': ', match.group(1))
                    self.assertNotIn(' #', match.group(1))
                    self.assertNotRegex(match.group(1), r'^[-?:,\[\]{}&*!%@`]')


@unittest.skipIf(yaml is None and os.environ.get('AVRANA_REQUIRE_YAML', '') in ('', '0'),
                 'PyYAML missing: workflow YAML parse NOT RUN (AVRANA_REQUIRE_YAML=1 makes this fail)')
class WorkflowParsesTests(unittest.TestCase):
    def test_every_workflow_parses_and_the_install_step_is_the_reviewed_command(self):
        self.assertIsNotNone(yaml, 'PyYAML is required here (AVRANA_REQUIRE_YAML=1)')
        for path in sorted(WORKFLOWS.glob('*.y*ml')):
            with self.subTest(workflow=path.name):
                doc = yaml.safe_load(path.read_text(encoding='utf-8'))
                self.assertIsInstance(doc, dict)
                self.assertIsInstance(doc.get('jobs'), dict)
                for job in doc['jobs'].values():
                    self.assertIsInstance(job.get('steps'), list)
        doc = yaml.safe_load(MAIN.read_text(encoding='utf-8'))
        self.assertEqual(set(doc['jobs']), {'offline-tests', 'content-gate'})
        runs = [step.get('run') for step in doc['jobs']['offline-tests']['steps']]
        self.assertIn(INSTALL_COMMAND, runs)
        self.assertIn('python -B tests/run_offline.py', runs)


class OfflineTestsWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.code = code_of(MAIN)

    def test_triggers_are_pull_request_and_push_to_main_only(self):
        self.assertRegex(self.code, r'(?m)^on:\n  pull_request:\n  push:\n    branches: \[main\]\n')
        for other in ('schedule', 'workflow_dispatch', 'issue_comment', 'release', 'repository_dispatch'):
            self.assertNotRegex(self.code, rf'(?m)^  {other}:')

    def test_runs_the_offline_suite_and_the_content_gate(self):
        self.assertIn('python -B tests/run_offline.py', self.code)
        self.assertIn('python -B scripts/review_git_content.py --staged', self.code)

    def test_networking_is_removed_for_a_second_run(self):
        self.assertRegex(self.code, r'unshare --net')
        self.assertEqual(2, self.code.count('python -B tests/run_offline.py'))

    def test_no_deploy_ssh_or_remote_access_steps(self):
        banned = (r'ssh', r'scp', r'sftp', r'rsync', r'docker', r'kubectl', r'helm', r'terraform', r'ansible',
                  r'deploy\w*', r'rclone', r'curl', r'wget', r'npm', r'gh', r'git push', r'git remote')
        for word in banned:
            with self.subTest(word=word):
                self.assertNotRegex(self.code, rf'(?i)(?<![\w-]){word}(?![\w-])')
        self.assertNotRegex(self.code, r'(?m)^\s*environment:')
        self.assertNotRegex(self.code, r'(?m)^\s*(?:id-token|packages|deployments|actions):')

    def test_only_the_d8a_hash_pinned_install_uses_pip(self):
        """D-8a (owner, 2026-10-14), extended by D-8b (2026-10-26): one pip call, hash-pinned, binary-only,
        no dependencies, in the offline-tests job before the suites run. Nothing else may install or fetch
        a package."""
        pip_lines = [l.strip() for l in self.code.splitlines()
                     if re.search(r'(?i)(?<![\w-])pip\d*(?![\w-])|PIP_', l)]
        self.assertEqual(pip_lines, [INSTALL])
        offline_job = self.code.split('\n  offline-tests:\n', 1)[1].split('\n  content-gate:\n', 1)
        self.assertIn(INSTALL, offline_job[0])
        self.assertNotIn('pip', offline_job[1])
        self.assertLess(offline_job[0].index(INSTALL), offline_job[0].index('python -B tests/run_offline.py'))
        for other in ('pipx', 'poetry', 'uv ', 'conda', 'easy_install', 'setup.py'):
            self.assertNotIn(other, self.code)

    def test_requirements_are_the_reviewed_hash_pinned_set(self):
        """D-8a (PyYAML) and D-8b (owner, 2026-10-26, AVR-757: web and connector test dependencies).
        Every line is one exact pin with one sha256, or the single include of the avrana-home lock,
        whose entries are held to the same rule. Adding a package means changing this list. Pillow: owner,
        2026-10-28 (Me -> My profile photos, avatar.py)."""
        lines = [l.strip() for l in REQUIREMENTS.read_text(encoding='utf-8').splitlines()
                 if l.strip() and not l.lstrip().startswith('#')]
        self.assertNotIn(b'\r', REQUIREMENTS.read_bytes())
        self.assertEqual(lines.count('-r ../services/avrana-home/requirements.lock'), 1)
        pinned = [l for l in lines if l != '-r ../services/avrana-home/requirements.lock']
        for line in pinned:
            self.assertRegex(line, r'^[A-Za-z0-9_.-]+==[\w.]+ --hash=sha256:[0-9a-f]{64}$')
        names = {l.split('==', 1)[0].lower() for l in pinned}
        self.assertEqual(names, {'pyyaml', 'itsdangerous', 'python-multipart', 'pytest', 'iniconfig',
                                 'packaging', 'pluggy', 'pygments'})
        self.assertNotIn(b'\r', HOME_LOCK.read_bytes())
        lock = HOME_LOCK.read_text(encoding='utf-8')
        entries = [e.strip() for e in re.sub(r'\s*\\\n\s*', ' ', lock).splitlines()
                   if e.strip() and not e.lstrip().startswith('#')]
        for entry in entries:
            self.assertRegex(entry, r'^[A-Za-z0-9_.-]+==[\w.]+( --hash=sha256:[0-9a-f]{64})+$')
        locked = {e.split('==', 1)[0].lower() for e in entries}
        self.assertEqual(locked, {'annotated-types', 'anyio', 'certifi', 'click', 'fastapi', 'h11', 'httpcore',
                                  'httpx', 'idna', 'jinja2', 'markupsafe', 'pillow', 'pydantic', 'pydantic-core',
                                  'starlette', 'typing-extensions', 'typing-inspection', 'uvicorn'})
        self.assertFalse(names & locked, 'a package pinned twice')

    def test_missing_pyyaml_fails_both_runs(self):
        self.assertRegex(self.code, r'(?m)^env:\n(?:  .*\n)*  AVRANA_REQUIRE_YAML: "1"\n')
        # Exactly these two settings: a job- or step-level override (for example "0") would also match above.
        self.assertEqual(self.code.count('AVRANA_REQUIRE_YAML'), 2)
        # sudo resets the environment, so the no-network run must pass the variable itself.
        self.assertRegex(self.code, r'sudo env "PATH=\$PATH" AVRANA_REQUIRE_YAML=1 unshare --net')

    def test_every_action_is_pinned_to_a_full_commit_sha(self):
        uses = re.findall(r'(?m)^\s*-?\s*uses:\s*(\S+)', self.code)
        self.assertTrue(uses)
        for value in uses:
            with self.subTest(uses=value):
                self.assertRegex(value, r'^[\w.-]+/[\w./-]+@[0-9a-f]{40}$')

    def test_runner_python_timeout_and_concurrency(self):
        section = self.code.split('\njobs:\n', 1)[1]
        jobs = re.findall(r'(?m)^  [\w-]+:\n(?:    .*\n?)+', section + '\n')
        self.assertEqual(2, len(jobs))
        for job in jobs:
            self.assertIn('runs-on: ubuntu-latest', job)
            self.assertRegex(job, r'timeout-minutes: \d+')
            self.assertIn('python-version: "3.12"', job)
            self.assertIn('persist-credentials: false', job)
        self.assertRegex(self.code, r'(?m)^concurrency:\n  group: .+\n  cancel-in-progress: true\n')


if __name__ == '__main__':
    unittest.main()
