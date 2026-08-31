import subprocess

from scripts import validate_private_control_v31 as validator


def run(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def test_committed_tree_recurses_into_nested_git_trees(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    run(repo, "init", "-q")
    run(repo, "config", "user.name", "test")
    run(repo, "config", "user.email", "test@example.invalid")

    nested = repo / "control" / "missions"
    nested.mkdir(parents=True)
    (nested / "example.mission.json").write_text("{}\n", encoding="utf-8")
    (repo / "README.md").write_text("test\n", encoding="utf-8")
    run(repo, "add", ".")
    run(repo, "commit", "-q", "-m", "fixture")

    entries = validator.committed_tree(repo)

    assert "control/missions/example.mission.json" in entries
    assert entries["control/missions/example.mission.json"][0] == "100644"
    assert entries["control/missions/example.mission.json"][1] == "blob"
    assert "control" not in entries
    assert "control/missions" not in entries
