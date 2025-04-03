from fastapi import APIRouter, Request, Response
from fastapi import HTTPException as FastApiHTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from app_distribution_server.build_info import (
    Platform,
)
from app_distribution_server.config import (
    APP_TITLE,
    LOGO_URL,
    get_absolute_url,
)
from app_distribution_server.qrcode import get_qr_code_svg
from app_distribution_server.storage import (
    get_latest_upload_id_by_bundle_id,
    get_upload_asserted_platform,
    load_build_info,
    get_upload_id_by_tag,
)

router = APIRouter(tags=["HTML page handling"])

templates = Jinja2Templates(directory="templates")


@router.get(
    "/get/{upload_id}",
    response_class=HTMLResponse,
    summary="Render the HTML installation page for the specified item ID",
)
async def render_get_item_installation_page(
    request: Request,
    upload_id: str,
) -> HTMLResponse:
    platform = get_upload_asserted_platform(upload_id)

    if platform == Platform.ios:
        plist_url = get_absolute_url(f"/get/{upload_id}/app.plist")
        install_url = f"itms-services://?action=download-manifest&url={plist_url}"
    else:
        install_url = get_absolute_url(f"/get/{upload_id}/app.apk")

    build_info = load_build_info(upload_id)

    return templates.TemplateResponse(
        request=request,
        name="download-page.jinja.html",
        context={
            "page_title": f"{build_info.app_title} @{build_info.bundle_version} - {APP_TITLE}",
            "build_info": build_info,
            "install_url": install_url,
            "qr_code_svg": get_qr_code_svg(install_url),
            "logo_url": LOGO_URL,
        },
    )


async def render_error_page(
    request: Request,
    user_error: FastApiHTTPException | StarletteHTTPException,
) -> Response:
    return templates.TemplateResponse(
        request=request,
        status_code=user_error.status_code,
        name="error.jinja.html",
        context={
            "page_title": user_error.detail,
            "error_message": f"{user_error.status_code} - {user_error.detail}",
        },
    )


@router.get(
    "/bundle/{bundle_id}",
    response_class=HTMLResponse,
    summary="Landing page for the latest app build of a bundle ID",
)
async def render_latest_bundle_installation_page(
    request: Request,
    bundle_id: str,
) -> HTMLResponse:
    upload_id = get_latest_upload_id_by_bundle_id(bundle_id)

    if not upload_id:
        raise FastApiHTTPException(status_code=404, detail="No builds found for this bundle ID")

    return await render_get_item_installation_page(request, upload_id)

@router.get(
    "/bundle/{bundle_id}/{tag}",
    response_class=HTMLResponse,
    summary="Landing page for a specific tagged app build of a bundle ID",
)
async def render_tagged_bundle_installation_page(
    request: Request,
    bundle_id: str,
    tag: str,
) -> HTMLResponse:
    upload_id = get_upload_id_by_tag(bundle_id, tag)

    if not upload_id:
        raise FastApiHTTPException(status_code=404, detail="No builds found for this tag")

    return await render_get_item_installation_page(request, upload_id)
