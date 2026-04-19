#从kafka中接收消息的结构
class TaskMessage:
    def __init__(self, data):
        self.job_id = data['job_id']
        self.stage=data['stage']
        self.payload = data['payload']
        self.retry = data.get('retry', 0)

class ResultMessage:
    def __init__(self, job_id,stage,status,result=None,error=None):
        self.data={
            "job_id": job_id,
            "stage": stage,
            "status": status,
            "result": result,
            "error": error
        }

class MemoryEventMessage:
    def __init__(self,data):
        self.data={}

Event = {
    "type": str,              # question | pause | replay | chat
    "student_id": str,
    "knowledge_id": str,

    "video_id": str | None,
    "segment_id": str | None,

    "ts": int,

    # ---- question ----
    "question_id": str | None,
    "is_correct": bool | None,
    "content": str | None,
    "user_answer": str | None,
    "right_answer": str | None,

    # ---- chat ----
    "text": str | None,
    "intent": str | None,
}