from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.security import decode_token
from app.models.all_models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

async def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db)
) -> Optional[User]:
    if not token:
        return None
    payload = decode_token(token)
    if not payload or "sub" not in payload:
        return None
    user_id = payload["sub"]
    stmt = select(User).where(User.id == user_id)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()
    return user

async def get_required_user(
    current_user: Optional[User] = Depends(get_current_user)
) -> User:
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales no válidas o sesión expirada"
        )
    return current_user

async def get_superadmin_user(
    current_user: User = Depends(get_required_user)
) -> User:
    if current_user.role != "superadmin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso restringido a SuperAdministradores"
        )
    return current_user
