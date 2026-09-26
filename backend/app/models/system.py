"""
系统用户与权限模型
包含：sys_user, sys_role, sys_permission
单角色设计：sys_user.role_id 直接外键关联 sys_role.id

主键类型用 `PK_TYPE`（本模块对团队版的唯一偏离），原因见 core/database.py。

本模块（移动端预约与通知）不直接使用这三张表；引入它们是因为
`reserve_order.user_id` / `notify_message.receiver_id` 声明了指向 `sys_user.id` 的
真外键，SQLAlchemy 要求被引用表同时注册在 metadata 中。
"""
from datetime import datetime

from sqlalchemy import BigInteger, String, Integer, DateTime, JSON, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import PK_TYPE, Base


class SysUser(Base):
    """用户表：系统使用者（C端用户、管理员、运维）"""
    __tablename__ = "sys_user"

    id: Mapped[int] = mapped_column(PK_TYPE, primary_key=True, autoincrement=True, comment="主键")
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="登录名")
    password: Mapped[str] = mapped_column(String(255), nullable=False, comment="密码哈希")

    # 单角色：直接外键关联 sys_role
    role_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_role.id"), nullable=True, comment="角色ID"
    )

    avatar: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="头像地址")
    status: Mapped[int] = mapped_column(Integer, default=1, nullable=False, comment="状态：1正常，0禁用")

    create_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), comment="创建时间"
    )
    update_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间"
    )

    # 多对一：一个用户属于一个角色
    role: Mapped["SysRole"] = relationship(back_populates="users")


class SysRole(Base):
    """角色表"""
    __tablename__ = "sys_role"

    id: Mapped[int] = mapped_column(PK_TYPE, primary_key=True, autoincrement=True, comment="主键")
    role_name: Mapped[str] = mapped_column(String(64), nullable=False, comment="角色名称")
    permissions: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="权限集合，JSON数组")
    create_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), comment="创建时间"
    )

    # 一对多：一个角色可以被多个用户拥有
    users: Mapped[list["SysUser"]] = relationship(back_populates="role")


class SysPermission(Base):
    """权限表（树形结构，用于菜单和接口权限）"""
    __tablename__ = "sys_permission"

    id: Mapped[int] = mapped_column(PK_TYPE, primary_key=True, autoincrement=True, comment="主键")
    permission_name: Mapped[str] = mapped_column(String(64), nullable=False, comment="权限名称")
    permission_code: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False, comment="权限编码，如 user:add"
    )
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="父权限ID，树形结构"
    )
