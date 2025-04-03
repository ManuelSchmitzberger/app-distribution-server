from typing import Literal

import httpx
from fastapi.responses import StreamingResponse
from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi import HTTPException

from app_distribution_server.build_info import (
    Platform,
)
from app_distribution_server.config import (
    GITLAB_ACCESS_TOKEN,
    get_absolute_url,
)
from app_distribution_server.storage import (
    get_upload_asserted_platform,
    load_app_file,
    load_build_info,
)

router = APIRouter(tags=["App files"])

templates = Jinja2Templates(directory="templates")


@router.get(
    "/get/{upload_id}/app.plist",
    response_class=HTMLResponse,
)
async def get_item_plist(
    request: Request,
    upload_id: str,
) -> HTMLResponse:
    get_upload_asserted_platform(
        upload_id,
        expected_platform=Platform.ios,
    )

    build_info = load_build_info(upload_id)

    return templates.TemplateResponse(
        request=request,
        name="plist.xml",
        media_type="application/xml",
        context={
            "ipa_file_url": get_absolute_url(f"/get/{upload_id}/{Platform.ios.app_file_name}"),
            "app_title": build_info.app_title,
            "bundle_id": build_info.bundle_id,
            "bundle_version": build_info.bundle_version,
        },
    )


@router.get(
    "/get/{upload_id}/app.{file_type}",
    response_class=HTMLResponse,
)
async def get_app_file(
    upload_id: str,
    file_type: Literal["ipa", "apk"],
) -> Response:
    build_info = load_build_info(upload_id)
    expected_platform = Platform.ios if file_type == "ipa" else Platform.android
    get_upload_asserted_platform(upload_id, expected_platform=expected_platform)

    # PROXY: GitLab Artifact Handling
    if build_info.external_gitlab_url:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                build_info.external_gitlab_url,
                headers={"PRIVATE-TOKEN": GITLAB_ACCESS_TOKEN},
                follow_redirects=True,
            )

        if response.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to download artifact from GitLab: {response.status_code}",
            )

        return StreamingResponse(
            response.aiter_bytes(),
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f"attachment; filename={build_info.app_title}.{file_type}"
            }
        )

    app_file_content = load_app_file(build_info)

    created_at_prefix = (
        build_info.created_at.strftime("%Y-%m-%d_%H-%M-%S") if build_info.created_at else ""
    )
    file_name = f"{build_info.app_title} {build_info.bundle_version}{created_at_prefix}"

    return Response(
        content=app_file_content,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={file_name}.{file_type}"},
    )
