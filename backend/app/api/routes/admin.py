from fastapi import APIRouter, Query

from app.services.admin_service import seed_demo, clear_demo

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/seed-demo")
def admin_seed_demo(dry_run: bool = Query(False)):
    return seed_demo(dry_run=dry_run)


@router.post("/clear-demo")
def admin_clear_demo(confirm: bool = Query(False, description="Must be true to actually delete data")):
    if not confirm:
        return {"ok": False, "message": "Pass ?confirm=true to actually delete demo data."}
    return clear_demo()
