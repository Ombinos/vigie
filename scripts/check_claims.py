"""Validate excerpt provenance in collected text, never truth or attribution.
An empty claim set is valid: a feed need not contain quoted speech.
"""
from __future__ import annotations
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def normalized_span(value: object) -> str:
    return " ".join(str(value or "").split())


def audit_claims(enriched: dict, issues: dict) -> dict:
    candidates = enriched.get("candidates") or []
    by_id = {str(c["id"]): c for c in candidates if c.get("id")}
    errors: list[dict] = []
    attrs: Counter = Counter()
    claim_count = 0
    speakers = 0
    for candidate in candidates:
        for claim in (candidate.get("enrich") or {}).get("claims") or []:
            claim_count += 1
            attrs[str(claim.get("attribution") or "unknown")] += 1
            speakers += bool(claim.get("speaker"))
            reason = None
            field = claim.get("field")
            quote = normalized_span(claim.get("quote"))
            text = normalized_span(candidate.get(field)) if field in ("title", "summary") else ""
            if claim.get("status") != "proposed":
                reason = "claim_status_not_proposed"
            elif not text or not quote or quote not in text:
                reason = "excerpt_not_in_declared_source_field"
            elif claim.get("speaker") and normalized_span(claim["speaker"]) not in text:
                reason = "speaker_not_in_declared_source_field"
            if reason:
                errors.append({"candidate_id": candidate.get("id"), "reason": reason})
    for issue in issues.get("issues") or []:
        voices = {t.get("institution_id") for t in issue.get("tensions") or [] if t.get("institution_id")}
        if len(voices) < 2:
            errors.append({"issue_id": issue.get("issue_id"), "reason": "fewer_than_two_institutions"})
        for tension in issue.get("tensions") or []:
            for item in tension.get("items") or []:
                source = by_id.get(str(item.get("candidate_id")))
                if source is None:
                    errors.append({"candidate_id": item.get("candidate_id"), "reason": "issue_article_missing_from_snapshot"})
                    continue
                expected = (source.get("enrich") or {}).get("claims") or []
                for claim in item.get("claims") or []:
                    if claim not in expected:
                        errors.append({"candidate_id": item.get("candidate_id"), "reason": "issue_claim_lost_or_changed_provenance"})
    return {
        "method": "extraction-integrity-v1-not-truth-verification",
        "candidate_count": len(candidates),
        "claim_count": claim_count,
        "candidates_with_claims": sum(bool((c.get("enrich") or {}).get("claims")) for c in candidates),
        "with_speaker": speakers,
        "attributions": dict(attrs),
        "errors": errors,
        "ok": not errors,
        "limitation": "Containment does not validate truth, context, speaker attribution, or independent confirmation.",
    }


def main() -> int:
    enriched = json.loads((ROOT / "data/normalized/latest_enriched.json").read_text(encoding="utf-8"))
    issues = json.loads((ROOT / "data/issues/latest_issues.json").read_text(encoding="utf-8"))
    report = audit_claims(enriched, issues)
    path = ROOT / "data/normalized/_check_claims.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
