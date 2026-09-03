from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_self_hosted_workflow_is_read_only_and_uses_dedicated_runner_labels():
    workflow = (ROOT / '.github/workflows/aie-v04-s1-self-hosted.yml').read_text(encoding='utf-8')
    assert 'contents: read' in workflow
    assert 'self-hosted' in workflow
    assert 'linux' in workflow
    assert 'x64' in workflow
    assert 'aie-interop' in workflow
    assert 'contents: write' not in workflow
    assert 'pull-requests: write' not in workflow
    assert 'preflight_external_host.sh' in workflow
    assert 'run_external_host.sh' in workflow
    assert 'actions/upload-artifact@v4' in workflow
    assert 'AIE_S1_1_PROMOTION.json' in workflow


def test_external_host_preflight_checks_privilege_network_tools_ports_and_workspace():
    script = (ROOT / 'interop/s1/scripts/preflight_external_host.sh').read_text(encoding='utf-8')
    for required in (
        'sudo -n true',
        'registry.npmjs.org',
        'github.com',
        'python3',
        'openssl',
        'runuser',
        'useradd',
        '18081',
        '18443',
        '18444',
        '19080',
        '19081',
        '3000',
        'preflight.json',
    ):
        assert required in script
    assert 'BLOCKED_EXTERNAL_RUNTIME' not in script


def test_external_host_wrapper_keeps_canonical_promotion_contract():
    script = (ROOT / 'interop/s1/scripts/run_external_host.sh').read_text(encoding='utf-8')
    assert 'preflight_external_host.sh' in script
    assert "python -m pip install -e '.[dev,otel]'" in script
    assert 'AIE_S1_PYTHON' in script
    assert 'AIE_S1_UV' in script
    assert 'AIE_S1_NPX' in script
    assert 'ci_external_s1.sh' in script
    assert 'AIE_S1_1_PROMOTION.json' in script
    assert 'promotion' in script
    assert 'PASS' in script


def test_blocked_github_hosted_external_probe_is_manual_only_until_runner_issue_is_resolved():
    workflow = (ROOT / '.github/workflows/aie-v04-s1-external-interop.yml').read_text(encoding='utf-8')
    assert 'workflow_dispatch:' in workflow
    assert '\n  push:\n' not in workflow
