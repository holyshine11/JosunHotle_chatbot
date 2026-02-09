/**
 * STT (Speech-to-Text) 엔진 모듈
 * Web Speech API SpeechRecognition 래퍼 (한국어)
 */
const STTEngine = {
  _recognition: null,
  _state: 'idle',  // idle | listening | processing

  // 콜백
  onResult: null,       // (transcript) => void  — 인식 완료 시
  onStateChange: null,  // (state) => void

  /**
   * STT 사용 가능 여부
   */
  isAvailable() {
    return !!(window.SpeechRecognition || window.webkitSpeechRecognition);
  },

  /**
   * 녹음 시작
   */
  start() {
    if (!this.isAvailable()) return;
    if (this._state !== 'idle') {
      this.stop();
    }

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    this._recognition = new SpeechRecognition();
    this._recognition.lang = 'ko-KR';
    this._recognition.continuous = false;      // 한 문장 인식 후 자동 종료
    this._recognition.interimResults = false;  // 최종 결과만
    this._recognition.maxAlternatives = 1;

    this._recognition.onstart = () => {
      this._setState('listening');
    };

    this._recognition.onresult = (event) => {
      const transcript = event.results[0][0].transcript;
      this._setState('processing');
      if (this.onResult && transcript.trim()) {
        this.onResult(transcript.trim());
      }
      this._setState('idle');
    };

    this._recognition.onerror = (event) => {
      // 'no-speech'는 말을 안 한 경우 → 조용히 처리
      if (event.error !== 'no-speech' && event.error !== 'aborted') {
        console.warn('[STT] 인식 오류:', event.error);
      }
      this._setState('idle');
    };

    this._recognition.onend = () => {
      // 이미 idle이 아닌 경우에만 (onresult/onerror에서 처리 안 된 경우)
      if (this._state !== 'idle') {
        this._setState('idle');
      }
    };

    this._recognition.start();
  },

  /**
   * 녹음 정지
   */
  stop() {
    if (this._recognition) {
      this._recognition.abort();
      this._recognition = null;
    }
    this._setState('idle');
  },

  /**
   * 토글 (시작/정지)
   */
  toggle() {
    if (this._state === 'idle') {
      this.start();
    } else {
      this.stop();
    }
  },

  /**
   * 상태 변경
   */
  _setState(newState) {
    this._state = newState;
    if (this.onStateChange) this.onStateChange(newState);
  },

  /**
   * 현재 상태 조회
   */
  getState() {
    return this._state;
  }
};
