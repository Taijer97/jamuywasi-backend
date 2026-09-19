import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"

@pytest.mark.asyncio
async def test_api_health():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

@pytest.mark.asyncio
async def test_get_stores():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/stores")
        assert response.status_code == 200
        stores = response.json()
        assert len(stores) >= 3

@pytest.mark.asyncio
async def test_get_products():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/products")
        assert response.status_code == 200
        products = response.json()
        assert len(products) >= 4

@pytest.mark.asyncio
async def test_get_banners():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/api/banners")
        assert response.status_code == 200
        banners = response.json()
        assert len(banners) >= 2

@pytest.mark.asyncio
async def test_auth_login():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post("/api/auth/login", json={
            "email": "admin@jamuywasi.com",
            "password": "admin123"
        })
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["user"]["role"] == "superadmin"
