from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class UnsubCallback(BaseModel):
    subscription_id: Optional[str]

    def serialize(self) -> str:
        return f"unsub:{self.subscription_id or 'cancel'}"

    @classmethod
    def parse(cls, data: str) -> "UnsubCallback":
        _, rest = data.split(":", 1)
        return cls(subscription_id=None if rest == "cancel" else rest)


class LangCallback(BaseModel):
    lang: str

    def serialize(self) -> str:
        return f"lang:{self.lang}"

    @classmethod
    def parse(cls, data: str) -> "LangCallback":
        _, lang = data.split(":", 1)
        return cls(lang=lang)


class OnboardLangCallback(BaseModel):
    lang: str

    def serialize(self) -> str:
        return f"onboard:{self.lang}"

    @classmethod
    def parse(cls, data: str) -> "OnboardLangCallback":
        _, lang = data.split(":", 1)
        return cls(lang=lang)


class DigestPodCallback(BaseModel):
    subscription_id: Optional[str]

    def serialize(self) -> str:
        return f"digest:pod:{self.subscription_id or 'cancel'}"

    @classmethod
    def parse(cls, data: str) -> "DigestPodCallback":
        parts = data.split(":")
        sid = parts[2]
        return cls(subscription_id=None if sid == "cancel" else sid)


class DigestEpCallback(BaseModel):
    subscription_id: Optional[str]
    index: int = 0

    def serialize(self) -> str:
        if self.subscription_id is None:
            return "digest:ep:cancel:0"
        return f"digest:ep:{self.subscription_id}:{self.index}"

    @classmethod
    def parse(cls, data: str) -> "DigestEpCallback":
        parts = data.split(":")
        sid = parts[2]
        if sid == "cancel":
            return cls(subscription_id=None, index=0)
        return cls(subscription_id=sid, index=int(parts[3]))


class TranscriptPodCallback(BaseModel):
    subscription_id: Optional[str]

    def serialize(self) -> str:
        return f"transcript:pod:{self.subscription_id or 'cancel'}"

    @classmethod
    def parse(cls, data: str) -> "TranscriptPodCallback":
        parts = data.split(":")
        sid = parts[2]
        return cls(subscription_id=None if sid == "cancel" else sid)


class TranscriptEpCallback(BaseModel):
    subscription_id: Optional[str]
    index: int = 0

    def serialize(self) -> str:
        if self.subscription_id is None:
            return "transcript:ep:cancel:0"
        return f"transcript:ep:{self.subscription_id}:{self.index}"

    @classmethod
    def parse(cls, data: str) -> "TranscriptEpCallback":
        parts = data.split(":")
        sid = parts[2]
        if sid == "cancel":
            return cls(subscription_id=None, index=0)
        return cls(subscription_id=sid, index=int(parts[3]))


class DigestNavCallback(BaseModel):
    subscription_id: str
    offset: int

    def serialize(self) -> str:
        return f"digest:nav:{self.subscription_id}:{self.offset}"

    @classmethod
    def parse(cls, data: str) -> "DigestNavCallback":
        parts = data.split(":")
        return cls(subscription_id=parts[2], offset=int(parts[3]))


class TranscriptNavCallback(BaseModel):
    subscription_id: str
    offset: int

    def serialize(self) -> str:
        return f"transcript:nav:{self.subscription_id}:{self.offset}"

    @classmethod
    def parse(cls, data: str) -> "TranscriptNavCallback":
        parts = data.split(":")
        return cls(subscription_id=parts[2], offset=int(parts[3]))


class SetpromptPodCallback(BaseModel):
    subscription_id: str

    def serialize(self) -> str:
        return f"setprompt:pod:{self.subscription_id}"

    @classmethod
    def parse(cls, data: str) -> "SetpromptPodCallback":
        sid = data.split(":", 2)[2]
        return cls(subscription_id=sid)


class SetpromptActionCallback(BaseModel):
    action: str
    subscription_id: str

    def serialize(self) -> str:
        return f"setprompt:{self.action}:{self.subscription_id}"

    @classmethod
    def parse(cls, data: str) -> "SetpromptActionCallback":
        parts = data.split(":", 2)
        return cls(action=parts[1], subscription_id=parts[2])


class ChatPodCallback(BaseModel):
    subscription_id: Optional[str]

    def serialize(self) -> str:
        return f"chat:pod:{self.subscription_id or 'cancel'}"

    @classmethod
    def parse(cls, data: str) -> "ChatPodCallback":
        parts = data.split(":")
        sid = parts[2]
        return cls(subscription_id=None if sid == "cancel" else sid)


class ChatNavCallback(BaseModel):
    subscription_id: str
    offset: int

    def serialize(self) -> str:
        return f"chat:nav:{self.subscription_id}:{self.offset}"

    @classmethod
    def parse(cls, data: str) -> "ChatNavCallback":
        parts = data.split(":")
        return cls(subscription_id=parts[2], offset=int(parts[3]))


class ChatEpCallback(BaseModel):
    subscription_id: Optional[str]
    index: int = 0

    def serialize(self) -> str:
        if self.subscription_id is None:
            return "chat:ep:cancel:0"
        return f"chat:ep:{self.subscription_id}:{self.index}"

    @classmethod
    def parse(cls, data: str) -> "ChatEpCallback":
        parts = data.split(":")
        sid = parts[2]
        if sid == "cancel":
            return cls(subscription_id=None, index=0)
        return cls(subscription_id=sid, index=int(parts[3]))
