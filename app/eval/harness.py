import json
from pathlib import Path
from typing import Any, Dict, List

from sqlmodel import Session, select

from app.core.orchestrator import Orchestrator
from app.db.models import EvaluationRun, JobExecution
from app.db.sessions import engine
from app.eval.meta_optimizer import MetaAgent


CASES_PATH = Path(__file__).with_name("cases.json")


class EvaluationHarness:
    """Manual scoring harness for the built-in 15 evaluation cases."""

    def __init__(self) -> None:
        self.orchestrator = Orchestrator()
        self.meta_agent = MetaAgent()

    async def run_all(self) -> Dict[str, Any]:
        cases = self.load_cases()
        results = []
        for case in cases:
            results.append(await self.run_case(case))
        failures = [item for item in results if item["score"] < 0.7]
        prompt_diffs = await self.meta_agent.propose_prompt_diffs(failures)
        return {
            "count": len(results),
            "average_score": round(sum(item["score"] for item in results) / max(len(results), 1), 3),
            "results": results,
            "prompt_diffs": prompt_diffs,
        }

    async def run_case(self, case: Dict[str, Any]) -> Dict[str, Any]:
        final_payload: Dict[str, Any] = {}
        async for event in self.orchestrator.execute(case["query"]):
            if event["event"] == "final":
                final_payload = json.loads(event["data"])
            elif event["event"] == "error":
                final_payload = {"answer": "", "error": json.loads(event["data"]).get("message")}

        answer = str(final_payload.get("answer", ""))
        score, justification = self.score_answer(answer, case)
        job_id = str(final_payload.get("job_id", ""))
        self._record_eval(job_id, case["category"], score, justification)
        return {
            "case_id": case["id"],
            "category": case["category"],
            "job_id": job_id,
            "score": score,
            "justification": justification,
            "answer": answer,
        }

    def load_cases(self) -> List[Dict[str, Any]]:
        return json.loads(CASES_PATH.read_text(encoding="utf-8"))

    def score_answer(self, answer: str, case: Dict[str, Any]) -> tuple[float, str]:
        lowered = answer.lower()
        traits = case.get("expected_traits", [])
        hits = 0
        for trait in traits:
            terms = [term.strip().lower() for term in str(trait).replace("/", " ").split()]
            if any(term and term in lowered for term in terms):
                hits += 1
        non_empty = 0.2 if len(answer.split()) >= 8 else 0.0
        score = min(1.0, non_empty + (hits / max(len(traits), 1)) * 0.8)
        justification = f"Matched {hits}/{len(traits)} expected traits; answer length={len(answer.split())} words."
        return round(score, 3), justification

    def _record_eval(self, job_id: str, category: str, score: float, justification: str) -> None:
        if not job_id:
            return
        try:
            with Session(engine) as session:
                if session.get(JobExecution, job_id):
                    session.add(
                        EvaluationRun(
                            job_id=job_id,
                            category=category,
                            score=score,
                            justification=justification,
                        )
                    )
                    session.commit()
        except Exception:
            pass


def eval_summary() -> Dict[str, Any]:
    try:
        with Session(engine) as session:
            runs = session.exec(select(EvaluationRun)).all()
            if not runs:
                return {"count": 0, "average_score": None, "by_category": {}}
            by_category: Dict[str, List[float]] = {}
            for run in runs:
                by_category.setdefault(run.category, []).append(run.score)
            return {
                "count": len(runs),
                "average_score": round(sum(run.score for run in runs) / len(runs), 3),
                "by_category": {
                    category: round(sum(scores) / len(scores), 3)
                    for category, scores in by_category.items()
                },
            }
    except Exception as exc:
        return {"count": 0, "average_score": None, "by_category": {}, "error": str(exc)}
