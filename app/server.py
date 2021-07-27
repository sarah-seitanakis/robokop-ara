"""Fill knowledge graph and bind."""
import logging
import os

from bmt import Toolkit
from fastapi import Body
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse
import httpx
from reasoner_pydantic import Query as ReasonerQuery, Response
from starlette.requests import Request

from .identifiers import map_identifiers
from .util import load_example
from .trapi import TRAPI

BMT = Toolkit(schema="https://raw.githubusercontent.com/biolink/biolink-model/1.8.2/biolink-model.yaml")

openapi_kwargs = dict(
    title="ROBOKOP ARA",
    version="2.2.0",
    terms_of_service="N/A",
    translator_component="ARA",
    translator_teams=["SRI"],
    contact={
        "name": "Patrick Wang",
        "email": "patrick@covar.com",
        "x-id": "patrickkwang",
        "x-role": "responsible developer",
    },
    openapi_tags=[{"name": "robokop"}],
    trapi_operations=["lookup"],
)
OPENAPI_SERVER_URL = os.getenv("OPENAPI_SERVER_URL")
if OPENAPI_SERVER_URL:
    openapi_kwargs["servers"] = [
        {"url": OPENAPI_SERVER_URL}
    ]
APP = TRAPI(**openapi_kwargs)


LOGGER = logging.getLogger(__name__)


@APP.exception_handler(Exception)
async def exception_handler(request: Request, exc: Exception):
    LOGGER.exception(exc)
    return JSONResponse(
        status_code=500,
        content={"message": str(exc)},
    )


@APP.post(
        "/query",
        tags=["reasoner"],
        response_model=Response,
        response_model_exclude_unset=True,
        responses={
            200: {
                "content": {
                    "application/json": {
                        "example": load_example("response")
                    }
                },
            },
        },
)
async def lookup(
        request: ReasonerQuery = Body(..., example=load_example("query")),
) -> Response:
    """Look up answers to the question."""
    trapi_query = request.dict(
        by_alias=True,
        exclude_unset=True,
    )
    try:
        await map_identifiers(trapi_query)
    except KeyError:
        pass
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://automat.renci.org/robokopkg/1.1/query",
            json=trapi_query,
            timeout=None,
        )
        if response.status_code != 200:
            raise HTTPException(500, f"Failed doing lookup: {response.text}")

        response = await client.post(
            "https://aragorn-ranker.renci.org/1.1/omnicorp_overlay",
            json=response.json(),
            timeout=None,
        )
        if response.status_code != 200:
            raise HTTPException(500, f"Failed doing overlay: {response.text}")

        response = await client.post(
            "https://aragorn-ranker.renci.org/1.1/weight_correctness",
            json=response.json(),
            timeout=None,
        )
        if response.status_code != 200:
            raise HTTPException(500, f"Failed doing weighting: {response.text}")

        response = await client.post(
            "https://aragorn-ranker.renci.org/1.1/score",
            json=response.json(),
            timeout=None,
        )
        if response.status_code != 200:
            raise HTTPException(500, f"Failed doing scoring: {response.text}")
    return Response(**response.json())
