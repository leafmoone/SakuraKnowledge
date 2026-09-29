"""Public identities and versioned tokenization."""
import re
import unicodedata
from dataclasses import dataclass

_WORDS = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]+|[^\W_]+")
_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]+\Z")
_MAX_WORD = 256
_MAX_QUERY_TOKENS = 256

STATUSES = frozenset({"source_backed", "generated_from_evidence", "unverified_draft",
                      "no_reference", "conflict", "failed"})
# Identity resolution (exact keys, value/alias resolution, ask targets) accepts
# only evidence anchored to the source. Future reviewed-identity statuses are
# added here deliberately, never by default.
IDENTITY_TRUSTED = frozenset({"source_backed"})
# Descriptions and FTS may additionally use trusted-producer generated text.
TEXT_TRUSTED = frozenset({"source_backed", "generated_from_evidence"})
TRUSTED = TEXT_TRUSTED  # historical name, kept for compatibility
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


def _lex(text):
    # Use the same normalization and lexing for queries and indexed documents.
    # Do not split at arbitrary chunk boundaries: this loses Latin words and CJK bigrams.
    for match in _WORDS.finditer(unicodedata.normalize("NFKC", text).casefold()):
        word = match.group()
        if _CJK.fullmatch(word):
            for index in range(len(word) - 1):
                yield word[index:index + 2]
        elif len(word) <= _MAX_WORD:
            yield word


def tokens(text):
    if not isinstance(text, str) or len(text) > 4096:
        raise ValueError("query exceeds 4096 characters")
    result = []
    for token in _lex(text):
        if len(result) == _MAX_QUERY_TOKENS:
            raise ValueError("query exceeds 256 tokens")
        result.append(token)
    return result


def search_text(text):
    if not isinstance(text, str) or len(text) > 100_000:
        raise ValueError("document exceeds 100000 characters")
    return " ".join(_lex(text))


def match_query(text):
    return " OR ".join('"' + t.replace('"', '""') + '"' for t in dict.fromkeys(tokens(text)))
