/**
 * 챗봇 API 클라이언트
 * 일반 요청과 스트리밍 모두 지원
 */

// API 베이스 URL (환경변수 또는 기본값)
// 같은 도메인에서 제공되면 빈 문자열 사용
const API_BASE_URL = window.VITE_CHAT_API_BASE_URL || '';

// 요청 타임아웃 (60초)
const REQUEST_TIMEOUT = 60000;

/**
 * 일반 채팅 요청
 * @param {string} hotelId - 호텔 ID
 * @param {string} message - 사용자 메시지
 * @param {Array} history - 대화 히스토리
 * @returns {Promise<{answer: string, score?: number, sources?: string[]}>}
 */
export async function sendMessage(hotelId, message, history = []) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT);
  
  try {
    const response = await fetch(`${API_BASE_URL}/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        hotelId,
        message,
        history
      }),
      signal: controller.signal
    });
    
    clearTimeout(timeoutId);
    
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    
    const data = await response.json();
    return data;
  } catch (error) {
    clearTimeout(timeoutId);
    
    if (error.name === 'AbortError') {
      throw new Error('요청 시간이 초과되었습니다. 다시 시도해 주세요.');
    }
    
    throw error;
  }
}

/**
 * 스트리밍 채팅 요청 (SSE)
 * @param {string} hotelId - 호텔 ID
 * @param {string} message - 사용자 메시지
 * @param {Array} history - 대화 히스토리
 * @param {function} onChunk - 청크 수신 콜백
 * @param {function} onComplete - 완료 콜백
 * @param {function} onError - 에러 콜백
 */
export async function sendMessageStream(hotelId, message, history = [], onChunk, onComplete, onError) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => {
    controller.abort();
    onError(new Error('요청 시간이 초과되었습니다.'));
  }, REQUEST_TIMEOUT);
  
  try {
    const response = await fetch(`${API_BASE_URL}/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        hotelId,
        message,
        history
      }),
      signal: controller.signal
    });
    
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let fullContent = '';
    
    while (true) {
      const { done, value } = await reader.read();
      
      if (done) {
        clearTimeout(timeoutId);
        onComplete(fullContent);
        break;
      }
      
      const chunk = decoder.decode(value, { stream: true });
      fullContent += chunk;
      onChunk(chunk, fullContent);
    }
  } catch (error) {
    clearTimeout(timeoutId);
    
    if (error.name === 'AbortError') {
      onError(new Error('요청 시간이 초과되었습니다.'));
    } else {
      onError(error);
    }
  }
}

/**
 * 연결 테스트
 */
export async function testConnection() {
  try {
    const response = await fetch(`${API_BASE_URL}/health`, {
      method: 'GET',
      timeout: 5000
    });
    return response.ok;
  } catch {
    return false;
  }
}

/**
 * Mock API (백엔드 없이 테스트용)
 */
export async function sendMessageMock(hotelId, message, history = []) {
  // 1~3초 지연 시뮬레이션
  await new Promise(resolve => setTimeout(resolve, 1000 + Math.random() * 2000));
  
  // 간단한 응답 생성
  const responses = {
    '체크인': '체크인 시간은 오후 3시(15:00)입니다.',
    '체크아웃': '체크아웃 시간은 오전 11시(11:00)입니다.',
    '주차': '호텔 지하 주차장을 이용하실 수 있으며, 투숙객은 무료입니다.',
    '조식': '조식은 오전 7시부터 10시까지 운영됩니다.',
    '수영장': '수영장은 오전 6시부터 오후 10시까지 운영됩니다.',
    '피트니스': '피트니스 센터는 24시간 운영됩니다.'
  };
  
  // 키워드 매칭
  for (const [keyword, response] of Object.entries(responses)) {
    if (message.includes(keyword)) {
      return { 
        answer: response,
        score: 0.95,
        sources: ['https://www.josunhotel.com/faq']
      };
    }
  }
  
  // 기본 응답
  return {
    answer: `"${message}"에 대한 정보를 찾고 있습니다. 현재 선택된 호텔은 ${hotelId}입니다. 구체적인 정보는 호텔 고객센터(02-1234-5678)로 문의해 주세요.`,
    score: 0.7,
    sources: []
  };
}

// 사용할 API 함수 (실제 백엔드 연동)
export const chat = sendMessage;
