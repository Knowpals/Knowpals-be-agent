from __future__ import annotations

from dataclasses import dataclass

from app.memory.memory import MemoryTool


@dataclass
class ChatMemoryWriteInput:
    student_id: str
    video_id: str
    user_text: str
    assistant_text: str


def write_chat_turns(memory: MemoryTool, inp: ChatMemoryWriteInput) -> None:
    memory.add_chat_turn(student_id=inp.student_id, role="student", text=inp.user_text, video_id=inp.video_id)
    memory.add_chat_turn(student_id=inp.student_id, role="assistant", text=inp.assistant_text, video_id=inp.video_id)

