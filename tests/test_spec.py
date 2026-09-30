import copy
from collections import Counter

import pytest

from dcc_corpus import spec


@pytest.fixture(scope="module")
def loaded():
    return spec.load_spec()


def issues(timeline):
    return [i for e in timeline["events"] for i in e.get("issue", [])]


def test_spec_is_consistent(loaded):
    assert spec.validate(*loaded) == []


def test_corpus_shape(loaded):
    _, timeline = loaded
    assert [s["code"] for s in timeline["storylines"]] == list("ABCDEFGHIJK")
    assert Counter(d["storyline"] for d in timeline["documents"].values()) == {
        "A": 12, "B": 9, "C": 9, "D": 5, "E": 12,
        "F": 13, "G": 5, "H": 6, "I": 6, "J": 17, "K": 6}
    items = issues(timeline)
    files = len(items) + sum(len(i.get("copies", [])) for i in items)
    assert (len(timeline["documents"]), len(items), files) == (100, 120, 122)
    formats = {spec.TEMPLATE_FORMATS[timeline["documents"][i["doc"]]["template"]] for i in items}
    assert formats == {"pdf", "docx", "xlsx"}


def test_events_are_merged_in_date_order(loaded):
    _, timeline = loaded
    dates = [e["date"] for e in timeline["events"]]
    assert dates == sorted(dates)


def latest_and_construction(timeline, key, use_statuses):
    """Latest issued revision, and the latest whose final status is in use_statuses."""
    revs = {(e["date"], i["rev"]): i["status"] for e in timeline["events"] for i in e.get("issue", []) if i["doc"] == key}
    final = dict(revs)
    for e in timeline["events"]:
        for change in e.get("status_change", []):
            if change["doc"] == key:
                for k in final:
                    if k[1] == change["rev"]:
                        final[k] = change["status"]
    latest = max(revs)[1]
    usable = max(k for k, status in final.items() if status in use_statuses)[1]
    return latest, usable


def test_correct_is_not_the_latest(loaded):
    _, timeline = loaded
    assert latest_and_construction(timeline, "GA", {"FC"}) == ("P03", "C02")
    assert latest_and_construction(timeline, "FCD", {"AC", "AN"}) == ("P02", "P01")


def test_links_cross_storylines(loaded):
    _, timeline = loaded
    home = {k: d["storyline"] for k, d in timeline["documents"].items()}
    crossing = [l for l in timeline["links"]
                if home[spec.split_target(l["from"])[0]] != home[spec.split_target(l["to"])[0]]]
    assert crossing  # e.g. RFI-0013 generated_from meeting 7


def ga_p03(timeline):
    return next(i for e in timeline["events"] for i in e.get("issue", []) if i["doc"] == "GA" and i["rev"] == "P03")


@pytest.mark.parametrize("corrupt, expected", [
    (lambda t: t["links"].append({"from": "RFI12", "to": "GA@C09", "type": "affects"}), "unresolved target"),
    (lambda t: t["links"].append({"from": "GA", "to": "GA@C02", "type": "related_to"}), "self-link"),
    (lambda t: t["events"][0]["issue"][0].update(status="FC"), "not allowed"),
    (lambda t: t["documents"]["GA"].update(owner="Nobody"), "unknown owner"),
    (lambda t: ga_p03(t).update(rev="C02"), "issued twice"),
    (lambda t: t["documents"]["MM07"].update(also_in=["Z"]), "not another known storyline"),
    (lambda t: ga_p03(t)["content"]["geometry"].update(kind="spiral"), "unknown drawing geometry"),
    (lambda t: t["duplicates"].append("GA"), "more than one storyline"),
])
def test_validation_catches_problems(loaded, corrupt, expected):
    project, timeline = loaded
    broken = copy.deepcopy(timeline)
    corrupt(broken)
    assert any(expected in e for e in spec.validate(project, broken))
