"""
Copyright 2023-present fretgfr

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from __future__ import annotations

import base64
import datetime
import io
import mimetypes
import os
from typing import Any, Dict, List, Literal, Optional, Sequence, Type, Union

from casefy import camelcase
from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, computed_field, field_validator

from .enums import FileSearchField, FileSearchSort, OAuthProviderType, Order, QuotaType, RecentFilesFilter, UserRole
from .http import HTTPClient, Route
from .utils import (
    MISSING,
    build_avatar_payload,
    generate_quota_payload,
    guess_mimetype_by_magicnumber,
    parse_iso_timestamp,
)

__all__ = (
    "ZiplineModel",
    "File",
    "Folder",
    "User",
    "InviteUser",
    "Invite",
    "TagFile",
    "Tag",
    "URL",
    "UploadFile",
    "UploadResponse",
    "FileData",
    "PartialQuota",
    "UserQuota",
    "OAuthProvider",
    "Thumbnail",
    "UserViewSettings",
    "ServerVersionInfo",
    "UserStats",
    "UserFilesResponse",
    "Avatar",
)

JSON = Union[Dict[str, Any], List[Any], int, str, float, bool, Type[None]]


class ZiplineModel(BaseModel):
    """
    Base model class used to represent data structures returned from the Zipline API.
    """

    model_config = ConfigDict(
        alias_generator=camelcase,
        arbitrary_types_allowed=True,
        populate_by_name=True,
        validate_default=True,
    )

    @field_validator("created_at", "deletes_at", "updated_at", mode="before", check_fields=False)
    @classmethod
    def _timestamp_validator(cls, value: Any) -> Any:
        if isinstance(value, str):
            return parse_iso_timestamp(value)
        if isinstance(value, datetime):
            return value
        raise ValueError(f"Invalid datetime passed! {value}")

    def __json__(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class _ZiplineClientModel(ZiplineModel):
    http: HTTPClient = Field(exclude=True)


class File(_ZiplineClientModel):
    """
    Represents a file stored on Zipline.

    .. container:: operations

        .. describe:: str(x)

            Returns the full url of the file.

    Attributes
    ----------
    id: :class:`str`
        The internal id of the file in Zipline.
    created_at: :class:`datetime.datetime`
        When the file was created.
    updated_at: :class:`datetime.datetime`
        When the file was last updated.
    deletes_at: Optional[:class:`datetime.datetime`]
        The scheduled deletion time of the file, if applicable.
    favorite: :class:`bool`
        Whether the file is favorited.
    original_name: Optional[:class:`str`]
        The original name of the file, if stored.
    name: :class:`str`
        The name of the file.
    size: :class:`int`
        The size of the file in bytes.
    type: :class:`str`
        The MIME type of the file.
    views: :class:`int`
        The number of times the file has been viewed.
    max_views: Optional[:class:`int`]
        The maximum number of times the file can be viewed before being removed, if applicable.
    password: Optional[Union[:class:`str`, :class:`bool`]]
        Whether the file is password protected.
    folder_id: Optional[:class:`str`]
        The id of the :class:`~zipline.models.Folder` that this file resides in, if applicable.
    thumbnail: Optional[:class:`~zipline.models.Thumbnail`]
        The thumbnail of the file, if available.
    tags: List[:class:`~zipline.models.Tag`]
        The tags applied to the file.
    url: Optional[:class:`str`]
        The url of this file, if given.
    """

    id: str
    created_at: datetime.datetime
    updated_at: datetime.datetime
    deletes_at: Optional[datetime.datetime] = None
    favorite: bool
    original_name: Optional[str] = None
    name: str
    size: int
    type: str
    views: int
    max_views: Optional[int] = None
    password: Optional[Union[str, bool]] = None
    folder_id: Optional[str] = None
    thumbnail: Optional[Thumbnail] = None
    tags: Optional[List[Tag]] = None
    url: Optional[str] = None

    @field_validator("tags", mode="before")
    @classmethod
    def _validate_tags(cls, value: Any, info: ValidationInfo) -> Optional[List[Tag]]:
        return [Tag(http=info.data["http"], **tag_data) for tag_data in value] if value else None

    def __str__(self) -> str:
        return self.full_url

    @computed_field  # includes this in json output
    @property
    def full_url(self) -> str:
        """
        Returns
        -------
        :class:`str`
            The full url of this file.
        """
        if self.url and (self.url.startswith("http://") or self.url.startswith("https://")):
            url = self.url
        else:
            url = f"{self.http.base_url}{self.url}"

        return url

    @computed_field  # includes this in json output
    @property
    def thumbnail_url(self) -> Optional[str]:
        """
        Returns
        -------
        Optional[:class:`str`]
            The full url for the thumbnail image, if available.
        """
        if not self.thumbnail:
            return None

        return f"{self.http.base_url}/{self.thumbnail.path}"

    def is_password_protected(self) -> bool:
        """
        Returns the password protection status of this file.

        Returns
        -------
        :class:`bool`
        """
        return self.password is not None

    async def download_password_protected(self, password: str) -> bytes:
        """|coro|

        Download this file if password protected.

        Parameters
        ----------
        password: :class:`str`
            The password to use when accessing this file.

        Returns
        -------
        :class:`bytes`
            The content of this file.
        """
        params = {"pw": password}
        r = Route("GET", self.full_url)
        return await self.http.request(r, params=params)

    async def refresh(self) -> File:
        """|coro|

        Retrieve an updated instance of this file.

        Returns
        -------
        :class:`~zipline.models.File`
            A new instance with the latest information about this file.
        """
        r = Route("GET", f"/api/user/files/{self.id}")
        data = await self.http.request(r)
        return File(http=self.http, **data)

    async def delete(self) -> File:
        """|coro|

        Delete this file.

        Returns
        -------
        :class:`~zipline.models.File`
            A new instance with the latest information about this file.
        """
        r = Route("DELETE", f"/api/user/files/{self.id}")
        data = await self.http.request(r)
        return File(http=self.http, **data)

    async def edit(
        self,
        *,
        favorite: Optional[bool] = None,
        tags: Optional[Sequence[Tag]] = None,
        max_views: Optional[int] = None,
        original_name: Optional[str] = None,
        password: Optional[str] = None,
        type: Optional[str] = None,
    ) -> File:
        """|coro|

        Update this file.

        Parameters
        ----------
        favorite: Optional[:class:`bool`]
            The new favorite status of the file, if given.
        tags: Optional[Sequence[:class:`~zipline.models.Tag`]]
            Tag to apply to this file, if given.
        max_views: Optional[:class:`int`]
            The new maximum views of the file, if given.
        original_name: Optional[:class:`str`]
            The new original name of the file, if given.
        password: Optional[:class:`str`]
            The new password for the file, if given.
        type: Optional[:class:`str`]
            The new MIME type for the file, if given.

            .. warning::

                Misuse of this parameter can cause files to display incorrectly or fail outright.

        Returns
        -------
        :class:`~zipline.models.File`
            The updated file.
        """
        payload = {}

        if favorite:
            payload["favorite"] = favorite
        if tags:
            payload["tags"] = [t.id for t in tags]
        if max_views:
            payload["maxViews"] = max_views
        if original_name:
            payload["originalName"] = original_name
        if password:
            payload["password"] = password
        if type:
            payload["type"] = type

        r = Route("PATCH", f"/api/user/files/{self.id}")
        data = await self.http.request(r, json=payload)
        return File(http=self.http, **data)

    async def add_favorite(self) -> File:
        """|coro|

        Favorite this file.

        Returns
        -------
        :class:`~zipline.models.File`
            A new instance with the latest information about this file.

        Raises
        ------
        ValueError
            The file is already favorited.
        """
        if self.favorite:
            raise ValueError("this file is already favorited.")

        payload = {"favorite": True}
        r = Route("PATCH", f"/api/user/files/{self.id}")
        data = await self.http.request(r, json=payload)
        return File(http=self.http, **data)

    async def remove_favorite(self) -> File:
        """|coro|

        Unfavorite this file.

        Returns
        -------
        :class:`~zipline.models.File`
            A new instance with the latest information about this file.

        Raises
        ------
        ValueError
            The file is already favorited.
        """
        if not self.favorite:
            raise ValueError("this file is already not favorited.")

        payload = {"favorite": False}
        r = Route("PATCH", f"/api/user/files/{self.id}")
        data = await self.http.request(r, json=payload)
        return File(http=self.http, **data)

    async def remove_from_folder(self):
        """|coro|

        Remove this file from it's current :class:`~zipline.models.Folder`.
        """
        payload = {"delete": "file", "id": self.id}
        r = Route("DELETE", f"/api/user/folders/{self.folder_id}")
        await self.http.request(r, json=payload)

    async def read(self) -> bytes:
        """|coro|

        Read the content of this file into memory.

        Returns
        -------
        :class:`bytes`
            The content of this file.
        """
        if self.url and (self.url.startswith("http://") or self.url.startswith("https://")):
            url = self.url
        else:
            url = f"{self.http.base_url}{self.url}"

        r = Route("GET", url)
        return await self.http.request(r)


class Folder(_ZiplineClientModel):
    """
    Represents a Folder on Zipline.

    .. container:: operations

        .. describe:: str(x)

            Returns the full url of the folder.

    Attributes
    ----------
    id: :class:`str`
        The id of the folder.
    created_at: :class:`datetime.datetime`
        When the folder was created.
    updated_at: :class:`datetime.datetime`
        When the folder was last updated.
    name: :class:`str`
        The name of the folder.
    public: :class:`bool`
        Whether the folder is public.
    files: Optional[List[:class:`~zipline.models.File`]]
        The files contained in the folder, if available.
    user: Optional[:class:`~zipline.models.User`]
        The user this folder belongs to, if available.
    user_id: :class:`str`
        The id of the user this folder belongs to.
    """

    id: str
    created_at: datetime.datetime
    updated_at: datetime.datetime
    name: str
    public: bool
    files: Optional[List[File]] = None
    user: Optional[User] = None
    user_id: str

    @field_validator("files", mode="before")
    @classmethod
    def _validate_files(cls, value: Any, info: ValidationInfo) -> Optional[List[File]]:
        return [File(http=info.data["http"], **file_data) for file_data in value] if value else None

    @field_validator("user", mode="before")
    @classmethod
    def _validate_user(cls, value: Any, info: ValidationInfo) -> Optional[User]:
        return User(http=info.data["http"], **value) if value else None

    def __str__(self) -> str:
        return self.full_url

    @property
    def full_url(self) -> str:
        """A :class:`str` with the URL of the folder."""
        return f"{self.http.base_url}/folder/{self.id}"

    async def refresh(self) -> Folder:
        """|coro|

        Retrieve an updated instance of this object.

        Returns
        -------
        :class:`~zipline.models.Folder`
            A new instance with the latest information about this folder.
        """
        r = Route("GET", f"/api/user/folders/{self.id}")
        data = await self.http.request(r)
        return Folder(http=self.http, **data)

    async def delete(self) -> Folder:
        """|coro|

        Delete this folder.

        Returns
        -------
        :class:`~zipline.models.Folder`
            A new instance with the latest information about this folder.
        """
        payload = {"delete": "folder"}
        r = Route("DELETE", f"/api/user/folders/{self.id}")
        data = await self.http.request(r, json=payload)
        return Folder(http=self.http, **data)

    async def edit(self, *, name: str) -> Folder:
        """|coro|

        Edit this folder.

        Parameters
        ----------
        name: :class:`str`
            The new name of this folder.

        Returns
        -------
        :class:`~zipline.models.Folder`
            The updated folder.
        """
        payload = {"name": name}
        r = Route("PATCH", f"/api/user/folders/{self.id}")
        data = await self.http.request(r, json=payload)
        return Folder(http=self.http, **data)

    async def remove_file(self, file: Union[File, str], /) -> Folder:
        """|coro|

        Remove a file from this folder.

        Parameters
        ----------
        file: Union[:class:`~zipline.models.File`, :class:`str`]
            The file or file id to remove from this folder.

        Returns
        -------
        :class:`~zipline.models.Folder`
            A new instance with the latest information about this folder.
        """
        payload = {
            "delete": "file",
            "id": file.id if isinstance(file, File) else file,
        }

        r = Route("DELETE", f"/api/user/folders/{self.id}")
        data = await self.http.request(r, json=payload)
        return Folder(http=self.http, **data)

    async def add_file(self, file: Union[File, str], /) -> Folder:
        """|coro|

        Add a file to this folder.

        Parameters
        ----------
        file: Union[:class:`~zipline.models.File`, :class:`str`]
            The file or file id to add to this folder.

        Returns
        -------
        :class:`~zipline.models.Folder`
            A new instance with the latest information about this folder.
        """
        payload = {"id": file.id if isinstance(file, File) else file}

        r = Route("PUT", f"/api/user/folders/{self.id}")
        data = await self.http.request(r, json=payload)
        return Folder(http=self.http, **data)

    async def add_files(self, files: Sequence[Union[File, str]], /) -> Folder:
        """|coro|

        Add multiple files to this folder.

        Parameters
        ----------
        files: Sequence[Union[:class:`~zipline.models.File`, :class:`str`]]
            The files or file ids to add to this folder.

        Returns
        -------
        :class:`~zipline.models.Folder`
            A new instance with the latest information about this folder.
        """
        file_ids = [file.id if isinstance(file, File) else file for file in files]

        payload = {
            "files": file_ids,
            "folder": self.id,
        }

        r = Route("PATCH", "/api/user/files/transaction")
        data = await self.http.request(r, json=payload)
        return Folder(http=self.http, **data)


class User(_ZiplineClientModel):
    """
    Represents a Zipline user.

    .. container:: operations

        .. describe:: str(x)

            Returns the username of this user.

    Attributes
    ----------
    id: :class:`str`
        The id of this user.
    username: :class:`str`
        The username of this user.
    created_at: :class:`datetime.datetime`
        When this user was created or registered.
    updated_at: :class:`datetime.datetime`
        The last time this user was updated.
    role: :class:`~zipline.enums.UserRole`
        The role of this user.
    view: :class:`~zipline.models.UserViewSettings`
        Custom view info for this user.
    sessions: List[:class:`str`]
        List of session ids this user has open.
    oauth_providers: List[:class:`~zipline.models.OAuthProvider`]
        OAuth providers registered for this user.
    totp_secret: Optional[:class:`str`]
        The user's timed one-time password secret, if available.
    passkeys: List[:class:`~zipline.models.UserPasskey`]
        Passkeys registered for this user.
    quota: Optional[:class:`~zipline.models.UserQuota`]
        The quota this user has, if applicable.
    avatar: Optional[:class:`~zipline.models.Avatar`]
        The user's avatar information, if available.
    password: Optional[:class:`str`]
        Password information for this user, if available.
    token: Optional[:class:`str`]
        The user's token.
    """

    id: str
    username: str
    created_at: datetime.datetime
    updated_at: datetime.datetime
    role: UserRole
    view: Optional[UserViewSettings] = None
    sessions: List[str] = Field(default_factory=list)
    oauth_providers: List[OAuthProvider] = Field(default_factory=list)
    totp_secret: Optional[str] = None
    passkeys: Optional[List[UserPasskey]] = None
    quota: Optional[UserQuota] = None
    avatar: Optional[Avatar] = None
    password: Optional[str] = None
    token: Optional[str] = None

    @field_validator("quota", mode="before")
    @classmethod
    def _validate_quota(cls, value: Any, info: ValidationInfo) -> Optional[UserQuota]:
        return UserQuota(http=info.data["http"], **value) if value else None

    def __str__(self) -> str:
        return self.username

    async def refresh(self) -> User:
        """|coro|

        Retrieve the latest information about this user.

        Returns
        -------
        :class:`~zipline.models.User`
            A new instance with the latest information about this user.
        """
        r = Route("GET", f"/api/users/{self.id}")
        data = await self.http.request(r)
        return User(http=self.http, **data)

    async def edit(
        self,
        *,
        username: Optional[str] = None,
        password: Optional[str] = None,
        avatar: Optional[Avatar] = None,
        role: Optional[UserRole] = None,
        quota: Optional[Union[UserQuota, PartialQuota]] = None,
    ) -> User:
        """|coro|

        Edit this user.

        Parameters
        ----------
        username: Optional[:class:`str`]
            The new username for this user, if given.
        password: Optional[:class:`str`]
            The new password for this user, if given.
        avatar: Optional[:class:`~zipline.models.Avatar`]
            The new avatar for this user, if given.
        role: Optional[:class:`~zipline.enums.UserRole`]
            The new role for this user, if given.
        quota: Optional[Union[:class:`~zipline.models.UserQuota`, :class:`~zipline.models.PartialQuota`]]
            The new quota for this user, if given.

        Returns
        -------
        :class:`~zipline.models.User`
            The updated user.
        """
        payload = {}

        if username:
            payload["username"] = username
        if password:
            payload["password"] = password
        if avatar:
            payload["avatar"] = avatar.to_payload_str()
        if role:
            payload["role"] = role.value
        if quota:
            payload["quota"] = quota._to_dict()

        r = Route("PATCH", f"/api/users/{self.id}")
        data = await self.http.request(r, json=payload)
        return User(http=self.http, **data)

    async def delete(self, *, remove_data: bool = True) -> User:
        """|coro|

        Delete this user.

        Parameters
        ----------
        remove_data: :class:`bool`
            Whether this user's files and urls should be deleted as well, by default True

        Returns
        -------
        :class:`~zipline.models.User`
            A new instance with the latest information about this user.

        Raises
        ------
        BadRequest
            Something went wrong handling the request.
        Forbidden
            You are not an administrator and cannot use this method.
        """
        payload = {"delete": remove_data}
        r = Route("DELETE", f"/api/users/{self.id}")
        data = await self.http.request(r, json=payload)
        return User(http=self.http, **data)

    async def get_files(
        self,
        *,
        page: int = 1,
        per_page: int = 10,
        filter: RecentFilesFilter = RecentFilesFilter.all,
        favorite: Optional[bool] = None,
        sort_by: FileSearchSort = FileSearchSort.created_at,
        order: Order = Order.asc,
        search_field: FileSearchField = FileSearchField.file_name,
        search_query: Optional[str] = None,
    ) -> UserFilesResponse:
        """|coro|

        Get files belonging to this user.

        .. note::

            This route requires that you have an account with the Super Admin type.

        Parameters
        ----------
        page: :class:`int`
            The page of files to get.
        per_page: :class:`int`
            How many files should be returned per page.
        filter: :class:`~zipline.enums.RecentFilesFilter`
            A filter to apply to the files retrieved.
        favorite: Optional[:class:`bool`]
            Whether to search for only favorited or unfavorited files. None for all files.
        sort_by: :class:`~zipline.enums.FileSearchSort`
            How the results should be sorted. Defaults to creation datetime.
        order: :class:`~zipline.enums.Order`
            How the results should be ordered. Defaults to ascending.
        search_field: :class:`~zipline.enums.FileSearchField`
            What file attribute to search by. Defaults to file name.
        search_query: Optional[:class:`str`]
            The query to use in the search.

        Returns
        -------
        :class:`~zipline.models.UserFilesResponse`
            The requested search results.
        """
        params = {"sortBy": sort_by.value, "order": order.value, "id": self.id}

        if page:
            params["page"] = str(page)
        if per_page:
            params["perpage"] = str(per_page)
        if filter:
            params["filter"] = filter.value
        if favorite:
            params["favorite"] = "true" if favorite else "false"
        if search_field:
            params["searchField"] = search_field.value
        if search_query:
            params["searchQuery"] = search_query

        r = Route("GET", "/api/user/files")
        data = await self.http.request(r, params=params)
        return UserFilesResponse(**data)


class InviteUser(_ZiplineClientModel):
    """
    User information provided with an :class:`~zipline.models.Invite`.

    .. note::

        This can be resolved to a :class:`~zipline.models.User` via :meth:`resolve`.

    .. container:: operations

        .. describe:: str(x)

            Returns the full url of the file.

    Attributes
    ----------
    username: :class:`str`
        The username of the invite owner.
    id: :class:`str`
        The id of the invite owner.
    role: :class:`~zipline.enums.UserRole`
        The invite owner's account type.
    """

    username: str
    id: str
    role: UserRole

    def __str__(self) -> str:
        return self.username

    async def resolve(self) -> User:
        """|coro|

        Resolve this object to a full :class:`~zipline.models.User`.

        Returns
        -------
        :class:`~zipline.models.User`
            The fully fledged user object.
        """
        r = Route("GET", f"/api/users/{self.id}")
        data = await self.http.request(r)
        return User(http=self.http, **data)


class Invite(_ZiplineClientModel):
    """
    Represents an invite to a Zipline instance.

    .. container:: operations

        .. describe:: str(x)

            Returns the url of the invite.

    Attributes
    ----------
    id: :class:`str`
        The internal id of the invite.
    created_at: :class:`datetime.datetime`
        When this invite was created.
    updated_at: :class:`datetime.datetime`
        When this invite was last updated.
    expires_at: Optional[:class:`datetime.datetime`]
        When this invite expires, if applicable.
    code: :class:`str`
        The code for this invite.
    uses: :class:`int`
        The number of times this invite has been used.
    max_uses: Optional[:class:`int`]
        The number of times this invite can be used before it's no longer valid, if applicable.
    inviter: :class:`~zipline.models.InviteUser`
        The user that is attributed to the creation of this invite.
    inviter_id: :class:`str`
        The id of the user attributed to the creation of this invite.
    """

    id: str
    created_at: datetime.datetime
    updated_at: datetime.datetime
    expires_at: Optional[datetime.datetime] = None
    code: str
    uses: int
    max_uses: Optional[int] = None
    inviter: InviteUser
    inviter_id: str

    @field_validator("inviter", mode="before")
    @classmethod
    def _validate_inviter(cls, value: Any, info: ValidationInfo) -> InviteUser:
        return InviteUser(http=info.data["http"], **value)

    def __str__(self) -> str:
        return self.url

    @property
    def url(self) -> str:
        """
        Returns
        -------
        :class:`str`
            The full url of this invite.
        """
        return f"{self.http.base_url}/auth/register?code={self.code}"

    async def delete(self) -> Invite:
        """|coro|

        Delete this invite.

        Returns
        -------
        :class:`~zipline.models.Invite`
            A new instance with the latest information about this invite.
        """
        r = Route("DELETE", f"/api/auth/invites/{self.id}")
        data = await self.http.request(r)
        return Invite(http=self.http, **data)

    async def refresh(self) -> Invite:
        """|coro|

        Retrieve updated information about this invite.

        Returns
        -------
        :class:`~zipline.models.Invite`
            A new instance with the latest information about this invite.
        """
        r = Route("GET", f"/api/auth/invites/{self.id}")
        data = await self.http.request(r)
        return Invite(http=self.http, **data)


class TagFile(_ZiplineClientModel):
    """
    Partial file given with Tags.

    .. note::

        This can be resolved to a :class:`~zipline.models.File` via :meth:`resolve`.

    Attributes
    ----------
    id: :class:`str`
        The internal id of the :class:`~zipline.models.File` represented.
    """

    id: str

    async def resolve(self) -> File:
        """|coro|

        Retrieve the whole file associated with this partial data.

        Returns
        -------
        :class:`~zipline.models.File`
            The fully fledged file object.
        """
        r = Route("GET", f"/api/user/files/{self.id}")  # NOTE: Undocumented // Not officially used in the frontend.
        data = await self.http.request(r)
        return File(http=self.http, **data)


class Tag(_ZiplineClientModel):
    """
    Represents a tag on Zipline.

    .. container:: operations

        .. describe:: str(x)

            Returns the name of this tag.

    Attributes
    ----------
    id: :class:`str`
        The internal id of the tag.
    created_at: :class:`datetime.datetime`
        When this tag was created.
    updated_at: :class:`datetime.datetime`
        When this tag was last updated.
    name: :class:`str`
        The name of this tag.
    color: :class:`str`
        The color associated with this tag.
    files: Optional[List[:class:`~zipline.models.TagFile`]]
        Partial files associated with this tag, if available.
    """

    id: str
    created_at: datetime.datetime
    updated_at: datetime.datetime
    name: str
    color: str
    files: Optional[List[TagFile]] = None

    @field_validator("files", mode="before")
    @classmethod
    def _validate_files(cls, value: Any, info: ValidationInfo) -> Optional[List[TagFile]]:
        return [TagFile(http=info.data["http"], **file_data) for file_data in value] if value else None

    def __str__(self) -> str:
        return self.name

    async def edit(self, color: Optional[str] = None, name: Optional[str] = None) -> Tag:
        """|coro|

        Edit this tag.

        Parameters
        ----------
        color: Optional[:class:`str`]
            The new color of the tag, if given.

            .. note::

                Must be in hex format with preceding #

                ex. #rrggbb
        name: Optional[:class:`str`]
            The new name of the tag, if given.

        Returns
        -------
        :class:`~zipline.models.Tag`
            The updated tag.
        """
        payload = {}

        if color:
            payload["color"] = color
        if name:
            payload["name"] = name

        r = Route("PATCH", f"/api/user/tags/{self.id}")
        data = await self.http.request(r, json=payload)
        return Tag(http=self.http, **data)

    async def delete(self) -> Tag:
        """|coro|

        Delete this tag.

        Returns
        -------
        :class:`~zipline.models.Tag`
            A new instance with the latest information about this tag.
        """
        r = Route("DELETE", f"/api/user/tags/{self.id}")
        data = await self.http.request(r)
        return Tag(http=self.http, **data)

    async def refresh(self) -> Tag:
        """|coro|

        Retrieve the latest information about this tag.

        Returns
        -------
        :class:`~zipline.models.Tag`
            A new instance with the latest information about this tag.
        """
        r = Route("GET", f"/api/user/tags/{self.id}")
        data = await self.http.request(r)
        return Tag(http=self.http, **data)


class URL(_ZiplineClientModel):
    """
    Represents a shortened url on Zipline.

    .. container:: operations

        .. describe:: str(x)

            Returns the link to use the URL.

    Attributes
    ----------
    id: :class:`str`
        The internal id of the url.
    created_at: :class:`datetime.datetime`
        When this url was created.
    updated_at: :class:`datetime.datetime`
        When this url was last updated.
    code: :class:`str`
        The url code.
    vanity: Optional[:class:`str`]
        The vanity code of this url, if applicable.
    destination: :class:`str`
        The url this url redirects to.
    views: :class:`int`
        The number of times this url has been used.
    max_views: Optional[:class:`int`]
        The maximum number of times this url can be used, if applicable.
    password: Optional[:class:`str`]
        The password required to use this url.
    enabled: :class:`bool`
        Whether this url is active for use.
    user: Optional[:class:`~zipline.models.User`]
        The user this url belongs to.
    user_id: :class:`str`
        The id of the user this url belongs to.
    """

    id: str
    created_at: datetime.datetime
    updated_at: datetime.datetime
    code: str  # The part of the url that redirects. <base_url>/go/<code>
    vanity: Optional[str] = None
    destination: str
    views: int
    max_views: Optional[int] = None
    password: Optional[str] = None
    enabled: bool
    user: Optional[User] = None
    user_id: str

    @field_validator("user", mode="before")
    @classmethod
    def _validate_user(cls, value: Any, info: ValidationInfo) -> Optional[User]:
        return User(http=info.data["http"], **value) if value else None

    def __str__(self) -> str:
        return self.full_url

    @computed_field  # includes this in json output
    @property
    def full_url(self) -> str:
        """
        Returns
        -------
        :class:`str`
            The full url.
        """
        code = self.vanity or self.code
        return f"{self.http.base_url}/go/{code}"

    async def edit(
        self,
        max_views: Optional[int] = None,
        vanity: Optional[str] = None,
        destination: Optional[str] = None,
        enabled: Optional[bool] = None,
        password: Optional[str] = None,
    ) -> URL:
        """|coro|

        Edit this url.

        Parameters
        ----------
        max_views: Optional[:class:`int`]
            The new maximum views, if given.
        vanity: Optional[:class:`str`]
            The new vanity code this url should have, if given.
        destination: Optional[:class:`str`]
            The new destination, if given.
        enabled: Optional[:class:`bool`]
            Whether this url should be usable, if given.
        password: Optional[:class:`str`]
            The new password required to use this url, if given.

        Returns
        -------
        :class:`~zipline.models.URL`
            The updated url.
        """
        payload = {}

        if max_views:
            payload["maxViews"] = max_views
        if vanity:
            payload["vanity"] = vanity
        if destination:
            payload["destination"] = destination
        if enabled:
            payload["enabled"] = enabled
        if password:
            payload["password"] = password

        r = Route("PATCH", f"/api/user/urls/{self.id}")
        data = await self.http.request(r, json=payload)
        return URL(http=self.http, **data)

    async def delete(self) -> URL:
        """|coro|

        Delete this url.

        Returns
        -------
        :class:`~zipline.models.URL`
            A new instance with the latest information about this url.
        """
        r = Route("DELETE", f"/api/user/urls/{self.id}")
        data = await self.http.request(r)
        return URL(http=self.http, **data)


class UploadFile(_ZiplineClientModel):
    """
    File data given by the API when a file is uploaded.

    .. note::

        This may be resolved to a full :class:`~zipline.models.File` via :meth:`resolve`.

    .. container:: operations

        .. describe:: str(x)

            Returns the full url of the uploaded file.


    Attributes
    ----------
    id: :class:`str`
        The id of the uploaded file.
    type: :class:`str`
        The media type of the uploaded file.
    url: :class:`str`
        The url for the uploaded file.
    """

    id: str
    type: str
    url: str

    def __str__(self) -> str:
        return self.url

    async def resolve(self) -> File:
        """|coro|

        Retrieve fully fledged information about this object.

        Returns
        -------
        :class:`~zipline.models.File`
            The fully fledged object
        """
        r = Route("GET", f"/api/user/files/{self.id}")  # NOTE: Undocumented // Not officially used in the frontend.
        data = await self.http.request(r)
        return File(http=self.http, **data)


class UploadResponse(_ZiplineClientModel):
    """
    Response given by the API when a file or multiple files are uploaded.

    Attributes
    ----------
    files: List[:class:`~zipline.models.UploadFile`]
        A list of information about the files uploaded.
    deletes_at: Optional[:class:`datetime.datetime`]
        The scheduled deletion time of the uploaded files, if applicable.
    """

    files: List[UploadFile]
    deletes_at: Optional[datetime.datetime] = None

    @field_validator("files", mode="before")
    @classmethod
    def _validate_files(cls, value: Any, info: ValidationInfo) -> List[UploadFile]:
        return [UploadFile(http=info.data["http"], **file_data) for file_data in value]


class FileData(ZiplineModel):
    """
    Used to upload a File to Zipline.

    Attributes
    ----------
    obj: Union[:class:`str`, :class:`bytes`, :class:`os.PathLike`, :class:`io.BufferedIOBase`]
        The file or file like object to open.
    filename: Optional[:class:`str`]
        The name of the file to be uploaded. Defaults to filename of the given path, if applicable.
    mimetype: Optional[:class:`str`]
        The MIME type of the file, if None the lib will attempt to determine it.
    """

    obj: Union[str, bytes, os.PathLike, io.BufferedIOBase]
    filename: Optional[str] = Field(default=None, validate_default=True)
    mimetype: Optional[str] = Field(default=None, validate_default=True)

    @field_validator("filename")
    @classmethod
    def _validate_filename(cls, filename: Optional[str], info: ValidationInfo) -> Optional[str]:
        obj = info.data["obj"]
        if filename is None:
            if isinstance(obj, str):
                _, filename = os.path.split(obj)
            else:
                filename = getattr(obj, "name", "untitled")
        return filename

    @field_validator("mimetype")
    @classmethod
    def _validate_mimetype(cls, mimetype: Optional[str], info: ValidationInfo) -> Optional[str]:
        obj = info.data["obj"]
        filename = info.data["filename"]
        # Mime type determination. Strategy is:
        #   - an explicitly given type
        #   - a guessed type based on the filename, if present.
        #   - a guessed type based on magic bytes
        #   - application/octet-stream as a fallback.
        guessed_mime = None
        if mimetype is not None:
            guessed_mime = mimetype
        elif filename is not None:
            guessed_mime = mimetypes.guess_type(filename)[0]
        elif filename is None and mimetype is None:
            with cls._open_file(obj) as file:
                guessed_mime = guess_mimetype_by_magicnumber(file.read(16))

        return guessed_mime or "application/octet-stream"

    def data(self) -> io.BufferedReader | io.BufferedIOBase:
        """A seekable, readable file object representing the input data.

        Returns
        -------
        Union[io.BufferedReader, io.BufferedIOBase]
            A file-like object that can be read and seek'ed through.
            - For path-like inputs: Returns an opened file in binary read mode
            - For file-like inputs: Returns the original object if it's seekable and readable

        Raises
        ------
        ValueError
            If the input is a file-like object that is not both seekable and readable
        OSError
            If the input is a path and the file cannot be opened

        Examples
        --------
        >>> file_data = FileData(obj="path/to/file.txt")
        >>> with file_data.data() as f:
        ...     content = f.read()
        """
        return self._open_file(self.obj)

    @staticmethod
    def _open_file(
        obj: Union[str, bytes, os.PathLike, io.BufferedIOBase],
    ) -> Union[io.BufferedReader, io.BufferedIOBase]:
        if isinstance(obj, io.IOBase):
            if not (obj.seekable() and obj.readable()):
                raise ValueError(f"File buffer {obj!r} must be seekable and readable")
            return obj
        else:
            return open(obj, "rb")


class PartialQuota(ZiplineModel):
    """
    A partial quota useful for creating a new quota for a :class:`~zipline.models.User`.

    Attributes
    ----------
    type: :class:`~zipline.enums.QuotaType`
        The type of this quota.
    value: Optional[:class:`int`]
        The value to assign to this quota.

        .. note::

            This may only be omitted if :attr:`~zipline.PartialQuota.type` is :attr:`~zipline.QuotaType.none`
    max_urls: Optional[int]
        The url limit for this quota.

        .. note::

            This argument may be omitted. If None is passed there will be no limit.
    """

    type: QuotaType
    value: Optional[int] = None
    max_urls: Optional[int] = Field(default=MISSING, validate_default=True)

    @field_validator("value")
    @classmethod
    def validate_value(cls, v: Optional[int], info: ValidationInfo) -> Optional[int]:
        if "type" not in info.data:
            return v

        if info.data["type"] is not QuotaType.none and v is None:
            raise ValueError("value must be given to this quota unless type is none")
        if v is not None and v < 0:
            raise ValueError("quota amount must be greater than or equal to zero")
        return v

    @field_validator("max_urls")
    @classmethod
    def validate_max_urls(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v <= 0:
            raise ValueError("max_urls must be greater than or equal to zero")
        return v

    def _to_dict(self) -> Dict[str, Any]:
        return generate_quota_payload(self.type, self.value, self.max_urls)


class UserQuota(_ZiplineClientModel):
    """
    Represents a quota assigned to a :class:`~zipline.models.User` in Zipline.

    .. note::

        While this class may be used to update a user's quota this class is not intended
        to be created manually and should not be used for this purpose.

        Usage of :class:`~zipline.models.PartialQuota` is recommended this purpose instead.

    Attributes
    ----------
    id: :class:`str`
        The id of the quota.
    created_at: :class:`datetime.datetime`
        When this quota was created.
    updated_at: :class:`datetime.datetime`
        When this quota was last updated.
    files_quota: :class:`~zipline.enums.QuotaType`
        The type of this quota.
    max_bytes: Optional[:class:`str`]
        The maximum bytes of storage for this quota, if applicable.
    max_files: Optional[:class:`int`]
        The maximum number of files for this quota, if applicable.
    max_urls: Optional[:class:`int`]
        The maximum number of shortened urls for this quota, if applicable.
    user: Optional[:class:`~zipline.models.User`]
        The user this quota is assigned to, if given.
    user_id: Optional[:class:`str`]
        The id of the user this quota is assigned to, if given.
    """

    id: str
    created_at: datetime.datetime
    updated_at: datetime.datetime
    files_quota: QuotaType
    max_bytes: Optional[str] = None
    max_files: Optional[int] = None
    max_urls: Optional[int] = None
    user: Optional[User] = None
    user_id: Optional[str] = None

    @field_validator("user", mode="before")
    @classmethod
    def _validate_user(cls, value: Any, info: ValidationInfo) -> User:
        return User(http=info.data["http"], **value)

    def _to_dict(self) -> Dict[str, Any]:
        return generate_quota_payload(self.type, self._amount(), self.max_urls)

    def _amount(self) -> int:
        if self.max_bytes is not None:
            return int(self.max_bytes)

        if self.max_files is not None:
            return self.max_files

        raise ValueError("amount of this quota cannot be determined.")

    @property
    def type(self) -> QuotaType:
        """
        Returns
        -------
        :class:`~zipline.enums.QuotaType`
            The type of this quota.
        """
        return self.files_quota

    async def resolve_user(self) -> User:
        """|coro|

        Resolve the user this quota is assigned to, if possible.

        Returns
        -------
        :class:`~zipline.models.User`
            The user this quota is assigned to.

        Raises
        ------
        TypeError
            The :attr:`Quota.user_id` is None and the user cannot be resolved.
        """
        if self.user_id is None:
            raise TypeError("cannot resolve user with null id.")

        r = Route("GET", f"/api/users/{self.id}")
        data = await self.http.request(r)
        return User(http=self.http, **data)


class UserPasskey(ZiplineModel):
    """
    A passkey a Zipline :class:`~zipline.models.User` has set up.

    Attributes
    ----------
    id: :class:`str`
        The internal id of this object.
    created_at: :class:`datetime.datetime`
        When this passkey was created in the database.
    updated_at: :class:`datetime.datetime`
        When this passkey was last updated.
    last_used: Optional[:class:`datetime.datetime`]
        When this passkey was last used.
    name: :class:`str`
        The name of this passkey.
    reg: :class:`dict`
        Additional information about this passkey.
    user_id: :class:`str`
        The id of the :class:`~zipline.models.User` that this passkey belongs to.
    """

    id: str
    created_at: datetime.datetime
    updated_at: datetime.datetime
    last_used: Optional[datetime.datetime] = None
    name: str
    reg: JSON
    user_id: str  # NOTE: This does expose a `User` attr in the api.
    #                     Not inclined to expose it because it'd complicate this class
    #                     for minimal gain as this should already be attached to a User object.


class OAuthProvider(ZiplineModel):
    """
    Represents an OAuth provider being used by a :class:`~zipline.models.User` on Zipline.

    Attributes
    ----------
    id: :class:`str`
        The internal id of this entry.
    created_at: :class:`datetime.datetime`
        When this entry was created.
    updated_at: :class:`datetime.datetime`
        When this entry was updated.
    user_id: :class:`str`
        The id of the user this provider registration is for.
    provider: :class:`~zipline.enums.OAuthProviderType`
        The service this entry is for.
    username: :class:`str`
        The username of this entry.
    access_token: :class:`str`
        The access token of this entry.
    refresh_token: Optional[:class:`str`]
        The refresh token for this entry.
    oauth_id: Optional[:class:`str`]
        The oauth id for this entry.
    """

    id: str
    created_at: datetime.datetime
    updated_at: datetime.datetime
    user_id: str
    provider: OAuthProviderType
    username: str
    access_token: str
    refresh_token: Optional[str]
    oauth_id: Optional[str]


class Thumbnail(ZiplineModel):
    """
    Thumbnail data for a Zipline :class:`~zipline.models.File`.

    Attributes
    ----------
    path: :class:`str`
        The path to this thumbnail.
    """

    path: str


class UserViewSettings(ZiplineModel):
    """
    Represents view settings for a Zipline :class:`~zipline.models.User`.

    Attributes
    ----------
    enabled: Optional[:class:`bool`]
        Whether the view settings are enabled.
    align: Optional[Literal['left', 'center', 'right']]
        How the content should be aligned on the page.
    show_mimetype: Optional[:class:`bool`]
        Whether the content's MIME type should be displayed.
    content: Optional[:class:`str`]
        The view content.
    embed: Optional[:class:`bool`]
        Whether embed tags should be present.
    embed_title: Optional[:class:`str`]
        The title of the embed the content will generate, if applicable.
    embed_description: Optional[:class:`str`]
        The description of the embed the content will generate, if applicable.
    embed_color: Optional[:class:`str`]
        The color of the embed the content will generate, if applicable.
    embed_site_name: Optional[:class:`str`]
        The name of the site the embed will redirect to, if applicable.
    """

    enabled: Optional[bool] = None
    align: Optional[Literal["left", "center", "right"]] = None
    show_mimetype: Optional[bool] = None
    content: Optional[str] = None
    embed: Optional[bool] = None
    embed_title: Optional[str] = None
    embed_description: Optional[str] = None
    embed_color: Optional[str] = None
    embed_site_name: Optional[str] = None


class ServerVersionInfo(ZiplineModel):
    """
    Version information for a Zipline instance.

    Attributes
    ----------
    version: :class:`str`
        The current version being used.
    """

    version: str


class UserStats(ZiplineModel):
    """
    Stats for a Zipline :class:`~zipline.models.User`.

    Attributes
    ----------
    files_uploaded: :class:`int`
        The number of files the user has uploaded.
    favorite_files: :class:`int`
        The number of files the user has favorited.
    views: :class:`int`
        The number of times files uploaded by the user have been viewed.
    avg_views: :class:`int`
        The average number of views a file uploaded by the user has received.
    storage_used: :class:`int`
        The amount of storage the user is using in bytes.
    avg_storage_used: :class:`float`
        The amount of storage a file uploaded by the user takes up in bytes.
    urls_created: :class:`int`
        The number of urls the user has created.
    url_views: :class:`int`
        The number of times urls created by the user have been visited.
    sort_type_count: Dict[:class:`str`, :class:`int`]
        A mapping of MIME type to number of files uploaded.
    """

    files_uploaded: int
    favorite_files: int
    views: int
    avg_views: int
    storage_used: int
    avg_storage_used: float
    urls_created: int
    url_views: int
    sort_type_count: Dict[str, int]


class UserFilesResponse(ZiplineModel):
    """
    Represents a response to a file search on Zipline.

    Attributes
    ----------
    page: List[:class:`~zipline.models.File`]
        The files on this page.
    search: Optional[Dict[:class:`str`, Any]]
        Search parameters that were passed.
    total: Optional[:class:`int`]
        The total number of items matching the search.
    pages: Optional[:class:`int`]
        The number of pages available.
    """

    page: List[File]
    search: Optional[Dict[str, Any]] = None
    total: Optional[int] = None
    pages: Optional[int] = None

    @property
    def files(self) -> List[File]:
        """Alias for :attr:`~zipline.models.UserFilesResponse.page`."""
        return self.page


class Avatar(ZiplineModel):
    """
    Wraps the representation of avatars in Zipline.

    .. container:: operations

        .. describe:: str(x)

            Returns the encoded data for this Avatar.

    Attributes
    ----------
    data: :class:`bytes`
        The avatar data itself.
    mime: :class:`str`
        The MIME type of the data. If not given the library will attempt to guess the type.

        .. versionchanged:: 0.28.0

            This attribute is no longer optional.
    """

    data: bytes
    mime: str

    @field_validator("mime", mode="before")
    @classmethod
    def _mime_validator(cls, v: Any, info: ValidationInfo) -> Any:
        if isinstance(v, str):
            return v
        mime_guess = guess_mimetype_by_magicnumber(info.data["data"][:16])
        if mime_guess:
            return mime_guess
        raise ValueError("Could not determine mimetype of avatar and one was not provided.")

    def __str__(self) -> str:
        return self.to_payload_str()

    @classmethod
    def from_coded_string(cls, coded_str: str) -> Avatar:
        """
        Transforms a coded string.

        Parameters
        ----------
        coded_str: :class:`str`
            The string to transform
        """
        mime_part, data = coded_str.split(";")

        mime_part = mime_part[5:]
        data = base64.b64decode(data[7:])

        return cls(data=data, mime=mime_part)

    def to_payload_str(self) -> str:
        """
        Returns the base64 encoded string for use in Zipline requests.

        Returns
        -------
        :class:`str`
            The string for use in requests.
        """
        return build_avatar_payload(self.mime, self.data)
