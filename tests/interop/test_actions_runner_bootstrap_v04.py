from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = ROOT / 'interop/s1/scripts/bootstrap_actions_runner.sh'
REMOVE = ROOT / 'interop/s1/scripts/remove_actions_runner.sh'
VERSIONS = ROOT / 'interop/s1/versions.env'
RUNBOOK = ROOT / 'docs/s1-self-hosted-runner.md'


def test_bootstrap_pins_official_runner_release_and_verifies_linux_x64_checksum():
    versions = VERSIONS.read_text(encoding='utf-8')
    script = BOOTSTRAP.read_text(encoding='utf-8')
    assert 'GITHUB_ACTIONS_RUNNER_VERSION=2.337.0' in versions
    assert 'GITHUB_ACTIONS_RUNNER_LINUX_X64_SHA256=70920811a4f8ad4328818682bca5c6469c1c942fab52448868071d0063816613' in versions
    assert 'actions-runner-linux-x64-${GITHUB_ACTIONS_RUNNER_VERSION}.tar.gz' in script
    assert 'sha256sum -c -' in script
    assert 'github.com/actions/runner/releases/download/v${GITHUB_ACTIONS_RUNNER_VERSION}' in script


def test_bootstrap_uses_dedicated_non_root_user_and_expected_repo_labels_and_service():
    script = BOOTSTRAP.read_text(encoding='utf-8')
    for required in (
        'RUNNER_USER=${AIE_RUNNER_USER:-aie-runner}',
        'https://github.com/JonasAbde/aie',
        '--labels',
        'aie-interop',
        'useradd',
        'runuser -u "$RUNNER_USER"',
        './config.sh',
        './svc.sh install "$RUNNER_USER"',
        './svc.sh start',
        'bin/installdependencies.sh',
        'preflight_external_host.sh',
    ):
        assert required in script
    assert 'RUNNER_ALLOW_RUNASROOT' not in script


def test_bootstrap_requires_short_lived_token_without_logging_or_persisting_it():
    script = BOOTSTRAP.read_text(encoding='utf-8')
    assert 'AIE_RUNNER_REGISTRATION_TOKEN' in script
    assert '--token "$AIE_RUNNER_REGISTRATION_TOKEN"' in script
    assert 'unset AIE_RUNNER_REGISTRATION_TOKEN' in script
    assert 'set -x' not in script
    assert 'echo "$AIE_RUNNER_REGISTRATION_TOKEN"' not in script
    assert 'printf "$AIE_RUNNER_REGISTRATION_TOKEN"' not in script


def test_bootstrap_requires_explicit_dedicated_host_sudo_opt_in_and_hardens_sudoers_file():
    script = BOOTSTRAP.read_text(encoding='utf-8')
    assert 'AIE_RUNNER_ENABLE_LAB_SUDO' in script
    assert 'dedicated' in script.lower()
    assert '/etc/sudoers.d/aie-interop-runner' in script
    assert 'NOPASSWD: ALL' in script
    assert 'chmod 0440' in script
    assert 'visudo -cf' in script


def test_remove_script_requires_separate_removal_token_stops_service_and_deregisters():
    script = REMOVE.read_text(encoding='utf-8')
    for required in (
        'AIE_RUNNER_REMOVAL_TOKEN',
        './svc.sh stop',
        './svc.sh uninstall',
        './config.sh remove',
        '--token "$AIE_RUNNER_REMOVAL_TOKEN"',
        'unset AIE_RUNNER_REMOVAL_TOKEN',
    ):
        assert required in script
    assert 'set -x' not in script
    assert 'rm -rf "$RUNNER_HOME"' not in script


def test_runbook_explains_one_hour_token_boundary_and_public_repo_runner_risk():
    doc = RUNBOOK.read_text(encoding='utf-8')
    assert 'one hour' in doc.lower()
    assert 'public repository' in doc.lower()
    assert 'dedicated or ephemeral' in doc.lower()
    assert 'AIE_RUNNER_REGISTRATION_TOKEN' in doc
    assert 'AIE_RUNNER_REMOVAL_TOKEN' in doc
    assert 'v2.337.0' in doc


def test_pinned_runner_disables_automatic_updates_and_documents_manual_upgrade_ownership():
    script = BOOTSTRAP.read_text(encoding='utf-8')
    doc = RUNBOOK.read_text(encoding='utf-8')
    assert '--disableupdate' in script
    assert 'automatic updates' in doc.lower()
    assert 'manual' in doc.lower()


def test_bootstrap_rolls_back_privileged_sudoers_grant_on_incomplete_installation():
    script = BOOTSTRAP.read_text(encoding='utf-8')
    assert 'BOOTSTRAP_COMPLETE=0' in script
    assert 'rollback_privilege' in script
    assert 'rm -f "$SUDOERS_FILE"' in script
    assert 'trap cleanup EXIT' in script
    assert 'BOOTSTRAP_COMPLETE=1' in script


def test_removal_revokes_sudoers_grant_even_when_github_deregistration_fails():
    script = REMOVE.read_text(encoding='utf-8')
    assert 'cleanup_privilege' in script
    assert 'trap cleanup_privilege EXIT' in script
    assert 'rm -f "$SUDOERS_FILE"' in script
