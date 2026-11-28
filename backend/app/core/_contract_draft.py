"""SHIM tạm thời — Contract Drop của linh đã lên: kiểu dữ liệu và hằng số giờ nằm ở `app.schemas.*` và `app.config`.

File này chỉ re-export để code và test của bao chạy tiếp không cần sửa ngay.
bao: khi tiện, đổi import sang `app.schemas.*` / `app.config` rồi xóa file này.
"""

from app.config import (  # noqa: F401
    ANTI_COACHING_NOTICE_VI,
    DEFAULT_RULE_TTL_HOURS,
    EMBED_DIM,
    EMBED_MODEL,
    LLM_MODEL,
    MIN_ASK_AMOUNT_VND,
    PARTNER_WARN_SCORE,
    SEMANTIC_THRESHOLD,
    TRIGRAM_THRESHOLD,
)
from app.schemas.common import Strict as _Strict  # noqa: F401
from app.schemas.gateway import BaselineResult, DerivedTx  # noqa: F401
from app.schemas.incident import AnalyzeResult, Fact, IncidentAnalysis  # noqa: F401
from app.schemas.llm_incident import (  # noqa: F401
    FactLLM,
    IncidentAnalysisLLM,
    Provenance,
    TacticFamily,
    YesNoUnknown,
)
from app.schemas.llm_rule import (  # noqa: F401
    ConditionLLM,
    FieldName,
    LLMOutcome,
    OpName,
    PurposeOptionLLM,
    PurposeQuestionLLM,
    RelayRuleDraftLLM,
    StructuredVariantLLM,
)
from app.schemas.rule import (  # noqa: F401
    AnchorSet,
    Approval,
    CompileResult,
    Condition,
    FlaggedExample,
    JitQuestion,
    Lifecycle,
    ObservableSignals,
    Outcome,
    PurposeOption,
    PurposeQuestion,
    RegressionResult,
    RelayRule,
    RelayRuleDraft,
    RuleOption,
    Stage,
    StructuredVariant,
    ValidationResult,
)
