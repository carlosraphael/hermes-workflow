"""No-LLM board harness: create/complete/link/archive/status via kb.* on a temp board."""


class Board:
    """Thin no-LLM wrapper over hermes_cli.kanban_db for tests.

    Contract: create_task is keyword-only after conn; complete_task is
    keyword-only after task_id; get_task returns a Task OBJECT, so status
    uses attribute access (.status), not ["status"].
    """

    def __init__(self, kb, conn, name):
        self.kb, self.conn, self.name = kb, conn, name

    def create(self, title, parents=(), assignee="_workflow_root",
               workspace_kind="scratch", workspace_path=None, body="",
               skills=None, idempotency_key=None):
        return self.kb.create_task(self.conn, title=title, body=body, assignee=assignee,
                                   parents=tuple(parents), workspace_kind=workspace_kind,
                                   workspace_path=workspace_path, skills=skills,
                                   idempotency_key=idempotency_key, board=self.name)

    def complete(self, tid, summary="done", metadata=None):
        return self.kb.complete_task(self.conn, tid, summary=summary, metadata=metadata or {})

    def link(self, parent, child):
        return self.kb.link_tasks(self.conn, parent_id=parent, child_id=child)

    def archive(self, tid):
        return self.kb.archive_task(self.conn, tid)

    def status(self, tid):
        return self.kb.get_task(self.conn, tid).status  # ATTRIBUTE access, not ["status"]
