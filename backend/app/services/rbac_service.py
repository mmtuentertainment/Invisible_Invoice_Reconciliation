"""
Role-Based Access Control (RBAC) service for authorization management.
Implements hierarchical roles, permissions, and resource-level access control.
"""

from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func
from pydantic import BaseModel

from app.models.auth import Role, UserRole, UserProfile


class Permission:
    """Permission constants for the system."""
    
    # System permissions
    SYSTEM_ADMIN = "system:admin"
    
    # Invoice permissions
    INVOICE_CREATE = "invoice:create"
    INVOICE_READ = "invoice:read"
    INVOICE_UPDATE = "invoice:update"
    INVOICE_DELETE = "invoice:delete"
    INVOICE_APPROVE = "invoice:approve"
    INVOICE_EXPORT = "invoice:export"
    INVOICE_ALL = "invoice:*"
    
    # Vendor permissions
    VENDOR_CREATE = "vendor:create"
    VENDOR_READ = "vendor:read"
    VENDOR_UPDATE = "vendor:update"
    VENDOR_DELETE = "vendor:delete"
    VENDOR_MANAGE = "vendor:manage"
    VENDOR_ALL = "vendor:*"
    
    # Report permissions
    REPORT_VIEW = "report:view"
    REPORT_CREATE = "report:create"
    REPORT_EXPORT = "report:export"
    REPORT_ALL = "report:*"
    
    # User management permissions
    USER_VIEW = "user:view"
    USER_CREATE = "user:create"
    USER_UPDATE = "user:update"
    USER_DELETE = "user:delete"
    USER_MANAGE = "user:manage"
    USER_ALL = "user:*"
    
    # Tenant permissions
    TENANT_VIEW = "tenant:view"
    TENANT_UPDATE = "tenant:update"
    TENANT_MANAGE = "tenant:manage"
    TENANT_ALL = "tenant:*"
    
    @classmethod
    def get_all_permissions(cls) -> Set[str]:
        """Get all defined permissions."""
        permissions = set()
        for attr_name in dir(cls):
            if not attr_name.startswith('_') and not callable(getattr(cls, attr_name)):
                attr_value = getattr(cls, attr_name)
                if isinstance(attr_value, str) and ':' in attr_value:
                    permissions.add(attr_value)
        return permissions
    
    @classmethod
    def get_resource_permissions(cls, resource: str) -> Set[str]:
        """Get all permissions for a specific resource."""
        all_permissions = cls.get_all_permissions()
        return {perm for perm in all_permissions if perm.startswith(f"{resource}:")}


class RoleTemplate:
    """Predefined role templates with default permissions."""
    
    ADMIN = {
        "name": "admin",
        "display_name": "Administrator",
        "description": "Full system access with all permissions",
        "permissions": {
            "system": ["*"],
            "invoice": ["*"],
            "vendor": ["*"],
            "report": ["*"],
            "user": ["*"],
            "tenant": ["*"]
        },
        "level": 0
    }
    
    MANAGER = {
        "name": "manager",
        "display_name": "Manager",
        "description": "Management access to invoices, vendors, and reports",
        "permissions": {
            "invoice": ["*"],
            "vendor": ["manage"],
            "report": ["*"],
            "user": ["view", "manage"]
        },
        "level": 1
    }
    
    PROCESSOR = {
        "name": "processor",
        "display_name": "Processor",
        "description": "Process invoices and manage vendor data",
        "permissions": {
            "invoice": ["create", "read", "update"],
            "vendor": ["create", "read", "update"],
            "report": ["view"]
        },
        "level": 2
    }
    
    VIEWER = {
        "name": "viewer",
        "display_name": "Viewer",
        "description": "Read-only access to invoices and reports",
        "permissions": {
            "invoice": ["read"],
            "vendor": ["read"],
            "report": ["view"]
        },
        "level": 3
    }
    
    @classmethod
    def get_all_templates(cls) -> List[Dict]:
        """Get all role templates."""
        return [
            cls.ADMIN,
            cls.MANAGER,
            cls.PROCESSOR,
            cls.VIEWER
        ]


class PermissionCheck(BaseModel):
    """Permission check result."""
    allowed: bool
    reason: Optional[str] = None
    required_permissions: List[str] = []
    user_permissions: List[str] = []


class RBACService:
    """Role-Based Access Control service for authorization management."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def check_permission(
        self,
        user_id: UUID,
        tenant_id: UUID,
        resource: str,
        action: str
    ) -> PermissionCheck:
        """
        Check if user has permission for specific resource and action.
        
        Args:
            user_id: User UUID
            tenant_id: Tenant UUID
            resource: Resource type (e.g., 'invoice', 'vendor')
            action: Action to perform (e.g., 'read', 'create', 'delete')
            
        Returns:
            PermissionCheck result
        """
        # Get user permissions
        user_permissions = await self.get_user_permissions(user_id, tenant_id)
        
        # Required permission patterns
        required_permissions = [
            f"{resource}:{action}",
            f"{resource}:*",
            "system:*"
        ]
        
        # Check if user has any of the required permissions
        for required_perm in required_permissions:
            if required_perm in user_permissions:
                return PermissionCheck(
                    allowed=True,
                    required_permissions=required_permissions,
                    user_permissions=user_permissions
                )
        
        return PermissionCheck(
            allowed=False,
            reason=f"Insufficient permissions for {action} on {resource}",
            required_permissions=required_permissions,
            user_permissions=user_permissions
        )
    
    async def check_multiple_permissions(
        self,
        user_id: UUID,
        tenant_id: UUID,
        permission_checks: List[Tuple[str, str]]  # List of (resource, action) tuples
    ) -> Dict[str, PermissionCheck]:
        """
        Check multiple permissions at once for efficiency.
        
        Args:
            user_id: User UUID
            tenant_id: Tenant UUID
            permission_checks: List of (resource, action) tuples to check
            
        Returns:
            Dictionary mapping "resource:action" to PermissionCheck
        """
        user_permissions = await self.get_user_permissions(user_id, tenant_id)
        results = {}
        
        for resource, action in permission_checks:
            check_key = f"{resource}:{action}"
            required_permissions = [
                f"{resource}:{action}",
                f"{resource}:*",
                "system:*"
            ]
            
            # Check if user has any of the required permissions
            allowed = any(perm in user_permissions for perm in required_permissions)
            
            results[check_key] = PermissionCheck(
                allowed=allowed,
                reason=None if allowed else f"Insufficient permissions for {action} on {resource}",
                required_permissions=required_permissions,
                user_permissions=user_permissions
            )
        
        return results
    
    async def get_user_permissions(
        self,
        user_id: UUID,
        tenant_id: UUID,
        include_inherited: bool = True
    ) -> List[str]:
        """
        Get all permissions for a user in a tenant.
        
        Args:
            user_id: User UUID
            tenant_id: Tenant UUID
            include_inherited: Whether to include permissions from parent roles
            
        Returns:
            List of permission strings
        """
        # Get all active roles for the user
        query = (
            select(Role)
            .join(UserRole, Role.id == UserRole.role_id)
            .where(
                and_(
                    UserRole.user_id == user_id,
                    UserRole.tenant_id == tenant_id,
                    UserRole.is_active == True,
                    Role.is_active == True,
                    or_(
                        UserRole.expires_at == None,
                        UserRole.expires_at > datetime.utcnow()
                    )
                )
            )
        )
        
        result = await self.db.execute(query)
        user_roles = result.scalars().all()
        
        permissions = set()
        
        for role in user_roles:
            # Add direct role permissions
            role_permissions = await self._extract_permissions_from_role(role)
            permissions.update(role_permissions)
            
            # Add inherited permissions if enabled
            if include_inherited:
                inherited_permissions = await self._get_inherited_permissions(role)
                permissions.update(inherited_permissions)
        
        return list(permissions)
    
    async def get_user_roles(
        self,
        user_id: UUID,
        tenant_id: UUID,
        active_only: bool = True
    ) -> List[Role]:
        """
        Get all roles assigned to a user.
        
        Args:
            user_id: User UUID
            tenant_id: Tenant UUID
            active_only: Whether to return only active roles
            
        Returns:
            List of Role objects
        """
        conditions = [
            UserRole.user_id == user_id,
            UserRole.tenant_id == tenant_id
        ]
        
        if active_only:
            conditions.extend([
                UserRole.is_active == True,
                Role.is_active == True,
                or_(
                    UserRole.expires_at == None,
                    UserRole.expires_at > datetime.utcnow()
                )
            ])
        
        query = (
            select(Role)
            .join(UserRole, Role.id == UserRole.role_id)
            .where(and_(*conditions))
            .order_by(Role.level.asc())
        )
        
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def assign_role_to_user(
        self,
        user_id: UUID,
        tenant_id: UUID,
        role_id: UUID,
        granted_by: UUID,
        expires_at: Optional[datetime] = None
    ) -> bool:
        """
        Assign a role to a user.
        
        Args:
            user_id: User UUID
            tenant_id: Tenant UUID
            role_id: Role UUID to assign
            granted_by: UUID of user granting the role
            expires_at: Optional expiration date
            
        Returns:
            True if role was assigned successfully
        """
        # Check if role exists and is active
        role_query = select(Role).where(
            and_(
                Role.id == role_id,
                Role.tenant_id == tenant_id,
                Role.is_active == True
            )
        )
        role_result = await self.db.execute(role_query)
        role = role_result.scalar_one_or_none()
        
        if not role:
            return False
        
        # Check if user already has this role
        existing_query = select(UserRole).where(
            and_(
                UserRole.user_id == user_id,
                UserRole.tenant_id == tenant_id,
                UserRole.role_id == role_id,
                UserRole.is_active == True
            )
        )
        existing_result = await self.db.execute(existing_query)
        existing_assignment = existing_result.scalar_one_or_none()
        
        if existing_assignment:
            return False  # Role already assigned
        
        # Create new role assignment
        user_role = UserRole(
            tenant_id=tenant_id,
            user_id=user_id,
            role_id=role_id,
            granted_by=granted_by,
            expires_at=expires_at,
            granted_at=datetime.utcnow(),
            is_active=True
        )
        
        self.db.add(user_role)
        await self.db.commit()
        
        return True
    
    async def revoke_role_from_user(
        self,
        user_id: UUID,
        tenant_id: UUID,
        role_id: UUID,
        revoked_by: UUID
    ) -> bool:
        """
        Revoke a role from a user.
        
        Args:
            user_id: User UUID
            tenant_id: Tenant UUID
            role_id: Role UUID to revoke
            revoked_by: UUID of user revoking the role
            
        Returns:
            True if role was revoked successfully
        """
        # Find active role assignment
        query = select(UserRole).where(
            and_(
                UserRole.user_id == user_id,
                UserRole.tenant_id == tenant_id,
                UserRole.role_id == role_id,
                UserRole.is_active == True
            )
        )
        
        result = await self.db.execute(query)
        user_role = result.scalar_one_or_none()
        
        if not user_role:
            return False
        
        # Revoke the role
        user_role.is_active = False
        user_role.revoked_at = datetime.utcnow()
        user_role.revoked_by = revoked_by
        
        await self.db.commit()
        
        return True
    
    async def create_role(
        self,
        tenant_id: UUID,
        name: str,
        display_name: str,
        description: str,
        permissions: Dict[str, List[str]],
        created_by: UUID,
        parent_role_id: Optional[UUID] = None,
        level: int = 0
    ) -> Optional[Role]:
        """
        Create a new role.
        
        Args:
            tenant_id: Tenant UUID
            name: Role name (must be unique within tenant)
            display_name: Human-readable role name
            description: Role description
            permissions: Permissions dictionary
            created_by: UUID of user creating the role
            parent_role_id: Optional parent role for inheritance
            level: Role level in hierarchy
            
        Returns:
            Created Role object or None if creation failed
        """
        # Check if role name already exists
        existing_query = select(Role).where(
            and_(
                Role.tenant_id == tenant_id,
                Role.name == name
            )
        )
        existing_result = await self.db.execute(existing_query)
        if existing_result.scalar_one_or_none():
            return None  # Role name already exists
        
        # Validate parent role if specified
        if parent_role_id:
            parent_query = select(Role).where(
                and_(
                    Role.id == parent_role_id,
                    Role.tenant_id == tenant_id,
                    Role.is_active == True
                )
            )
            parent_result = await self.db.execute(parent_query)
            parent_role = parent_result.scalar_one_or_none()
            if not parent_role:
                return None  # Parent role doesn't exist
        
        # Create new role
        role = Role(
            tenant_id=tenant_id,
            name=name,
            display_name=display_name,
            description=description,
            permissions=permissions,
            parent_role_id=parent_role_id,
            level=level,
            is_system_role=False,
            is_active=True,
            created_by=created_by,
            created_at=datetime.utcnow()
        )
        
        self.db.add(role)
        await self.db.commit()
        
        return role
    
    async def update_role_permissions(
        self,
        role_id: UUID,
        tenant_id: UUID,
        permissions: Dict[str, List[str]],
        updated_by: UUID
    ) -> bool:
        """
        Update role permissions.
        
        Args:
            role_id: Role UUID
            tenant_id: Tenant UUID
            permissions: New permissions dictionary
            updated_by: UUID of user making the update
            
        Returns:
            True if update was successful
        """
        query = select(Role).where(
            and_(
                Role.id == role_id,
                Role.tenant_id == tenant_id,
                Role.is_system_role == False  # Don't allow updating system roles
            )
        )
        
        result = await self.db.execute(query)
        role = result.scalar_one_or_none()
        
        if not role:
            return False
        
        role.permissions = permissions
        role.updated_by = updated_by
        role.updated_at = datetime.utcnow()
        
        await self.db.commit()
        
        return True
    
    async def get_tenant_roles(
        self,
        tenant_id: UUID,
        include_system: bool = True,
        active_only: bool = True
    ) -> List[Role]:
        """
        Get all roles for a tenant.
        
        Args:
            tenant_id: Tenant UUID
            include_system: Whether to include system roles
            active_only: Whether to return only active roles
            
        Returns:
            List of Role objects
        """
        conditions = [Role.tenant_id == tenant_id]
        
        if not include_system:
            conditions.append(Role.is_system_role == False)
        
        if active_only:
            conditions.append(Role.is_active == True)
        
        query = (
            select(Role)
            .where(and_(*conditions))
            .order_by(Role.level.asc(), Role.name.asc())
        )
        
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def initialize_default_roles(self, tenant_id: UUID) -> List[Role]:
        """
        Initialize default system roles for a tenant.
        
        Args:
            tenant_id: Tenant UUID
            
        Returns:
            List of created roles
        """
        created_roles = []
        
        for template in RoleTemplate.get_all_templates():
            # Check if role already exists
            existing_query = select(Role).where(
                and_(
                    Role.tenant_id == tenant_id,
                    Role.name == template["name"]
                )
            )
            existing_result = await self.db.execute(existing_query)
            
            if not existing_result.scalar_one_or_none():
                role = Role(
                    tenant_id=tenant_id,
                    name=template["name"],
                    display_name=template["display_name"],
                    description=template["description"],
                    permissions=template["permissions"],
                    level=template["level"],
                    is_system_role=True,
                    is_active=True,
                    created_at=datetime.utcnow()
                )
                
                self.db.add(role)
                created_roles.append(role)
        
        await self.db.commit()
        return created_roles
    
    # Private helper methods
    
    async def _extract_permissions_from_role(self, role: Role) -> Set[str]:
        """Extract permission strings from role permissions."""
        permissions = set()
        
        for resource, actions in role.permissions.items():
            if isinstance(actions, list):
                for action in actions:
                    permissions.add(f"{resource}:{action}")
            elif actions == "*":
                permissions.add(f"{resource}:*")
        
        return permissions
    
    async def _get_inherited_permissions(self, role: Role) -> Set[str]:
        """Get permissions inherited from parent roles."""
        permissions = set()
        
        if role.parent_role_id:
            parent_query = select(Role).where(Role.id == role.parent_role_id)
            parent_result = await self.db.execute(parent_query)
            parent_role = parent_result.scalar_one_or_none()
            
            if parent_role:
                # Get parent permissions
                parent_permissions = await self._extract_permissions_from_role(parent_role)
                permissions.update(parent_permissions)
                
                # Recursively get inherited permissions
                inherited_permissions = await self._get_inherited_permissions(parent_role)
                permissions.update(inherited_permissions)
        
        return permissions


# Helper function to create RBAC service with database session
async def get_rbac_service(db: AsyncSession) -> RBACService:
    """Get RBAC service instance with database session."""
    return RBACService(db)