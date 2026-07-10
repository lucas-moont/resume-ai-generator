import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.domain.schemas import RefineRequest, ResumeDocument
from app.routers.deps import resolve_requested_model
from app.services.llm_client import llm_backend_label
from app.services.profile_service import ProfileValidationError
from app.services.refine_service import refine_resume_events
from app.services.secret_redaction import redact_secrets
from app.services.streaming import sse

router = APIRouter()


@router.post("/api/refine", response_model=ResumeDocument)
async def refine(body: RefineRequest):
    model = resolve_requested_model(body.model)
    try:
        resume: ResumeDocument | None = None
        async for event, data in refine_resume_events(
            resume=body.resume,
            message=body.message,
            model=model,
            backend_label=llm_backend_label(),
        ):
            if event == "done":
                resume = data["resume"]
    except ProfileValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=502, detail=f"LLM returned invalid JSON: {e}") from e
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"LLM error ({llm_backend_label()}): {redact_secrets(str(e))}",
        ) from e
    return resume


@router.post("/api/refine/stream")
async def refine_stream(body: RefineRequest):
    model = resolve_requested_model(body.model)

    async def event_stream():
        try:
            async for event, data in refine_resume_events(
                resume=body.resume,
                message=body.message,
                model=model,
                backend_label=llm_backend_label(),
            ):
                if event == "done":
                    yield sse("done", {"progress": data["progress"], "resume": data["resume"].model_dump()})
                else:
                    yield sse(event, data)
        except ProfileValidationError as e:
            yield sse("error", {"message": str(e)})
        except TimeoutError as e:
            yield sse("error", {"message": str(e)})
        except json.JSONDecodeError as e:
            yield sse("error", {"message": f"LLM returned invalid JSON: {e}"})
        except Exception as e:
            yield sse("error", {"message": f"LLM error ({llm_backend_label()}): {redact_secrets(str(e))}"})

    return StreamingResponse(event_stream(), media_type="text/event-stream")
