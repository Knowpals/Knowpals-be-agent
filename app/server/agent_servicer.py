from __future__ import annotations

import grpc

from app.agent.orchestrator import LearningAgent
from app.pb.gen import agent_pb2, agent_pb2_grpc


class AgentGrpcServicer(agent_pb2_grpc.AgentServiceServicer):
    def __init__(self, agent: LearningAgent) -> None:
        self.agent = agent

    def Chat(self, request: agent_pb2.ChatRequest, context: grpc.ServicerContext):
        try:
            res = self.agent.chat(
                student_id=request.student_id,
                text=request.text,
                video_id=request.video_id or None,
                knowledge_id=request.knowledge_id or None,
            )
            return agent_pb2.ChatResponse(reply=res.reply or "", context=res.context or "", video_id=res.video_id or "")
        except Exception as e:
            context.abort(grpc.StatusCode.INTERNAL, str(e))

    def GenerateQuiz(self, request: agent_pb2.GenerateQuizRequest, context: grpc.ServicerContext):
        try:
            quizzes = self.agent.generate_quiz(
                student_id=request.student_id,
                video_id=request.video_id,
                num_questions=request.num_questions or 5,
            )
            out = []
            for q in quizzes:
                out.append(
                    agent_pb2.QuizItem(
                        knowledge_id=str(q.get("knowledge_id", "")),
                        type=str(q.get("type", "")),
                        question=str(q.get("question", "")),
                        options=[str(x) for x in (q.get("options") or [])],
                        answer=str(q.get("answer", "")),
                        analysis=str(q.get("analysis", "")),
                        difficulty=str(q.get("difficulty", "")),
                    )
                )
            return agent_pb2.GenerateQuizResponse(quizzes=out)
        except Exception as e:
            context.abort(grpc.StatusCode.INTERNAL, str(e))

    def GenerateReport(self, request: agent_pb2.GenerateReportRequest, context: grpc.ServicerContext):
        try:
            rep = self.agent.generate_report(student_id=request.student_id, video_id=request.video_id, topk=5)
            items = []
            for it in rep.get("items", []):
                seg_refs = []
                for s in (it.get("recommended_segments") or []):
                    if not isinstance(s, dict):
                        continue
                    seg_refs.append(
                        agent_pb2.SegmentRef(
                            video_id=str(s.get("video_id", "")),
                            segment_id=str(s.get("segment_id", "")),
                            start_ms=int(s.get("start_ms", 0) or 0),
                            end_ms=int(s.get("end_ms", 0) or 0),
                        )
                    )
                items.append(
                    agent_pb2.ReportItem(
                        knowledge_id=str(it.get("knowledge_id", "")),
                        mastery=float(it.get("mastery", 0.0) or 0.0),
                        summary=str(it.get("summary", "")),
                        weakness=[str(x) for x in (it.get("weakness") or [])],
                        behavior_pattern=[str(x) for x in (it.get("behavior_pattern") or [])],
                        trend=str(it.get("trend", "")),
                        recommended_segments=seg_refs,
                    )
                )
            return agent_pb2.GenerateReportResponse(
                video_id=str(rep.get("video_id", "")),
                items=items,
                overall_summary=str(rep.get("overall_summary", "")),
            )
        except Exception as e:
            context.abort(grpc.StatusCode.INTERNAL, str(e))

    def register(self, server: grpc.Server) -> None:
        agent_pb2_grpc.add_AgentServiceServicer_to_server(self, server)