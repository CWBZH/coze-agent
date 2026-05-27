from fastapi import Depends


def require_admin() -> bool:
    return True


AdminDependency = Depends(require_admin)
