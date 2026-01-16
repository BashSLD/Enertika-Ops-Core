
import asyncio
from unittest.mock import MagicMock, AsyncMock
import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

# Import permissions logic
from core.permissions import require_module_access
from fastapi import HTTPException

async def test_rbac_check(module: str, context: dict, action_name: str, should_pass: bool):
    """
    Simulates a permissions check using the core logic.
    """
    print(f"Testing {action_name} [User Role: {context.get('role')}, Module Role: {context.get('module_roles', {}).get(module)}]...")
    
    # Simulate DB check usually done in dependencies
    # require_module_access returns a 'Depends' object which contains the call.
    # We need to extract the inner function or call the factory correctly to get the validator. 
    # In core/permissions.py, require_module_access returns Depends(_validate).
    # So we need to call _validate manually.
    
    checker_dependency = require_module_access(module, "admin") 
    validator_func = checker_dependency.dependency # Extract the async inner function

    try:
        await validator_func(context)
        if should_pass:
            print("✅ Access GRANTED (Expected)")
            return True
        else:
            print("❌ Access GRANTED (UNEXPECTED! Should be Forbidden)")
            return False
    except HTTPException as e:
        if not should_pass:
            print(f"✅ Access DENIED ({e.detail}) (Expected)")
            return True
        else:
            print(f"❌ Access DENIED (UNEXPECTED! Should be Granted)")
            return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

async def main():
    print("=== RBAC Verification Script ===\n")
    
    # Scenario 1: MANAGER user with 'viewer' role in Comercial (Should be DENIED for admin actions)
    # CURRENTLY THIS FAILS in the app because routers bypass this check manually.
    # This script tests the CORE logic. We will manually verify the router changes.
    
    ctx_manager_viewer = {
        "user_name": "Manager Dave",
        "role": "MANAGER", 
        "module_roles": {"comercial": "viewer", "admin": "viewer"}
    }
    
    # Scenario 2: Regular USER with 'admin' role in Comercial (Should be GRANTED)
    ctx_user_admin = {
        "user_name": "Admin Alice",
        "role": "USER",
        "module_roles": {"comercial": "admin"}
    }

    results = []
    
    # Test 1: Manager trying to access Admin-level module feature (via standard dependency)
    results.append(await test_rbac_check("comercial", ctx_manager_viewer, "Manager (Viewer) doing Admin Action", should_pass=False))
    
    # Test 2: User trying to access Admin-level module feature
    results.append(await test_rbac_check("comercial", ctx_user_admin, "User (Module Admin) doing Admin Action", should_pass=True))

    if all(results):
        print("\n✅ CORE PERMISSION LOGIC IS SOUND.")
        print("The vulnerabilities exist in the ROUTERS where manual `if role in ['MANAGER']` bypasses this logic.")
    else:
        print("\n❌ CORE PERMISSION LOGIC FAILED.")

if __name__ == "__main__":
    asyncio.run(main())
