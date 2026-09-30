from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import AskRequest, AskResponse
from app.services.ask import answer_question

router = APIRouter()


@router.post("", response_model=AskResponse)
def ask(request: AskRequest, db: Session = Depends(get_db)):
    result = answer_question(db, request.question, top_k=request.top_k)
    return result
