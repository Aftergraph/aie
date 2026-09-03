import json
from pathlib import Path

import jsonschema
import yaml


def test_reference_manifest_validates_against_draft_03_schema():
    root = Path(__file__).parent.parent / "spec"
    schema = json.loads((root / "AIE_Draft_0.3_Schema.json").read_text())
    manifest = yaml.safe_load((root / "AIE_Draft_0.3_Reference.yaml").read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(manifest, schema)
