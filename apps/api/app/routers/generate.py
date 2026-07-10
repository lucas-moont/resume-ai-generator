import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.domain.schemas import GenerateRequest, ResumeDocument
from app.routers.deps import resolve_requested_model
from app.services.errors import http_error
from app.services.generation_service import ExtractionError, generate_resume_events
from app.services.llm_client import llm_backend_label
from app.services.profile_service import ProfileValidationError
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
        raise http_error(404, str(e)) from e
    except ProfileValidationError as e:
        raise http_error(400, str(e)) from e
    except ExtractionError as e:
        raise http_error(
            502, f"LLM error ({llm_backend_label()}) extracting Profile.pdf: {e.original}"
        ) from e
    except json.JSONDecodeError as e:
        raise http_error(502, f"LLM returned invalid JSON: {e}") from e
    except Exception as e:
        raise http_error(502, f"LLM error ({llm_backend_label()}): {e}") from e
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
            # sse() redacts "message" for every "error" event -- this used to be the one
            # extraction-error path that skipped redaction (see B3's report); now uniform
            # with every other error path via the single choke point in streaming.sse().
            yield sse(
                "error",
                {"message": f"LLM error ({llm_backend_label()}) extracting Profile.pdf: {e.original}"},
            )
        except TimeoutError as e:
            yield sse("error", {"message": str(e)})
        except json.JSONDecodeError as e:
            yield sse("error", {"message": f"LLM returned invalid JSON: {e}"})
        except Exception as e:
            yield sse("error", {"message": f"LLM error ({llm_backend_label()}): {e}"})

    return StreamingResponse(event_stream(), media_type="text/event-stream")
