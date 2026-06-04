import pathlib
import subprocess

from hermes_workflow.engine.graph import Identity
from hermes_workflow.worktree import provision_worktree, worktree_path


def _git(*a, cwd):
    subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True)


def _init_repo(tmp_path):
    repo = tmp_path / "repo"; repo.mkdir(); _git("init", cwd=repo)
    (repo / "f").write_text("x"); _git("add", "f", cwd=repo)
    _git("-c", "user.email=a@b.c", "-c", "user.name=a", "commit", "-m", "init", cwd=repo)
    return repo


def test_provision_is_idempotent(tmp_path):
    repo = _init_repo(tmp_path)
    ident = Identity("fix", 0, 0)
    p1 = provision_worktree("t_root", ident, str(repo), base_ref="HEAD")
    p2 = provision_worktree("t_root", ident, str(repo), base_ref="HEAD")  # reuse-if-exists
    assert p1 == p2 == str(worktree_path("t_root", ident, str(repo)))
    assert pathlib.Path(p1, ".git").exists()


def test_different_fan_index_yields_distinct_worktrees(tmp_path):
    repo = _init_repo(tmp_path)
    a = Identity("fix", 0, 0)
    b = Identity("fix", 1, 0)
    pa = provision_worktree("t_root", a, str(repo), base_ref="HEAD")
    pb = provision_worktree("t_root", b, str(repo), base_ref="HEAD")
    assert pa != pb
    assert pathlib.Path(pa, ".git").exists()
    assert pathlib.Path(pb, ".git").exists()
    # distinct, engine-derived branches per child
    branches = subprocess.run(
        ["git", "-C", str(repo), "branch", "--format=%(refname:short)"],
        check=True, capture_output=True, text=True,
    ).stdout.split()
    assert "wf/t_root/fix/0" in branches
    assert "wf/t_root/fix/1" in branches


def test_worktree_path_is_deterministic_and_pure(tmp_path):
    repo = _init_repo(tmp_path)
    ident = Identity("review", 2, 0)
    first = worktree_path("t_root", ident, str(repo))
    second = worktree_path("t_root", ident, str(repo))
    assert first == second                 # deterministic
    assert not first.exists()              # pure: no filesystem side effects
    assert first.parent.name == ".hermes-workflow-worktrees"
