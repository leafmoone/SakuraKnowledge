"""Public identities and versioned tokenization."""
from dataclasses import dataclass
import re
import unicodedata

STATUSES = frozenset({"source_backed", "generated_from_evidence", "unverified_draft",
                      "no_reference", "conflict", "failed"})
TRUSTED = frozenset({"source_backed", "generated_from_evidence"})
GROUPS = ("common_tags", "anime_pictures_1_noncommon", "bangumi_1_noncommon",
          "gamecg_5m_noncommon", "konachan_1_noncommon", "yande_1_noncommon",
          "zerochan_1_noncommon")
KINDS = frozenset({"subject", "character", "person", "episode", "page", "tag"})


@dataclass(frozen=True, order=True)
class EntryKey:
    kind: str
    namespace: str
    value: str

    def __post_init__(self):
        if self.kind not in KINDS or not self.namespace or self.value is None:
            raise ValueError("invalid EntryKey")
        object.__setattr__(self, "value", str(self.value))
        if not self.value or any(len(x) > 1024 for x in (self.namespace, self.value)):
            raise ValueError("invalid EntryKey length")

    def as_dict(self):
        return {"kind": self.kind, "namespace": self.namespace, "value": self.value}

    def parts(self):
        return self.kind, self.namespace, self.value


@dataclass(frozen=True)
class TagKey:
    namespace: str
    value: str

    def entry(self):
        return EntryKey("tag", self.namespace, self.value)


def tokens(text):
    if not isinstance(text, str) or len(text) > 4096:
        raise ValueError("query/text chunk exceeds 4096 characters")
    text = unicodedata.normalize("NFKC", text).casefold()
    result = []
    for match in re.finditer(r"[\u3040-\u30ff\u3400-\u9fff]+|[^\W_]+", text):
        word = match.group()
        if re.fullmatch(r"[\u3040-\u30ff\u3400-\u9fff]+", word):
            result.extend(word[i:i + 2] for i in range(len(word) - 1))
        else:
            result.append(word)
    return result[:256]


def search_text(text):
    if not isinstance(text, str) or len(text) > 100_000:
        raise ValueError("document exceeds 100000 characters")
    return " ".join(t for start in range(0, len(text), 2048)
                    for t in tokens(text[start:start + 2049]))


def match_query(text):
    return " OR ".join('"' + t.replace('"', '""') + '"' for t in dict.fromkeys(tokens(text)))
