/**
 * TTS 텍스트 전처리 모듈
 * 마크다운/URL/참조 마커 제거 + 한국어 최적화
 */
const TTSPreprocessor = {

  // 한국어 숫자 읽기 매핑
  _digitMap: { '0': '영', '1': '일', '2': '이', '3': '삼', '4': '사',
               '5': '오', '6': '육', '7': '칠', '8': '팔', '9': '구' },

  // 전화번호 숫자 읽기 (0→공)
  _phoneDigitMap: { '0': '공', '1': '일', '2': '이', '3': '삼', '4': '사',
                    '5': '오', '6': '육', '7': '칠', '8': '팔', '9': '구' },

  /**
   * 답변 텍스트를 TTS에 적합하게 변환
   */
  process(text) {
    if (!text) return '';
    let result = text;

    // 0. "참고 정보:" 이하 URL 블록 전체 제거 (본문만 읽기)
    result = result.replace(/참고\s*정보\s*:?[\s\S]*/g, '');

    // 1. 참조 마커 제거: [REF:1], [REF:2] 등
    result = result.replace(/\[REF:\d+\]/g, '');

    // 2. 마크다운 링크 → 텍스트만: [텍스트](url) → 텍스트
    result = result.replace(/\[([^\]]+)\]\([^)]+\)/g, '$1');

    // 3. 남은 URL 제거
    result = result.replace(/https?:\/\/[^\s)]+/g, '');

    // 4. 마크다운 서식 제거
    result = result.replace(/#{1,6}\s+/g, '');         // 헤더
    result = result.replace(/\*\*([^*]+)\*\*/g, '$1'); // bold
    result = result.replace(/\*([^*]+)\*/g, '$1');     // italic
    result = result.replace(/`([^`]+)`/g, '$1');       // inline code
    result = result.replace(/```[\s\S]*?```/g, '');    // code block

    // 5. 리스트 기호 → 문장 구분
    result = result.replace(/^[-*•]\s+/gm, '');
    result = result.replace(/^\d+\.\s+/gm, '');

    // 6. 한국어 숫자/시간 변환
    result = this._convertTime(result);
    result = this._convertPhone(result);
    result = this._convertPrice(result);

    // 7. 특수 기호 정리
    result = result.replace(/[|─═┌┐└┘├┤┬┴┼]/g, '');
    result = result.replace(/[><]/g, '');

    // 8. 연속 공백/줄바꿈 정리
    result = result.replace(/\n{2,}/g, '. ');
    result = result.replace(/\n/g, '. ');
    result = result.replace(/\s{2,}/g, ' ');
    result = result.replace(/\.\s*\./g, '.');

    return result.trim();
  },

  /**
   * 시간 표기 변환: 15:00 → 15시, 15:30 → 15시 30분
   */
  _convertTime(text) {
    return text.replace(/(\d{1,2}):(\d{2})/g, (match, h, m) => {
      const hour = parseInt(h);
      const min = parseInt(m);
      if (hour > 24 || min > 59) return match;
      return min === 0 ? `${hour}시` : `${hour}시 ${min}분`;
    });
  },

  /**
   * 전화번호 변환: 02-1234-5678 → 공이 일이삼사 오육칠팔
   */
  _convertPhone(text) {
    // 전화번호 패턴: 02-1234-5678, 02.1234.5678, 1588-1234
    return text.replace(/(\d{2,4})[-.]\d{3,4}[-.]\d{4}/g, (match) => {
      const digits = match.replace(/[-.\s]/g, '');
      return digits.split('').map(d => this._phoneDigitMap[d] || d).join('');
    });
  },

  /**
   * 가격 변환: 50,000원 → 5만원, 150,000원 → 15만원
   */
  _convertPrice(text) {
    // 만 단위 가격
    return text.replace(/([\d,]+)원/g, (match, num) => {
      const value = parseInt(num.replace(/,/g, ''));
      if (isNaN(value)) return match;
      if (value >= 10000) {
        const man = Math.floor(value / 10000);
        const remainder = value % 10000;
        if (remainder === 0) return `${man}만원`;
        return `${man}만 ${remainder.toLocaleString()}원`;
      }
      return match;
    });
  }
};
