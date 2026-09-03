from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_declares_modern_distribution_metadata():
    data = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
    build_requires = data['build-system']['requires']
    assert any(req.startswith('setuptools>=77.0.3') for req in build_requires)

    project = data['project']
    assert project['readme'] == 'README.md'
    assert project['license'] == 'Apache-2.0'
    assert project['license-files'] == ['LICENSE']
    assert project['authors'] == [{'name': 'Jonas Abde'}]
    assert {'ai-agents', 'authorization', 'governance', 'interoperability'} <= set(project['keywords'])
    assert project['urls']['Repository'] == 'https://github.com/JonasAbde/aie'
    assert project['urls']['Issues'] == 'https://github.com/JonasAbde/aie/issues'
    assert project['urls']['Changelog'].endswith('/blob/main/CHANGELOG.md')
