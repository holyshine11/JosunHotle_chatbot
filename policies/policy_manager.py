"""
정책 관리 모듈
- YAML 정책 파일 로드 및 관리
- 금지 키워드/주제 검사
- 답변 템플릿 적용
"""

import re
from pathlib import Path
from typing import Optional

import yaml


class PolicyManager:
    """정책 관리자"""

    def __init__(self, policyPath: str = None):
        self.basePath = Path(__file__).parent
        self.policyPath = policyPath or self.basePath / "josun_policies.yaml"

        # 정책 로드
        self.policy = self._loadPolicy()

        # 금지 키워드 컴파일
        self._compileForbiddenPatterns()

    def _loadPolicy(self) -> dict:
        """정책 파일 로드"""
        with open(self.policyPath, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _compileForbiddenPatterns(self):
        """금지 키워드 패턴 컴파일"""
        self.forbiddenPatterns = {}

        forbiddenKeywords = self.policy.get("forbidden_keywords", {})
        for category, keywords in forbiddenKeywords.items():
            patterns = [re.compile(re.escape(kw), re.IGNORECASE) for kw in keywords]
            self.forbiddenPatterns[category] = patterns

    def getHotelInfo(self, hotelKey: str) -> Optional[dict]:
        """호텔 정보 조회"""
        hotels = self.policy.get("hotels", {})
        return hotels.get(hotelKey)

    def getHotelPhone(self, hotelKey: str) -> str:
        """호텔 전화번호 조회"""
        info = self.getHotelInfo(hotelKey)
        if info:
            return info.get("phone", "호텔 고객센터")
        return "호텔 고객센터"

    def getHotelWebsite(self, hotelKey: str) -> str:
        """호텔 웹사이트 조회"""
        info = self.getHotelInfo(hotelKey)
        if info:
            return info.get("website", "")
        return ""

    def checkForbiddenKeywords(self, text: str) -> tuple[bool, str, str]:
        """
        금지 키워드 검사

        Returns:
            (is_forbidden, category, matched_keyword)
        """
        for category, patterns in self.forbiddenPatterns.items():
            for pattern in patterns:
                match = pattern.search(text)
                if match:
                    return True, category, match.group()

        return False, "", ""

    def getResponseTemplate(self, templateName: str, hotelKey: str = None) -> str:
        """답변 템플릿 조회 및 변수 치환"""
        templates = self.policy.get("response_templates", {})
        template = templates.get(templateName, {})

        message = template.get("message", "")

        # 변수 치환
        if hotelKey:
            message = message.replace("{hotel_phone}", self.getHotelPhone(hotelKey))
            message = message.replace("{hotel_website}", self.getHotelWebsite(hotelKey))

            info = self.getHotelInfo(hotelKey)
            if info:
                message = message.replace("{hotel_name}", info.get("name", ""))
                message = message.replace("{hotel_email}", info.get("email", ""))

        return message.strip()

    def getEvidenceThreshold(self) -> float:
        """근거 검증 임계값 조회"""
        gate = self.policy.get("evidence_gate", {})
        return gate.get("min_score", 0.5)

    def getMinChunks(self) -> int:
        """최소 필요 청크 수 조회"""
        gate = self.policy.get("evidence_gate", {})
        return gate.get("min_chunks", 1)

    def getCategoryRule(self, category: str) -> Optional[dict]:
        """카테고리별 규칙 조회"""
        rules = self.policy.get("category_rules", {})
        return rules.get(category)

    def applyPolicy(self, query: str, answer: str, hotelKey: str = None) -> dict:
        """
        정책 적용

        Returns:
            {
                "allowed": bool,
                "reason": str,
                "modified_answer": str,
                "template_used": str
            }
        """
        # 1. 금지 키워드 검사
        isForbidden, category, keyword = self.checkForbiddenKeywords(query)

        if isForbidden:
            if category == "personal_info":
                return {
                    "allowed": False,
                    "reason": f"개인정보 관련 키워드 감지: {keyword}",
                    "modified_answer": self.getResponseTemplate("personal_info_block", hotelKey),
                    "template_used": "personal_info_block"
                }
            elif category == "payment_action":
                return {
                    "allowed": False,
                    "reason": f"결제 관련 키워드 감지: {keyword}",
                    "modified_answer": self.getResponseTemplate("payment_redirect", hotelKey),
                    "template_used": "payment_redirect"
                }

        # 2. 정상 답변
        return {
            "allowed": True,
            "reason": "정책 통과",
            "modified_answer": answer,
            "template_used": "normal"
        }

    def formatAnswer(
        self,
        answer: str,
        hotelKey: str = None,
        category: str = None,
        sourceUrl: str = None,
        updatedAt: str = None
    ) -> str:
        """답변 포맷팅"""
        result = answer

        # 카테고리별 경고 추가
        if category:
            rule = self.getCategoryRule(category)
            if rule and rule.get("warning"):
                result += f"\n\n⚠️ {rule['warning']}"

        # 출처 추가
        if sourceUrl:
            result += f"\n\n📌 출처: {sourceUrl}"

        # 업데이트 시간 추가 (카테고리 규칙에 따라)
        if category and updatedAt:
            rule = self.getCategoryRule(category)
            if rule and rule.get("always_include_updated_at"):
                result += f"\n(정보 업데이트: {updatedAt[:10]})"

        return result


def main():
    """테스트"""
    pm = PolicyManager()

    # 호텔 정보 테스트
    print("[호텔 정보]")
    for hotel in ["josun_palace", "lescape"]:
        info = pm.getHotelInfo(hotel)
        print(f"  {hotel}: {info['name']} ({info['phone']})")

    # 금지 키워드 테스트
    print("\n[금지 키워드 검사]")
    testQueries = [
        "체크인 시간 알려주세요",
        "예약번호로 확인해주세요",
        "카드번호 입력하면 결제되나요?",
        "주차 요금이 어떻게 되나요?",
    ]

    for query in testQueries:
        forbidden, cat, kw = pm.checkForbiddenKeywords(query)
        status = f"❌ 금지 ({cat}: {kw})" if forbidden else "✅ 허용"
        print(f"  {query[:30]:30} -> {status}")

    # 템플릿 테스트
    print("\n[답변 템플릿]")
    print(pm.getResponseTemplate("personal_info_block", "josun_palace"))


if __name__ == "__main__":
    main()
