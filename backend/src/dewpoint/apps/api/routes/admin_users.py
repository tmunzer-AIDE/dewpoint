# SPDX-License-Identifier: Apache-2.0
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.audit.service import record
from dewpoint.core.auth.users import Email, EmailTakenError, PasswordPolicyError, create_user
from dewpoint.core.http import get_db, require_platform_admin
from dewpoint.core.models.identity import User

router = APIRouter(prefix="/api/v1/admin/users", tags=["admin"])


class UserIn(BaseModel):
    email: Email
    password: str = Field(min_length=1, max_length=1024)


@router.post("", status_code=201)
async def create(
    body: UserIn, admin: User = Depends(require_platform_admin), db: AsyncSession = Depends(get_db, scope="function")
) -> dict[str, str]:
    """Create a local account. The new user must enroll MFA at first sign-in."""
    try:
        user = await create_user(db, email=body.email, password=body.password)
    except PasswordPolicyError as e:
        raise HTTPException(422, detail={"error": "password_policy", "violations": e.violations}) from None
    except EmailTakenError:
        raise HTTPException(409, detail={"error": "email_taken"}) from None
    await record(
        db, tenant_id=None, actor_id=admin.id, action="user.create", target_type="user", target_id=str(user.id)
    )
    return {"id": str(user.id), "email": user.email}
