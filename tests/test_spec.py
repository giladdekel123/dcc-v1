import copy

import pytest

from dcc_corpus import spec


@pytest.fixture(scope="module")
def loaded():
    return spec.load_spec()


def test_spec_is_consistent(loaded):
    assert spec.validate(*loaded) == []


def test_storyline_a_shape(loaded):
    _, timeline = loaded
    issues = [i for e in timeline["events"] for i in e.get("issue", [])]
    files = len(issues) + sum(len(i.get("copies", [])) for i in issues)
    assert len(timeline["documents"]) == 12
    assert len(issues) == 17
    assert files == 18
    formats = {spec.TEMPLATE_FORMATS[timeline["documents"][i["doc"]]["template"]] for i in issues}
    assert formats == {"pdf", "docx", "xlsx"}


def test_latest_is_not_the_construction_issue(loaded):
    _, timeline = loaded
    ga = [(e["date"], i["rev"], i["status"]) for e in timeline["events"] for i in e.get("issue", []) if i["doc"] == "GA"]
    latest = max(ga)
    latest_fc = max(r for r in ga if r[2] == "FC")
    assert (latest[1], latest_fc[1]) == ("P03", "C02")


@pytest.mark.parametrize("corrupt, expected", [
    (lambda t: t["links"].append({"from": "RFI12", "to": "GA@C09", "type": "affects"}), "unresolved target"),
    (lambda t: t["links"].append({"from": "GA", "to": "GA@C02", "type": "related_to"}), "self-link"),
    (lambda t: t["events"][0]["issue"][0].update(status="FC"), "not allowed"),
    (lambda t: t["documents"]["GA"].update(owner="Nobody"), "unknown owner"),
    (lambda t: t["events"][-1]["issue"][0].update(rev="C02"), "issued twice"),
])
def test_validation_catches_problems(loaded, corrupt, expected):
    project, timeline = loaded
    broken = copy.deepcopy(timeline)
    corrupt(broken)
    assert any(expected in e for e in spec.validate(project, broken))
