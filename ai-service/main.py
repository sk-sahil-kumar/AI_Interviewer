
import uvicorn
import os
import io
import json
import tempfile
import threading
import re

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from typing import Optional

from ollama import Client
import whisper
from pydub import AudioSegment


load_dotenv()

AI_SERVICE_PORT = int(os.getenv("AI_SERVICE_PORT", 8000))

OLLAMA_MODEL_NAME = os.getenv(
    "OLLAMA_MODEL_NAME",
    "mistral-large-4"
)

OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY")

# Ollama Cloud Client
ollama_client = Client(
    host="https://ollama.com",
    headers={
        "Authorization": f"Bearer {OLLAMA_API_KEY}"
    } if OLLAMA_API_KEY else {}
)


def check_ollama_config():
    if not OLLAMA_API_KEY:
        raise RuntimeError(
            "OLLAMA_API_KEY is missing in environment variables"
        )


app = FastAPI(
    title="AI Interviewer Microservice",
    version="1.0"
)


origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Load Whisper only when transcription is requested.
WHISPER_MODEL = None
WHISPER_MODEL_LOCK = threading.Lock()


def get_whisper_model():
    global WHISPER_MODEL

    if WHISPER_MODEL is None:
        with WHISPER_MODEL_LOCK:
            if WHISPER_MODEL is None:
                print("Loading Whisper tiny.en model...")

                import torch
                torch.set_num_threads(1)

                WHISPER_MODEL = whisper.load_model(
                    "tiny.en",
                    device="cpu"
                )

                print("Whisper Model Loaded Successfully")

    return WHISPER_MODEL


class QuestionResquest(BaseModel):
    role: str = "MERN Stack Developer"
    level: str = "Junior"
    count: int = Field(default=5, ge=1, le=20)
    interview_type: str = "coding-mix"


class QuestionResponse(BaseModel):
    questions: list[str]
    model_used: str


class EvaluationRequest(BaseModel):
    question: str
    question_type: str
    role: str
    level: str
    user_answer: Optional[str] = None
    user_code: Optional[str] = None


class EvaluationResponse(BaseModel):
    technicalScore: int
    confidenceScore: int
    aiFeedback: str
    idealAnswer: str


@app.get("/")
async def root():
    return {
        "message": "Hello from AI Interviewer Microservice!",
        "model": OLLAMA_MODEL_NAME,
        "provider": "Ollama Cloud"
    }


@app.post("/generate-questions", response_model=QuestionResponse)
async def generate_questions(request: QuestionResquest):

    try:
        check_ollama_config()

        if request.interview_type == "coding-mix":

            coding_count = int(request.count * 0.2)
            oral_count = request.count - coding_count

            instruction = (
                f"The first {coding_count} questions MUST be coding "
                "challenges requiring function implementation. "
                f"The remaining {oral_count} questions MUST be "
                "conceptual oral questions."
            )

        else:
            instruction = (
                "All questions MUST be conceptual oral questions. "
                "Do NOT generate coding or implementation challenges."
            )

        system_prompt = (
            "You are a professional technical interviewer. "
            "Task: Generate interview questions. "
            "No conversational text or numbering. "
            f"Crucial: {instruction} "
            "Output exactly one question per line."
        )

        user_prompt = (
            f"Generate exactly {request.count} unique interview questions "
            f"for a {request.level} level {request.role}."
        )

        response = ollama_client.generate(
            model=OLLAMA_MODEL_NAME,
            prompt=user_prompt,
            system=system_prompt,
            stream=False,
            options={"temperature": 0.6}
        )

        raw_text = response["response"].strip()

        questions = [
            q.strip().lstrip("0123456789. )-")
            for q in raw_text.split("\n")
            if q.strip()
        ]

        questions = [q for q in questions if q]

        if not questions:
            raise ValueError("No questions were generated")

        return QuestionResponse(
            questions=questions[:request.count],
            model_used=OLLAMA_MODEL_NAME
        )

    except Exception as e:
        print(f"Question generation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):

    temp_audio_path = None

    try:
        audio_bytes = await file.read()

        if not audio_bytes:
            raise HTTPException(
                status_code=400,
                detail="Uploaded audio file is empty"
            )

        audio_in_memory = io.BytesIO(audio_bytes)

        audio_segment = AudioSegment.from_file(audio_in_memory)

        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=".mp3"
        ) as tmp:
            temp_audio_path = tmp.name

        audio_segment.export(
            temp_audio_path,
            format="mp3"
        )

        model = get_whisper_model()

        result = model.transcribe(
            temp_audio_path,
            fp16=False
        )

        return {
            "transcription": result["text"].strip()
        }

    except HTTPException:
        raise

    except Exception as e:
        print(f"Transcription error: {e}")
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

    finally:
        if temp_audio_path and os.path.exists(temp_audio_path):
            os.remove(temp_audio_path)


@app.post("/evaluate", response_model=EvaluationResponse)
async def evaluate(request: EvaluationRequest):

    try:
        check_ollama_config()

        if request.question_type == "oral":

            assessment_instruction = (
                "This is a conceptual oral question. "
                "Focus purely on candidate's verbal explanation. "
                "Ignore any code blocks. "
                "If the transcript is empty, nonsense "
                "or irrelevant to the question, SCORE 0."
            )

        else:

            assessment_instruction = (
                "This is a coding challenge question. "
                "Evaluate the code logic and efficiency. "
                "Use the transcription only for insight into their "
                "thought process. "
                "If the code is undefined, empty, random comments, "
                "or random characters, SCORE 0."
            )

        system_prompt = (
            "You are a strict technical interviewer. "
            "Do NOT hallucinate positive reviews for bad input. "
            "RULE 1: If the answer is gibberish, irrelevant, "
            "or missing, return technicalScore 0 and confidenceScore 0. "
            "RULE 2: For idealAnswer, provide a clean Markdown string. "
            "Do NOT return a nested JSON object. "
            f"Context: {assessment_instruction} "
            "Respond ONLY with a valid JSON object. "
            "Do not use Markdown code fences. "
            "Required keys: technicalScore (0-100), "
            "confidenceScore (0-100), aiFeedback, idealAnswer."
        )

        user_prompt = (
            f"Role: {request.role}\n"
            f"Question: {request.question}\n"
            f"Level: {request.level}\n"
            f"Verbal Answer: {request.user_answer or 'No verbal answer provided'}\n"
            f"Code Answer: {request.user_code or 'No code provided'}\n"
        )

        response = ollama_client.generate(
            model=OLLAMA_MODEL_NAME,
            prompt=user_prompt,
            system=system_prompt,
            stream=False,
            options={"temperature": 0.1}
        )

        response_text = response["response"].strip()

        # Remove Markdown JSON fences if the model returns them.
        response_text = re.sub(
            r"^```(?:json)?\s*|\s*```$",
            "",
            response_text,
            flags=re.IGNORECASE
        ).strip()

        # Extract JSON object if extra text is returned.
        start = response_text.find("{")
        end = response_text.rfind("}")

        if start == -1 or end == -1:
            raise ValueError("AI did not return a valid JSON object")

        response_text = response_text[start:end + 1]

        evaluation_data = json.loads(response_text)

        # Ensure idealAnswer is a string.
        if not isinstance(evaluation_data.get("idealAnswer"), str):
            evaluation_data["idealAnswer"] = json.dumps(
                evaluation_data.get("idealAnswer", ""),
                ensure_ascii=False
            )

        # Validate and limit scores.
        evaluation_data["technicalScore"] = max(
            0,
            min(100, int(evaluation_data["technicalScore"]))
        )

        evaluation_data["confidenceScore"] = max(
            0,
            min(100, int(evaluation_data["confidenceScore"]))
        )

        return EvaluationResponse(**evaluation_data)

    except Exception as e:
        print(f"Failed to generate evaluation: {e}")

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=AI_SERVICE_PORT
    )
