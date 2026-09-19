"""Construct conversation records without performing I/O."""

from researchflow.storage import now


def message(state, sender, receiver, content, task_id, refs=None):
    return {
        "id": f"{task_id}:{sender}:{receiver}",
        "task_id": task_id,
        "sender": sender,
        "receiver": receiver,
        "content": content,
        "refs": refs or [],
        "time": now(),
    }


def result_message(state, role, content, refs):
    return state["messages"] + [
        message(state, role, "调度 Agent", content, state["task"]["id"], refs)
    ]
