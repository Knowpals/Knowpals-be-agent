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