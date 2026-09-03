from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_dependabot_monitors_python_and_github_actions_weekly_without_auto_merge_policy():
    path = ROOT / '.github/dependabot.yml'
    data = yaml.safe_load(path.read_text(encoding='utf-8'))
    assert data['version'] == 2
    updates = {item['package-ecosystem']: item for item in data['updates']}
    assert set(updates) == {'pip', 'github-actions'}
    for ecosystem, item in updates.items():
        assert item['directory'] == '/'
        assert item['schedule']['interval'] == 'weekly'
        assert item['schedule']['day'] == 'monday'
        assert item['schedule']['timezone'] == 'Europe/Copenhagen'
        assert item['open-pull-requests-limit'] <= 5
        groups = item['groups']
        assert len(groups) == 1
        group = next(iter(groups.values()))
        assert group['patterns'] == ['*']
        assert set(group['update-types']) == {'minor', 'patch'}
        assert 'automerge' not in repr(item).lower()
