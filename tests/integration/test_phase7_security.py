"""مسیر فایل عمومی نباید احراز هویت و جداسازی رزومه را دور بزند."""

from app.core.config import settings
from app.core.storage import resolve_local_media_path
from tests.integration import test_tenant_isolation as tenant_fixtures
from tests.integration.conftest import auth_headers

two_orgs = tenant_fixtures.two_orgs


async def test_private_file_requires_identity_and_exact_tenant_or_owner(client, db_session, two_orgs, make_user):
    a = two_orgs["A"]
    resume = a["resume"]
    resume.file_url = settings.MEDIA_BASE_URL.rstrip("/") + "/resumes/phase7-synthetic.pdf"
    path = resolve_local_media_path(resume.file_url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4\n% synthetic privacy fixture\n")
    await db_session.commit()
    route = f"/api/v1/resumes/{resume.id}/file"
    try:
        assert (await client.get("/media/resumes/phase7-synthetic.pdf")).status_code == 404
        assert (await client.get(route)).status_code == 401
        assert (await client.get(route, headers=auth_headers(two_orgs["B"]["hr"]))).status_code == 404
        stranger = await make_user(role="Candidate")
        assert (await client.get(route, headers=auth_headers(stranger))).status_code == 404
        for user in [a["hr"], a["candidate_user"]]:
            response = await client.get(route, headers=auth_headers(user))
            assert response.status_code == 200, response.text
            assert response.content.startswith(b"%PDF-1.4")
            assert response.headers["cache-control"] == "private, no-store"
            assert response.headers["x-content-type-options"] == "nosniff"
    finally:
        path.unlink(missing_ok=True)
