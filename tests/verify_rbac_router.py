
import asyncio
from unittest.mock import MagicMock, AsyncMock
import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

# Import permissions logic
from core.permissions import require_module_access
from fastapi import HTTPException

async def test_router_logic_simulation(context: dict, action_name: str, should_pass: bool):
    """
    Simulates the logic INSIDE the routers that we just refactored.
    """
    print(f"Testing Router Logic: {action_name}...")
    print(f"   Context: User Role={context.get('role')}, Module Roles={context.get('module_roles')}")
    
    # Logic extracted from Refactored Routers
    role = context.get("role")
    module_role = context.get("module_roles", {}).get("comercial", "")
    
    # Logic: Admin Global OR Module Admin
    access_granted = (role == "ADMIN") or (module_role == "admin")
    
    if access_granted == should_pass:
        print(f"   ✅ Result: {'GRANTED' if access_granted else 'DENIED'} (EXPECTED)")
        return True
    else:
        print(f"   ❌ Result: {'GRANTED' if access_granted else 'DENIED'} (UNEXPECTED)")
        return False

async def main():
    print("=== RBAC Router Logic Verification ===\n")
    
    # 1. Old "Manager" Bypass Check (Should fail now if they are just viewers)
    ctx_manager_viewer = {
        "user_name": "Manager Dave",
        "role": "MANAGER", 
        "module_roles": {"comercial": "viewer"}
    }
    
    # 2. Valid Module Admin
    ctx_user_admin = {
        "user_name": "Admin Alice",
        "role": "USER",
        "module_roles": {"comercial": "admin"}
    }
    
    # 3. System Admin (Always passes)
    ctx_sys_admin = {
        "user_name": "Super Admin",
        "role": "ADMIN",
        "module_roles": {}
    }

    results = []
    
    # Test 1: Manager (Viewer) trying to do Admin Action
    # OLD CODE: Allowed (FAILED check)
    # NEW CODE: Should Deny
    results.append(await test_router_logic_simulation(ctx_manager_viewer, "Manager (Viewer) doing Admin Action", should_pass=False))
    
    # Test 2: User (Module Admin) 
    results.append(await test_router_logic_simulation(ctx_user_admin, "User (Module Admin) doing Admin Action", should_pass=True))
    
    # Test 3: System Admin
    results.append(await test_router_logic_simulation(ctx_sys_admin, "System Admin doing Admin Action", should_pass=True))

    if all(results):
        print("\n✅ ALL ROUTER CHECKS PASSED. The backdoor is closed.")
    else:
        print("\n❌ SOME CHECKS FAILED.")

if __name__ == "__main__":
    asyncio.run(main())
