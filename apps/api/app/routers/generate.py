import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.domain.schemas import GenerateRequest, ResumeDocument
from app.routers.deps import resolve_requested_model
from app.services.generation_service import ExtractionError, generate_resume_events
from app.services.llm_client import llm_backend_label
from app.services.profile_service import ProfileValidationError
from app.services.secret_redaction import redact_secrets
from app.services.streaming import sse

router = APIRouter()


@router.post("/api/generate", response_model=ResumeDocument)
async def generate(body: GenerateRequest):
    model = resolve_requested_model(body.model)
    try:
        resume: ResumeDocument | None = None
        async for event, data in generate_resume_events(
            job_description=body.job_description,
            model=model,
            locale=body.locale,
            backend_label=llm_backend_label(),
        ):
            if event == "done":
                resume = data["resume"]
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ProfileValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ExtractionError as e:
        raise HTTPException(
            status_code=502,
            detail=f"LLM error ({llm_backend_label()}) extracting Profile.pdf: {redact_secrets(str(e.original))}",
        ) from e
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=502, detail=f"LLM returned invalid JSON: {e}") from e
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"LLM error ({llm_backend_label()}): {redact_secrets(str(e))}",
        ) from e
    return resume


@router.post("/api/generate/stream")
async def generate_stream(body: GenerateRequest):
    model = resolve_requested_model(body.model)

    async def event_stream():
        try:
            async for event, data in generate_resume_events(
                job_description=body.job_description,
                model=model,
                locale=body.locale,
                backend_label=llm_backend_label(),
            ):
                if event == "done":
                    yield sse("done", {"progress": data["progress"], "resume": data["resume"].model_dump()})
                else:
                    yield sse(event, data)
        except FileNotFoundError as e:
            yield sse("error", {"message": str(e)})
        except ProfileValidationError as e:
            yield sse("error", {"message": str(e)})
        except ExtractionError as e:
            # No redact_secrets here: matches the pre-B4 stream behavior exactly (a
            # pre-existing inconsistency vs. the sync path above -- see B3's report).
            yield sse(
                "error",
                {"message": f"LLM error ({llm_backend_label()}) extracting Profile.pdf: {e.original}"},
            )
        except TimeoutError as e:
            yield sse("error", {"message": str(e)})
        except json.JSONDecodeError as e:
            yield sse("error", {"message": f"LLM returned invalid JSON: {e}"})
        except Exception as e:
            yield sse("error", {"message": f"LLM error ({llm_backend_label()}): {redact_secrets(str(e))}"})

    return StreamingResponse(event_stream(), media_type="text/event-stream")
