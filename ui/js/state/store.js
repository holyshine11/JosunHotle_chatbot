/**
 * 간단한 상태 관리 스토어
 * LocalStorage/IndexedDB 사용하지 않음 (세션 상태만 유지)
 */

// 호텔 데이터
export const HOTELS = [
  {
    id: 'josun_palace',
    name: '조선 팰리스',
    nameEn: 'Josun Palace',
    description: '서울 강남의 럭셔리 호텔',
    location: '서울 강남구',
    color: '#1a365d',
    url: 'https://www.josunhotel.com/josunPalace.do'
  },
  {
    id: 'grand_josun_busan',
    name: '그랜드 조선 부산',
    nameEn: 'Grand Josun Busan',
    description: '해운대 오션뷰 프리미엄 호텔',
    location: '부산 해운대구',
    color: '#2c5282',
    url: 'https://gjb.josunhotel.com/'
  },
  {
    id: 'grand_josun_jeju',
    name: '그랜드 조선 제주',
    nameEn: 'Grand Josun Jeju',
    description: '제주 중문의 리조트형 호텔',
    location: '제주 서귀포시',
    color: '#285e61',
    url: 'https://gjj.josunhotel.com/'
  },
  {
    id: 'lescape',
    name: '레스케이프',
    nameEn: "L'Escape",
    description: '명동의 부티크 라이프스타일 호텔',
    location: '서울 중구',
    color: '#553c9a',
    url: 'https://www.lescape.co.kr/'
  },
  {
    id: 'gravity_pangyo',
    name: '그래비티 판교',
    nameEn: 'Gravity Pangyo',
    description: '판교 테크노밸리의 비즈니스 호텔',
    location: '경기 성남시',
    color: '#744210',
    url: 'https://www.gravity-hotels.com/'
  }
];

// 초기 상태
const initialState = {
  currentHotel: null,        // 선택된 호텔
  messages: [],              // 대화 메시지 [{id, role, content, createdAt, status}]
  isSending: false,          // 전송 중 여부
  errorState: null,          // 에러 상태
  showHotelModal: true,      // 호텔 선택 모달 표시 여부
  sessionId: null            // 세션 ID (서버에서 발급)
};

// 상태 저장소
let state = { ...initialState };

// 구독자 목록
const subscribers = new Set();

/**
 * 상태 변경 알림
 */
function notifySubscribers() {
  subscribers.forEach(callback => callback(state));
}

/**
 * 상태 구독
 */
export function subscribe(callback) {
  subscribers.add(callback);
  return () => subscribers.delete(callback);
}

/**
 * 현재 상태 조회
 */
export function getState() {
  return { ...state };
}

/**
 * 호텔 선택
 */
export function selectHotel(hotelId) {
  const hotel = HOTELS.find(h => h.id === hotelId);
  if (hotel) {
    state = {
      ...state,
      currentHotel: hotel,
      showHotelModal: false
    };
    notifySubscribers();
  }
}

/**
 * 호텔 변경 (대화 유지)
 */
export function changeHotel(hotelId) {
  const hotel = HOTELS.find(h => h.id === hotelId);
  if (hotel) {
    // 호텔 변경 시스템 메시지 추가
    const systemMessage = {
      id: Date.now(),
      role: 'system',
      content: `호텔이 "${hotel.name}"(으)로 변경되었습니다.`,
      createdAt: new Date().toISOString(),
      status: 'done'
    };
    
    state = {
      ...state,
      currentHotel: hotel,
      messages: [...state.messages, systemMessage]
    };
    notifySubscribers();
  }
}

/**
 * 메시지 추가
 */
export function addMessage(message) {
  state = {
    ...state,
    messages: [...state.messages, {
      id: Date.now() + Math.random(),
      createdAt: new Date().toISOString(),
      status: 'done',
      ...message
    }]
  };
  notifySubscribers();
}

/**
 * 생각중 메시지 추가
 */
export function addThinkingMessage() {
  const thinkingId = Date.now() + Math.random();
  state = {
    ...state,
    messages: [...state.messages, {
      id: thinkingId,
      role: 'assistant',
      content: '',
      createdAt: new Date().toISOString(),
      status: 'thinking'
    }],
    isSending: true
  };
  notifySubscribers();
  return thinkingId;
}

/**
 * 생각중 메시지를 실제 응답으로 교체
 */
export function replaceThinkingMessage(thinkingId, content, status = 'done') {
  state = {
    ...state,
    messages: state.messages.map(msg => 
      msg.id === thinkingId 
        ? { ...msg, content, status }
        : msg
    ),
    isSending: false,
    errorState: status === 'error' ? content : null
  };
  notifySubscribers();
}

/**
 * 전송 상태 설정
 */
export function setSending(isSending) {
  state = { ...state, isSending };
  notifySubscribers();
}

/**
 * 에러 상태 설정
 */
export function setError(errorState) {
  state = { ...state, errorState, isSending: false };
  notifySubscribers();
}

/**
 * 에러 초기화
 */
export function clearError() {
  state = { ...state, errorState: null };
  notifySubscribers();
}

/**
 * 새 대화 시작 (메시지만 초기화)
 */
export function startNewChat() {
  state = {
    ...state,
    messages: [],
    errorState: null,
    isSending: false,
    sessionId: null  // 세션 초기화
  };
  notifySubscribers();
}

/**
 * 호텔 선택 모달 표시
 */
export function showHotelSelectModal() {
  state = { ...state, showHotelModal: true };
  notifySubscribers();
}

/**
 * 전체 초기화
 */
export function resetAll() {
  state = { ...initialState };
  notifySubscribers();
}

/**
 * 최근 N개 메시지 히스토리 반환 (API 전송용)
 */
export function getHistory(count = 10) {
  return state.messages
    .filter(m => m.role !== 'system' && m.status === 'done')
    .slice(-count)
    .map(m => ({ role: m.role, content: m.content }));
}
