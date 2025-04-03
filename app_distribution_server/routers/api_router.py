import secrets

from fastapi import Form
from fastapi import APIRouter, Depends, File, Path, UploadFile
from fastapi.responses import PlainTextResponse
from fastapi.security import APIKeyHeader

from app_distribution_server.build_info import (
    BuildInfo,
    Platform,
    get_build_info,
)
from app_distribution_server.config import (
    UPLOADS_SECRET_AUTH_TOKEN,
    get_absolute_url,
)
from app_distribution_server.errors import (
    InvalidFileTypeError,
    NotFoundError,
    UnauthorizedError,
)
from app_distribution_server.logger import logger
from app_distribution_server.storage import (
    delete_upload,
    get_latest_upload_id_by_bundle_id,
    get_upload_asserted_platform,
    load_build_info,
    save_upload,
    save_tag_for_upload,
    get_upload_id_by_tag,
)

x_auth_token_dependency = APIKeyHeader(name="X-Auth-Token")


def x_auth_token_validator(
    x_auth_token: str = Depends(x_auth_token_dependency),
):
    if not secrets.compare_digest(x_auth_token, UPLOADS_SECRET_AUTH_TOKEN):
        raise UnauthorizedError()


router = APIRouter(
    tags=["API"],
    dependencies=[Depends(x_auth_token_validator)],
)


def _upload_app(
    app_file: UploadFile,
    tag: str | None = None,
) -> BuildInfo:
    platform: Platform

    if app_file.filename is None:
        raise InvalidFileTypeError()

    if app_file.filename.endswith(".ipa"):
        platform = Platform.ios

    elif app_file.filename.endswith(".apk"):
        platform = Platform.android

    else:
        raise InvalidFileTypeError()

    app_file_content = app_file.file.read()

    build_info = get_build_info(platform, app_file_content)
    build_info.tag = tag
    upload_id = build_info.upload_id

    logger.debug(f"Starting upload of {upload_id!r}")

    save_upload(build_info, app_file_content)

    if build_info.tag:
        save_tag_for_upload(build_info.bundle_id, build_info.tag, build_info.upload_id)

    logger.info(f"Successfully uploaded {build_info.bundle_id!r} ({upload_id!r})")

    return build_info


_upload_route_kwargs = {
    "responses": {
        InvalidFileTypeError.STATUS_CODE: {
            "description": InvalidFileTypeError.ERROR_MESSAGE,
        },
        UnauthorizedError.STATUS_CODE: {
            "description": UnauthorizedError.ERROR_MESSAGE,
        },
    },
    "summary": "Upload an iOS/Android app Build",
    "description": "On swagger UI authenticate in the upper right corner ('Authorize' button).",
}


@router.post("/upload", **_upload_route_kwargs)
def _plaintext_post_upload(
    app_file: UploadFile = File(description="An `.ipa` or `.apk` build"),
    tag: str | None = Form(default=None)
) -> PlainTextResponse:
    build_info = _upload_app(app_file, tag)
    return PlainTextResponse(
        content=get_absolute_url(f"/get/{build_info.upload_id}"),
    )


@router.post("/api/upload", **_upload_route_kwargs)
def _json_api_post_upload(
    app_file: UploadFile = File(description="An `.ipa` or `.apk` build"),
    tag: str | None = Form(default=None)
) -> BuildInfo:
    build_info = _upload_app(app_file, tag)
    return build_info


async def _api_delete_app_upload(
    upload_id: str = Path(),
) -> PlainTextResponse:
    get_upload_asserted_platform(upload_id)

    delete_upload(upload_id)
    logger.info(f"Upload {upload_id!r} deleted successfully")

    return PlainTextResponse(status_code=200, content="Upload deleted successfully")


router.delete(
    "/api/delete/{upload_id}",
    summary="Delete an uploaded app build",
    response_class=PlainTextResponse,
)(_api_delete_app_upload)

router.delete(
    "/delete/{upload_id}",
    deprecated=True,
    summary="Delete an uploaded app build. Deprecated, use /api/delete/UPLOAD_ID instead",
    response_class=PlainTextResponse,
)(_api_delete_app_upload)


@router.get(
    "/api/bundle/{bundle_id}/latest_upload",
    summary="Retrieve the latest upload from a bundle ID",
)
def api_get_latest_upload_by_bundle_id(
    bundle_id: str = Path(
        pattern=r"^[a-zA-Z0-9\.\-]{1,256}$",
    ),
) -> BuildInfo:
    upload_id = get_latest_upload_id_by_bundle_id(bundle_id)

    if not upload_id:
        raise NotFoundError()

    get_upload_asserted_platform(upload_id)
    return load_build_info(upload_id)

@router.get(
    "/api/bundle/{bundle_id}/{tag}",
    summary="Retrieve a tagged upload from a bundle ID",
)
def api_get_tagged_upload(
    bundle_id: str = Path(pattern=r"^[a-zA-Z0-9\.\-]{1,256}$"),
    tag: str = Path(pattern=r"^v\d+\.\d+\.\d+$"),
) -> BuildInfo:
    upload_id = get_upload_id_by_tag(bundle_id, tag)

    if not upload_id:
        raise NotFoundError()

    get_upload_asserted_platform(upload_id)
    return load_build_info(upload_id)
