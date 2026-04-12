import redis

class EventCache:
    def __init__(self,client:redis.Redis):
        self.client=client

    # 为了在消费者端确定幂等性
    def is_done(self,job_id, stage)->bool:
        return self.client.exists(f"job:{job_id}:{stage}") == 1

    def mark_done(self,job_id, stage):
        self.client.set(f"job:{job_id}:{stage}", 1, ex=86400)
