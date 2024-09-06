import secrets
from typing import Literal
from venv import logger

from fastapi import APIRouter, File, Header, Request, Response, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app_distribution_server.config import (
    APP_BASE_URL,
    APP_TITLE,
    LOGO_URL,
    UPLOAD_SECRET_AUTH_TOKEN,
)
from app_distribution_server.errors import (
    InvalidFileTypeError,
    NotFoundError,
    UnauthorizedError,
)
from app_distribution_server.mobile_builds import (
    Platform,
    get_build_info,
)
from app_distribution_server.qrcode import get_qr_code_svg
from app_distribution_server.storage import (
    create_parent_directories,
    get_upload_platform,
    load_app_file,
    load_build_info,
    save_app_file,
    save_build_info,
)

router = APIRouter()

templates = Jinja2Templates(directory="templates")


def get_absolute_url(path: str) -> str:
    return f"{APP_BASE_URL}{path}"


def get_asserted_platform(
    upload_id: str,
    expected_platform: Platform | None = None,
) -> Platform:
    upload_platform = get_upload_platform(upload_id)

    if upload_platform is None:
        raise NotFoundError()

    if expected_platform is None:
        return upload_platform

    if upload_platform == expected_platform:
        return upload_platform

    raise NotFoundError()


@router.post(
    "/upload",
    responses={
        InvalidFileTypeError.STATUS_CODE: {
            "description": InvalidFileTypeError.ERROR_MESSAGE,
        },
        UnauthorizedError.STATUS_CODE: {
            "description": UnauthorizedError.ERROR_MESSAGE,
        },
    },
    tags=["Upload API"],
    summary="Upload an iOS/Android app Build",
)
async def upload_app(
    app_file: UploadFile = File(),
    x_auth_token: str = Header(),
) -> Response:
    if not secrets.compare_digest(x_auth_token, UPLOAD_SECRET_AUTH_TOKEN):
        raise UnauthorizedError()

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
    upload_id = build_info.upload_id

    logger.debug(f"Starting upload of {upload_id!r}")

    create_parent_directories(build_info.upload_id)
    save_build_info(build_info)
    save_app_file(build_info, app_file_content)

    logger.info(f"Upload {build_info.bundle_id!r} ({upload_id!r}) complete")

    return Response(
        content=get_absolute_url(f"/get/{upload_id}"),
        media_type="text/plain",
    )


@router.get(
    "/get/{upload_id}",
    response_class=HTMLResponse,
    tags=["Static page handling"],
    summary="Render the HTML installation page for the specified item ID.",
)
async def get_item_installation_page(
    request: Request,
    upload_id: str,
) -> HTMLResponse:
    platform = get_asserted_platform(upload_id)

    if platform == Platform.ios:
        plist_url = get_absolute_url(f"/get/{upload_id}/app.plist")
        install_url = f"itms-services://?action=download-manifest&url={plist_url}"
    else:
        install_url = get_absolute_url(f"/get/{upload_id}/app.apk")

    build_info = load_build_info(upload_id)

    return templates.TemplateResponse(
        request=request,
        name="download-page.html",
        context={
            "page_title": f"{build_info.app_title} @{build_info.bundle_version} - {APP_TITLE}",
            "build_info": build_info,
            "install_url": install_url,
            "qr_code_svg": get_qr_code_svg(install_url),
            "logo_url": LOGO_URL,
        },
    )


@router.get(
    "/get/{upload_id}/app.plist",
    response_class=HTMLResponse,
    tags=["Static page handling"],
)
async def get_item_plist(
    request: Request,
    upload_id: str,
) -> HTMLResponse:
    get_asserted_platform(
        upload_id,
        expected_platform=Platform.ios,
    )

    build_info = load_build_info(upload_id)

    return templates.TemplateResponse(
        request=request,
        name="plist.xml",
        context={
            "ipa_file_url": get_absolute_url(f"/get/{upload_id}/app.ipa"),
            "app_title": build_info.app_title,
            "bundle_id": build_info.bundle_id,
            "bundle_version": build_info.bundle_version,
        },
    )


@router.get(
    "/get/{upload_id}/app.{file_type}",
    response_class=HTMLResponse,
    tags=["Static page handling"],
)
async def get_app_file(upload_id: str, file_type: Literal["ipa", "apk"]) -> Response:
    expected_platform = Platform.ios if file_type == "ipa" else Platform.android
    get_asserted_platform(upload_id, expected_platform=expected_platform)

    build_info = load_build_info(upload_id)
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


@router.get(
    "/healthz",
    tags=["Healthz"],
)
async def healthz():
    return Response(
        content="OK",
        media_type="text/plain",
    )
