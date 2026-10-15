"""Static checks on the GitHub Actions workflows (decision D-8).

Standard library only: the workflow is read as text, comments are removed, and the rest is matched.
Nothing here runs a workflow or contacts GitHub.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / '.github' / 'workflows'
MAIN = WORKFLOWS / 'offline-tests.yml'
REQUIREMENTS = ROOT / '.github' / 'requirements-ci.txt'
INSTALL = ('run: python -m pip install --disable-pip-version-check --no-cache-dir --no-deps '
           '--only-binary=:all: --require-hashes -r .github/requirements-ci.txt')


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
        """D-8a (owner, 2026-10-14): one pip call, hash-pinned, binary-only, no dependencies, in the
        offline-tests job before the suites run. Nothing else may install or fetch a package."""
        pip_lines = [l.strip() for l in self.code.splitlines() if re.search(r'(?<![\w-])pip(?![\w-])', l)]
        self.assertEqual(pip_lines, [INSTALL])
        offline_job = self.code.split('\n  offline-tests:\n', 1)[1].split('\n  content-gate:\n', 1)
        self.assertIn(INSTALL, offline_job[0])
        self.assertNotIn('pip', offline_job[1])
        self.assertLess(offline_job[0].index(INSTALL), offline_job[0].index('python -B tests/run_offline.py'))
        for other in ('pipx', 'poetry', 'uv ', 'conda', 'easy_install', 'setup.py'):
            self.assertNotIn(other, self.code)

    def test_requirements_file_is_one_hash_pinned_pyyaml(self):
        lines = [l.strip() for l in REQUIREMENTS.read_text(encoding='utf-8').splitlines()
                 if l.strip() and not l.lstrip().startswith('#')]
        self.assertEqual(len(lines), 1)
        self.assertRegex(lines[0], r'^PyYAML==\d+\.\d+\.\d+ --hash=sha256:[0-9a-f]{64}$')
        self.assertNotIn(b'\r', REQUIREMENTS.read_bytes())

    def test_missing_pyyaml_fails_both_runs(self):
        self.assertRegex(self.code, r'(?m)^env:\n(?:  .*\n)*  AVRANA_REQUIRE_YAML: "1"\n')
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
